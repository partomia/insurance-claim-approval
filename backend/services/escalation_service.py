from dataclasses import dataclass, field
from typing import Any

from config import get_settings
from models.claim import Claim
from services.llm_service import llm_service

settings = get_settings()

FLAG_MESSAGES = {
    "high_fraud_score": "This claim has a higher fraud risk ({pct}%) and needs extra review",
    "low_evidence_confidence": "Your uploaded documents may be unclear or incomplete ({pct}% confidence)",
    "early_claim_high_amount": "This is a large claim filed soon after the policy started ({days} days in)",
    "clause_mismatch": "The policy section we found may not match what your plan covers",
    "evidence_mismatch": "{message}",
    "extraction_failed": "{message}",
    # Motor-specific flags
    "total_loss_suspected": "Repair cost is close to or above the vehicle's IDV — surveyor review required",
    "vin_mismatch": "The VIN on this claim does not match the vehicle covered by the policy",
    "unlicensed_driver": "Driver's licence details are missing or invalid on this claim",
    "third_party_injury_reported": "Third-party injuries reported — legal team review required",
    "no_police_report_major_loss": "Major-loss claim without a police / FIR report — additional evidence required",
}


@dataclass
class EscalationResult:
    flags: list[str] = field(default_factory=list)
    flag_details: dict[str, Any] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)


class EscalationService:
    def evaluate(self, claim: Claim, merged: dict[str, Any]) -> EscalationResult:
        flags: list[str] = []
        details: dict[str, Any] = {}

        fraud_score = float(merged.get("fraud_score", 0.0))
        if fraud_score >= settings.fraud_review_threshold:
            flags.append("high_fraud_score")
            details["high_fraud_score"] = {
                "fraud_score": fraud_score,
                "threshold": settings.fraud_review_threshold,
            }

        evidence_score = float(merged.get("evidence_confidence_score", 1.0))
        if evidence_score <= settings.evidence_review_threshold:
            flags.append("low_evidence_confidence")
            details["low_evidence_confidence"] = {
                "evidence_confidence": evidence_score,
                "threshold": settings.evidence_review_threshold,
            }

        if merged.get("evidence_mismatch"):
            flags.append("evidence_mismatch")
            issues = merged.get("evidence_issues", [])
            unacked = [i for i in issues if not i.get("acknowledged")]
            msg = "One or more uploaded documents do not match the expected type"
            if unacked:
                msg = unacked[0].get("reason") or msg
            details["evidence_mismatch"] = {"message": msg, "issues": issues}

        extraction_issues = [
            i
            for i in merged.get("evidence_issues", [])
            if i.get("issue_code") == "extraction_failed" and not i.get("acknowledged")
        ]
        if extraction_issues:
            flags.append("extraction_failed")
            first = extraction_issues[0]
            label = first.get("field") or "Document"
            fname = first.get("filename") or "upload"
            reason = first.get("reason") or "Could not extract readable content from this document"
            details["extraction_failed"] = {
                "message": f"{label} ({fname}): {reason}",
                "issues": extraction_issues,
            }

        if claim.policy and claim.policy.effective_date:
            days_since = (claim.incident_datetime - claim.policy.effective_date).days
            # Motor is the only policy type; threshold map still keyed for legacy compatibility.
            policy_type = claim.policy.policy_type or "Motor"
            threshold = settings.early_claim_amount_thresholds.get(policy_type, 10000.0)
            if (
                days_since <= settings.early_claim_days
                and claim.claim_amount > 0.5 * threshold
            ):
                flags.append("early_claim_high_amount")
                details["early_claim_high_amount"] = {
                    "days_since_effective": days_since,
                    "claim_amount": claim.claim_amount,
                    "threshold": threshold,
                }

        retrieved = merged.get("retrieved_clauses", [])
        policy_ctx = claim.policy_context_json or {}
        alignment = llm_service.check_clause_alignment(
            claim.incident_description,
            retrieved,
            policy_ctx,
        )
        if alignment and not alignment.get("aligned", True):
            flags.append("clause_mismatch")
            details["clause_mismatch"] = alignment

        # --- Motor-specific escalation checks -----------------------------
        payout_breakdown = merged.get("payout_breakdown") or {}
        if payout_breakdown.get("is_total_loss"):
            flags.append("total_loss_suspected")
            details["total_loss_suspected"] = {
                "ratio_threshold": payout_breakdown.get("total_loss_ratio_threshold"),
                "salvage_deduction": payout_breakdown.get("salvage_deduction"),
            }

        if claim.policy and claim.vin and claim.policy.covered_vehicle_vin:
            if claim.vin.strip().upper() != claim.policy.covered_vehicle_vin.strip().upper():
                flags.append("vin_mismatch")
                details["vin_mismatch"] = {
                    "claim_vin": claim.vin,
                    "policy_vin": claim.policy.covered_vehicle_vin,
                }

        if not claim.driver_license_number:
            flags.append("unlicensed_driver")
            details["unlicensed_driver"] = {}

        if claim.injuries_reported:
            flags.append("third_party_injury_reported")
            details["third_party_injury_reported"] = {}

        # A "major loss" here means > 50% of coverage limit, and no police report uploaded.
        if claim.policy and claim.claim_amount > 0.5 * (claim.policy.coverage_limit or 0):
            has_police = any(
                (d.doc_type.value if hasattr(d.doc_type, "value") else str(d.doc_type)) == "POLICE_REPORT"
                for d in (claim.documents or [])
            )
            if not has_police:
                flags.append("no_police_report_major_loss")
                details["no_police_report_major_loss"] = {
                    "claim_amount": claim.claim_amount,
                    "coverage_limit": claim.policy.coverage_limit,
                }

        messages = self.build_messages(flags, details)
        return EscalationResult(flags=flags, flag_details=details, messages=messages)

    def build_messages(self, flags: list[str], details: dict[str, Any]) -> list[str]:
        messages: list[str] = []
        for flag in flags:
            detail = details.get(flag, {})
            if flag == "high_fraud_score":
                pct = round(detail.get("fraud_score", 0) * 100)
                threshold = round(detail.get("threshold", 0.4) * 100)
                messages.append(FLAG_MESSAGES[flag].format(pct=pct, threshold=threshold))
            elif flag == "low_evidence_confidence":
                pct = round(detail.get("evidence_confidence", 0) * 100)
                messages.append(FLAG_MESSAGES[flag].format(pct=pct))
            elif flag == "early_claim_high_amount":
                days = detail.get("days_since_effective", settings.early_claim_days)
                messages.append(FLAG_MESSAGES[flag].format(days=days))
            elif flag == "clause_mismatch":
                messages.append(
                    FLAG_MESSAGES[flag].format(
                        retrieved=detail.get("retrieved_ref", "unknown"),
                        expected=detail.get("expected_ref", "unknown"),
                    )
                )
            elif flag == "evidence_mismatch":
                messages.append(FLAG_MESSAGES[flag].format(message=detail.get("message", "Document type mismatch")))
            elif flag == "extraction_failed":
                messages.append(FLAG_MESSAGES[flag].format(message=detail.get("message", "Extraction failed")))
            elif flag in ("total_loss_suspected", "vin_mismatch", "unlicensed_driver",
                          "third_party_injury_reported", "no_police_report_major_loss"):
                messages.append(FLAG_MESSAGES[flag])
        return messages
