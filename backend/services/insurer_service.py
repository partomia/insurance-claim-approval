from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from models.claim import Claim, ClaimStatus
from models.insurer_user import InsurerUser
from services.escalation_service import EscalationService
from services.agent_service import agent_service


INSURER_VISIBLE_STATUSES = (
    ClaimStatus.SUBMITTED_TO_INSURER,
    ClaimStatus.APPROVED,
    ClaimStatus.REJECTED,
)


class InsurerService:
    def _base_query(self, db: Session):
        return (
            db.query(Claim)
            .options(
                joinedload(Claim.customer),
                joinedload(Claim.policy),
                joinedload(Claim.decision),
                joinedload(Claim.documents),
            )
            .filter(Claim.status.in_(INSURER_VISIBLE_STATUSES))
            .order_by(Claim.updated_at.desc())
        )

    def get_claim(self, db: Session, claim_id: int) -> Optional[Claim]:
        return self._base_query(db).filter(Claim.id == claim_id).first()

    def claim_to_item(self, claim: Claim) -> dict[str, Any]:
        approval = None
        if claim.decision:
            approval = claim.decision.approval_probability or claim.decision.confidence_score
        issues_raw = claim.evidence_issues if isinstance(claim.evidence_issues, list) else []
        doc_count = len(claim.documents or []) if claim.documents else 0
        flags = claim.escalation_flags if isinstance(claim.escalation_flags, list) else []
        messages = claim.escalation_messages if isinstance(claim.escalation_messages, list) else []
        if flags and not messages:
            messages = EscalationService().build_messages(flags, {})
        return {
            "id": claim.id,
            "claim_id": claim.claim_number,
            "status": claim.status.value,
            "claim_amount": claim.claim_amount,
            "customer_id": claim.customer_id,
            "customer_name": claim.customer.full_name if claim.customer else "",
            "customer_email": claim.customer.email if claim.customer else "",
            "policy_type": claim.policy.policy_type if claim.policy else None,
            "policy_number": claim.policy.policy_number if claim.policy else None,
            "assigned_agent": claim.assigned_agent,
            "escalation_flags": flags,
            "escalation_messages": messages,
            "created_at": claim.created_at,
            "updated_at": claim.updated_at,
            "approval_probability": approval,
            "fraud_score": claim.decision.fraud_score if claim.decision else None,
            "payable_amount": claim.decision.payable_amount if claim.decision else None,
            "document_count": doc_count,
            "has_document_issues": len(issues_raw) > 0,
        }

    def list_claims(self, db: Session, *, status: Optional[str] = None) -> list[dict[str, Any]]:
        query = self._base_query(db)
        if status:
            try:
                query = query.filter(Claim.status == ClaimStatus(status.upper()))
            except ValueError:
                pass
        elif status is None:
            query = query.filter(Claim.status == ClaimStatus.SUBMITTED_TO_INSURER)
        return [self.claim_to_item(c) for c in query.all()]

    def list_all_claims(self, db: Session, *, status: Optional[str] = None) -> list[dict[str, Any]]:
        query = self._base_query(db)
        if status:
            try:
                query = query.filter(Claim.status == ClaimStatus(status.upper()))
            except ValueError:
                pass
        return [self.claim_to_item(c) for c in query.all()]

    def get_dashboard_stats(self, db: Session) -> dict[str, Any]:
        claims = self._base_query(db).all()
        pending = [c for c in claims if c.status == ClaimStatus.SUBMITTED_TO_INSURER]
        approved = [c for c in claims if c.status == ClaimStatus.APPROVED]
        rejected = [c for c in claims if c.status == ClaimStatus.REJECTED]
        total_payout = sum(
            (c.decision.payable_amount if c.decision else 0.0) for c in approved
        )
        return {
            "pending_decision": len(pending),
            "approved_total": len(approved),
            "rejected_total": len(rejected),
            "total_approved_payout": round(total_payout, 2),
            "recent_submissions": [self.claim_to_item(c) for c in pending[:10]],
        }

    def list_claim_documents(self, claim: Claim) -> list[dict[str, Any]]:
        return agent_service.list_claim_documents(claim)

    def build_policy_requirements(self, claim: Claim) -> dict[str, Any]:
        return agent_service.build_policy_requirements(claim)


insurer_service = InsurerService()
