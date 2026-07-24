from dataclasses import dataclass, field
from typing import Optional

from models.claim import ClaimStatus


@dataclass
class DecisionInput:
    policy_expired: bool = False
    premium_unpaid: bool = False
    incident_excluded: bool = False
    evidence_missing: bool = False
    fraud_score: float = 0.0
    claim_amount: float = 0.0
    confidence_score: float = 1.0
    evidence_confidence_score: float = 1.0
    fraud_threshold: float = 0.75
    fraud_review_threshold: float = 0.40
    evidence_review_threshold: float = 0.55
    human_review_amount_threshold: float = 500_000.0
    confidence_review_threshold: float = 0.60
    escalation_flags: list[str] = field(default_factory=list)
    escalation_messages: list[str] = field(default_factory=list)


@dataclass
class DecisionResult:
    status: ClaimStatus
    reasoning: str
    human_review_required: bool = False


class DecisionEngine:
    def decide(self, inputs: DecisionInput) -> DecisionResult:
        if inputs.policy_expired:
            return DecisionResult(
                status=ClaimStatus.REJECTED,
                reasoning="Claim rejected: policy has expired or is inactive.",
            )
        if inputs.premium_unpaid:
            return DecisionResult(
                status=ClaimStatus.REJECTED,
                reasoning="Claim rejected: premium payments are not current.",
            )
        if inputs.incident_excluded:
            return DecisionResult(
                status=ClaimStatus.REJECTED,
                reasoning="Claim rejected: incident falls under policy exclusions.",
            )
        if inputs.evidence_missing:
            return DecisionResult(
                status=ClaimStatus.REQUEST_MORE_INFO,
                reasoning="Additional evidence required: mandatory documents are missing.",
            )

        if inputs.escalation_flags:
            flag_summary = "; ".join(inputs.escalation_messages) if inputs.escalation_messages else ", ".join(
                inputs.escalation_flags
            )
            return DecisionResult(
                status=ClaimStatus.PENDING_REVIEW,
                reasoning=f"Claim flagged for manual review: {flag_summary}",
                human_review_required=True,
            )

        if inputs.fraud_score >= inputs.fraud_review_threshold:
            return DecisionResult(
                status=ClaimStatus.PENDING_REVIEW,
                reasoning=f"Claim flagged for manual review due to fraud score ({inputs.fraud_score:.2f}).",
                human_review_required=True,
            )

        if inputs.evidence_confidence_score <= inputs.evidence_review_threshold:
            return DecisionResult(
                status=ClaimStatus.PENDING_REVIEW,
                reasoning=(
                    f"Claim flagged for manual review due to low evidence confidence "
                    f"({inputs.evidence_confidence_score:.2f})."
                ),
                human_review_required=True,
            )

        if inputs.fraud_score > inputs.fraud_threshold:
            return DecisionResult(
                status=ClaimStatus.PENDING_REVIEW,
                reasoning=f"Claim escalated due to high fraud score ({inputs.fraud_score:.2f}).",
                human_review_required=True,
            )
        if inputs.claim_amount > inputs.human_review_amount_threshold:
            return DecisionResult(
                status=ClaimStatus.PENDING_REVIEW,
                reasoning=f"Claim amount ({inputs.claim_amount:,.0f}) exceeds auto-approval threshold.",
                human_review_required=True,
            )
        if inputs.confidence_score < inputs.confidence_review_threshold:
            return DecisionResult(
                status=ClaimStatus.PENDING_REVIEW,
                reasoning=f"Confidence score ({inputs.confidence_score:.2f}) below threshold.",
                human_review_required=True,
            )
        return DecisionResult(
            status=ClaimStatus.ANALYSIS_COMPLETE,
            reasoning="AI analysis complete: claim appears covered with strong approval likelihood. Review and submit to your insurer.",
        )
