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
            policy_type = claim.policy.policy_type or "Auto"
            threshold = settings.early_claim_amount_thresholds.get(policy_type, 5000.0)
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
        return messages
