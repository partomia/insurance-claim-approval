from dataclasses import dataclass, field

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
    SIGNAL_WEIGHTS = {
        "duplicate_claim": 0.30,
        "abnormal_amount": 0.25,
        "blacklist": 0.35,
        "duplicate_document": 0.15,
        "policy_abuse": 0.20,
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
