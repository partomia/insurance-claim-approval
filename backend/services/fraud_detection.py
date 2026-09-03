from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session

from config import get_settings
from models.audit import FraudAssessment
from models.claim import Claim, ClaimStatus
from models.customer import Customer
from services.evidence_analysis import EvidenceAnalysisResult

settings = get_settings()


@dataclass
class FraudDetectionResult:
    fraud_score: float
    signals: list[str] = field(default_factory=list)
    blacklist_hit: bool = False


class FraudDetectionService:
    """Motor-vehicle fraud rule engine.

    Rule signals cover motor-specific patterns: VIN mismatch, IDV/claim ratio
    on aged vehicles, third-party without police report, prior-claim clustering,
    device-hash reuse across customers, and duplicate-document / duplicate-claim
    baselines from the general layer.
    """

    # Weights are calibrated so any single "hard" fraud signal (blacklist, VIN
    # mismatch, duplicate claim, device-hash reuse) on its own meets the review
    # threshold (settings.fraud_review_threshold, default 0.40). "Soft" signals
    # stay below it individually and only push into review when they stack.
    SIGNAL_WEIGHTS = {
        "duplicate_claim": 0.45,
        "abnormal_amount": 0.25,
        "blacklist": 0.50,
        "duplicate_document": 0.20,
        "policy_abuse": 0.25,
        # Motor-specific
        "vin_mismatch": 0.45,
        "idv_ratio_aged_vehicle": 0.20,
        "third_party_no_police_report": 0.25,
        "device_hash_reuse": 0.45,
        "unlicensed_driver": 0.40,
    }

    def detect(
        self,
        db: Session,
        claim: Claim,
        evidence_result: EvidenceAnalysisResult | None = None,
    ) -> FraudDetectionResult:
        signals: list[str] = []
        score = 0.0

        customer = db.query(Customer).filter(Customer.id == claim.customer_id).first()
        if customer and customer.blacklist_flag:
            score += self.SIGNAL_WEIGHTS["blacklist"]
            signals.append("Customer on blacklist/watchlist")

        duplicate_claims = (
            db.query(Claim)
            .filter(
                Claim.customer_id == claim.customer_id,
                Claim.id != claim.id,
                Claim.incident_description == claim.incident_description,
                Claim.claim_amount == claim.claim_amount,
            )
            .count()
        )
        if duplicate_claims > 0:
            score += self.SIGNAL_WEIGHTS["duplicate_claim"]
            signals.append(f"Duplicate claim pattern detected ({duplicate_claims} similar claims)")

        policy = claim.policy
        if policy and claim.claim_amount > policy.coverage_limit * 0.9:
            score += self.SIGNAL_WEIGHTS["abnormal_amount"]
            signals.append("Claim amount near or above coverage limit")

        recent_claims = (
            db.query(Claim)
            .filter(
                Claim.customer_id == claim.customer_id,
                Claim.id != claim.id,
                Claim.created_at >= claim.created_at.replace(day=1),
            )
            .count()
        )
        if recent_claims >= 3:
            score += self.SIGNAL_WEIGHTS["policy_abuse"]
            signals.append("High claim frequency this period")

        if evidence_result and len(evidence_result.duplicate_uploads) > 0:
            score += self.SIGNAL_WEIGHTS["duplicate_document"]
            signals.append("Duplicate document uploads detected")

        # --- Motor-specific rules -----------------------------------------
        if policy and claim.vin and policy.covered_vehicle_vin:
            if claim.vin.strip().upper() != policy.covered_vehicle_vin.strip().upper():
                score += self.SIGNAL_WEIGHTS["vin_mismatch"]
                signals.append(
                    f"VIN on claim ({claim.vin}) does not match policy's covered vehicle "
                    f"({policy.covered_vehicle_vin})"
                )

        if (
            policy
            and claim.vehicle_year
            and claim.claim_amount > policy.coverage_limit * 0.8
        ):
            vehicle_age = max(0, claim.incident_datetime.year - claim.vehicle_year)
            if vehicle_age >= 5:
                score += self.SIGNAL_WEIGHTS["idv_ratio_aged_vehicle"]
                signals.append(
                    f"Claim > 80% of IDV on a {vehicle_age}-year-old vehicle"
                )

        if claim.third_party_involved:
            has_police_report = any(
                d.doc_type.value == "POLICE_REPORT" for d in (claim.documents or [])
            )
            if not has_police_report:
                score += self.SIGNAL_WEIGHTS["third_party_no_police_report"]
                signals.append("Third-party involvement without police / FIR report")

        if claim.injuries_reported:
            has_police_report = any(
                d.doc_type.value == "POLICE_REPORT" for d in (claim.documents or [])
            )
            if not has_police_report:
                score += self.SIGNAL_WEIGHTS["third_party_no_police_report"]
                signals.append("Injuries reported without police / FIR report")

        if claim.submission_device_hash:
            recent_window = claim.created_at - timedelta(days=90)
            device_reuse = (
                db.query(Claim)
                .filter(
                    Claim.submission_device_hash == claim.submission_device_hash,
                    Claim.customer_id != claim.customer_id,
                    Claim.created_at >= recent_window,
                )
                .count()
            )
            if device_reuse >= 1:
                score += self.SIGNAL_WEIGHTS["device_hash_reuse"]
                signals.append(
                    f"Submission device fingerprint shared across {device_reuse} other customers in the last 90 days"
                )

        # Unlicensed driver — no license number provided AND no KYC on file.
        if not claim.driver_license_number:
            score += self.SIGNAL_WEIGHTS["unlicensed_driver"] * 0.5
            signals.append("Driver's licence details missing on claim")

        fraud_score = round(min(score, 1.0), 4)
        return FraudDetectionResult(
            fraud_score=fraud_score,
            signals=signals,
            blacklist_hit=bool(customer and customer.blacklist_flag),
        )

    def persist(self, db: Session, claim_id: int, result: FraudDetectionResult) -> FraudAssessment:
        assessment = db.query(FraudAssessment).filter(FraudAssessment.claim_id == claim_id).first()
        if assessment is None:
            assessment = FraudAssessment(claim_id=claim_id)
            db.add(assessment)
        assessment.fraud_score = result.fraud_score
        assessment.signals = result.signals
        assessment.blacklist_hit = result.blacklist_hit
        db.commit()
        db.refresh(assessment)
        return assessment
