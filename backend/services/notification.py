import logging

from sqlalchemy.orm import Session

from models.claim import Claim, ClaimStatus

logger = logging.getLogger(__name__)


class NotificationService:
    def notify_customer(self, db: Session, claim: Claim, decision_status: ClaimStatus) -> dict:
        customer = claim.customer
        message = self._build_message(claim, decision_status)
        logger.info(
            "NOTIFY customer=%s claim=%s status=%s message=%s",
            customer.email if customer else "unknown",
            claim.claim_number,
            decision_status.value,
            message,
        )
        return {
            "channel": "email",
            "recipient": customer.email if customer else None,
            "claim_number": claim.claim_number,
            "status": decision_status.value,
            "message": message,
            "sent": True,
        }

    def _build_message(self, claim: Claim, status: ClaimStatus) -> str:
        if status == ClaimStatus.APPROVED:
            amount = claim.decision.payable_amount if claim.decision else claim.claim_amount
            return f"Your claim {claim.claim_number} has been approved. Payable amount: {amount:,.2f}."
        if status == ClaimStatus.REJECTED:
            return f"Your claim {claim.claim_number} has been rejected. Please contact support for details."
        if status == ClaimStatus.REQUEST_MORE_INFO:
            return f"Additional information is required for claim {claim.claim_number}."
        if status in (ClaimStatus.HUMAN_REVIEW, ClaimStatus.ESCALATE):
            return f"Your claim {claim.claim_number} is under manual review. We will contact you shortly."
        return f"Your claim {claim.claim_number} status is {status.value}."
