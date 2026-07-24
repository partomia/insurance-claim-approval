from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models.claim import Claim
from models.policy import Policy, PolicyStatus, PremiumPayment, PremiumPaymentStatus


@dataclass
class PolicyValidationResult:
    eligible: bool
    policy_expired: bool = False
    premium_unpaid: bool = False
    incident_excluded: bool = False
    within_waiting_period: bool = False
    exceeds_coverage: bool = False
    violations: list[str] = field(default_factory=list)
    policy_status: str = ""
    premium_status: str = ""


class PolicyValidationService:
    def validate(self, db: Session, claim: Claim) -> PolicyValidationResult:
        policy = db.query(Policy).filter(Policy.id == claim.policy_id).first()
        if not policy:
            return PolicyValidationResult(
                eligible=False,
                violations=["Policy not found"],
            )

        result = PolicyValidationResult(
            eligible=True,
            policy_status=policy.status.value,
        )

        now = datetime.utcnow()
        if policy.status == PolicyStatus.EXPIRED or policy.expiry_date < now:
            result.eligible = False
            result.policy_expired = True
            result.violations.append("Policy has expired")

        if policy.status in (PolicyStatus.LAPSED, PolicyStatus.CANCELLED):
            result.eligible = False
            result.policy_expired = True
            result.violations.append(f"Policy status is {policy.status.value}")

        latest_payment = (
            db.query(PremiumPayment)
            .filter(PremiumPayment.policy_id == policy.id)
            .order_by(PremiumPayment.paid_at.desc())
            .first()
        )
        if latest_payment and latest_payment.status != PremiumPaymentStatus.PAID:
            result.eligible = False
            result.premium_unpaid = True
            result.premium_status = latest_payment.status.value
            result.violations.append("Premium payment is not current")
        else:
            result.premium_status = "PAID"

        if policy.waiting_period_days > 0:
            days_since_effective = (claim.incident_datetime - policy.effective_date).days
            if days_since_effective < policy.waiting_period_days:
                result.eligible = False
                result.within_waiting_period = True
                result.violations.append(
                    f"Incident within waiting period ({policy.waiting_period_days} days)"
                )

        exclusions = policy.exclusions or []
        incident_lower = claim.incident_description.lower()
        for exclusion in exclusions:
            if exclusion.lower() in incident_lower:
                result.eligible = False
                result.incident_excluded = True
                result.violations.append(f"Incident matches exclusion: {exclusion}")

        if claim.claim_amount > policy.coverage_limit:
            result.exceeds_coverage = True
            result.violations.append(
                f"Claim amount exceeds coverage limit ({policy.coverage_limit})"
            )

        return result
