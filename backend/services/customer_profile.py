from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.platform import CustomerProfile
from models.policy import PremiumPayment, PremiumPaymentStatus


@dataclass
class CustomerProfileResult:
    customer_risk_score: float
    premium_history_score: float
    claim_frequency_score: float
    tenure_score: float
    prior_claims_count: int
    policy_tenure_days: int
    signals: list[str] = field(default_factory=list)


class CustomerProfileService:
    def analyze(self, db: Session, claim: Claim) -> CustomerProfileResult:
        customer = db.query(Customer).filter(Customer.id == claim.customer_id).first()
        policy = claim.policy

        prior_claims = (
            db.query(Claim)
            .filter(
                Claim.customer_id == claim.customer_id,
                Claim.id != claim.id,
                Claim.status.in_([ClaimStatus.APPROVED, ClaimStatus.ESCALATE, ClaimStatus.HUMAN_REVIEW]),
            )
            .count()
        )

        tenure_days = (datetime.utcnow() - policy.effective_date).days if policy else 0

        payments = (
            db.query(PremiumPayment)
            .filter(PremiumPayment.policy_id == claim.policy_id)
            .all()
        )
        unpaid = sum(1 for p in payments if p.status != PremiumPaymentStatus.PAID)
        premium_score = min(unpaid * 0.25, 1.0)

        frequency_score = min(prior_claims * 0.15, 1.0)
        tenure_score = max(0.0, 1.0 - min(tenure_days / 365, 1.0))

        # Motor-specific: prior motor claims in the last 12 months.
        one_year_ago = datetime.utcnow() - timedelta(days=365)
        prior_motor_claims_12mo = (
            db.query(Claim)
            .filter(
                Claim.customer_id == claim.customer_id,
                Claim.id != claim.id,
                Claim.created_at >= one_year_ago,
            )
            .count()
        )

        # Motor-specific: does the customer have saved vehicles or garages on file?
        profile = (
            db.query(CustomerProfile)
            .filter(CustomerProfile.customer_id == claim.customer_id)
            .first()
        )
        saved_vehicles_count = len(profile.saved_vehicles or []) if profile else 0
        saved_garages_count = len(profile.saved_garages or []) if profile else 0

        signals: list[str] = []
        if customer and customer.blacklist_flag:
            signals.append("Customer on internal watchlist")
        if prior_motor_claims_12mo >= 3:
            signals.append(
                f"prior_motor_claims_12mo={prior_motor_claims_12mo} (elevated frequency)"
            )
        if saved_vehicles_count == 0:
            signals.append("No vehicles saved to customer profile")

        risk = min(
            premium_score * 0.3 + frequency_score * 0.4 + tenure_score * 0.3,
            1.0,
        )
        if customer and customer.blacklist_flag:
            risk = min(risk + 0.3, 1.0)

        return CustomerProfileResult(
            customer_risk_score=round(risk, 4),
            premium_history_score=round(premium_score, 4),
            claim_frequency_score=round(frequency_score, 4),
            tenure_score=round(tenure_score, 4),
            prior_claims_count=prior_claims,
            policy_tenure_days=tenure_days,
            signals=signals,
        )
