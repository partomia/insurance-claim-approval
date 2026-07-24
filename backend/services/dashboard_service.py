from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, joinedload

from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.platform import CustomerProfile
from services.kyc_service import effective_kyc_status, is_kyc_verified
from models.policy import Policy, PolicyStatus, PremiumPayment
from services.analysis_service import analysis_to_dict

PENDING_STATUSES = {
    ClaimStatus.PENDING,
    ClaimStatus.PROCESSING,
    ClaimStatus.PENDING_REVIEW,
    ClaimStatus.HUMAN_REVIEW,
    ClaimStatus.ESCALATE,
    ClaimStatus.REQUEST_MORE_INFO,
    ClaimStatus.ANALYSIS_COMPLETE,
}

STATUS_LABELS = {
    ClaimStatus.APPROVED: "Approved by Insurer",
    ClaimStatus.REJECTED: "Rejected by Insurer",
    ClaimStatus.DRAFT: "Draft",
    ClaimStatus.PENDING: "Pending Analysis",
    ClaimStatus.PROCESSING: "AI Analyzing",
    ClaimStatus.ANALYSIS_COMPLETE: "Analysis Complete",
    ClaimStatus.PENDING_REVIEW: "Expert Review",
    ClaimStatus.HUMAN_REVIEW: "Expert Review",
    ClaimStatus.ESCALATE: "Expert Review",
    ClaimStatus.REQUEST_MORE_INFO: "Needs Documents",
    ClaimStatus.SUBMISSION_READY: "Ready to Submit",
    ClaimStatus.SUBMITTED_TO_INSURER: "Submitted to Insurer",
}


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _month_label(key: str) -> str:
    return datetime.strptime(key, "%Y-%m").strftime("%b %Y")


class DashboardService:
    def get_stats(self, db: Session, customer_id: int) -> dict[str, Any]:
        policies = (
            db.query(Policy)
            .options(joinedload(Policy.provider))
            .filter(Policy.customer_id == customer_id)
            .all()
        )
        active_policies = sum(1 for policy in policies if policy.status == PolicyStatus.ACTIVE)

        claims = (
            db.query(Claim)
            .options(joinedload(Claim.policy).joinedload(Policy.provider), joinedload(Claim.decision))
            .filter(Claim.customer_id == customer_id)
            .order_by(Claim.created_at.desc())
            .all()
        )

        submitted = [claim for claim in claims if claim.status != ClaimStatus.DRAFT]
        approved_claims = sum(1 for claim in submitted if claim.status == ClaimStatus.APPROVED)
        rejected_claims = sum(1 for claim in submitted if claim.status == ClaimStatus.REJECTED)
        pending_claims = sum(1 for claim in submitted if claim.status in PENDING_STATUSES)
        draft_claims = sum(1 for claim in claims if claim.status == ClaimStatus.DRAFT)

        total_claim_amount = round(sum(claim.claim_amount for claim in submitted), 2)
        approved_payout = round(
            sum(
                claim.decision.payable_amount
                for claim in submitted
                if claim.status == ClaimStatus.APPROVED and claim.decision
            ),
            2,
        )

        status_counts = Counter(claim.status for claim in claims)
        claims_by_status = [
            {
                "status": status.value,
                "label": STATUS_LABELS.get(status, status.value),
                "count": count,
            }
            for status, count in sorted(status_counts.items(), key=lambda item: item[0].value)
            if count > 0
        ]

        now = datetime.utcnow()
        month_keys = [
            _month_key(now - timedelta(days=30 * offset))
            for offset in range(5, -1, -1)
        ]
        monthly_counts: dict[str, int] = defaultdict(int)
        for claim in submitted:
            monthly_counts[_month_key(claim.created_at)] += 1
        claims_by_month = [
            {"month": _month_label(key), "count": monthly_counts.get(key, 0)}
            for key in month_keys
        ]

        type_counts: Counter[str] = Counter()
        type_amounts: Counter[str] = Counter()
        for claim in submitted:
            policy_type = claim.policy.policy_type if claim.policy else "Unlinked"
            type_counts[policy_type] += 1
            type_amounts[policy_type] += claim.claim_amount

        claims_by_policy_type = [
            {
                "policy_type": policy_type,
                "count": count,
                "total_amount": round(type_amounts[policy_type], 2),
            }
            for policy_type, count in type_counts.most_common()
        ]

        coverage_by_policy = [
            {
                "policy_number": policy.policy_number,
                "policy_type": policy.policy_type,
                "coverage_limit": policy.coverage_limit,
                "claimed_amount": round(
                    sum(
                        claim.claim_amount
                        for claim in submitted
                        if claim.policy_id == policy.id
                    ),
                    2,
                ),
            }
            for policy in policies
        ]

        recent_activity = [
            {
                "id": claim.id,
                "claim_id": claim.claim_number,
                "status": claim.status.value,
                "claim_amount": claim.claim_amount,
                "incident_description": (claim.incident_description or "")[:80],
                "policy_type": claim.policy.policy_type if claim.policy else None,
                "created_at": claim.created_at,
            }
            for claim in submitted[:6]
        ]

        profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer_id).first()
        kyc_status = effective_kyc_status(profile).value
        kyc_complete = is_kyc_verified(profile)

        connected_policies = []
        for policy in policies:
            claimed = sum(c.claim_amount for c in submitted if c.policy_id == policy.id)
            latest_payment = (
                db.query(PremiumPayment)
                .filter(PremiumPayment.policy_id == policy.id)
                .order_by(PremiumPayment.paid_at.desc())
                .first()
            )
            connected_policies.append(
                {
                    "id": policy.id,
                    "policy_number": policy.policy_number,
                    "policy_type": policy.policy_type,
                    "status": policy.status.value,
                    "coverage_limit": policy.coverage_limit,
                    "deductible": policy.deductible,
                    "co_pay_pct": policy.co_pay_pct,
                    "exclusions": policy.exclusions or [],
                    "premium_status": latest_payment.status.value if latest_payment else "PAID",
                    "effective_date": policy.effective_date,
                    "expiry_date": policy.expiry_date,
                    "document_count": 0,
                    "provider_name": policy.provider.name if policy.provider else None,
                    "premium_amount": policy.premium_amount,
                    "coverage_remaining": max(0, policy.coverage_limit - claimed),
                }
            )

        recent_analyses = []
        for claim in submitted[:5]:
            if claim.decision:
                recent_analyses.append(
                    {
                        "claim_id": claim.claim_number,
                        "claim_db_id": claim.id,
                        "status": claim.status.value,
                        **analysis_to_dict(claim.decision, claim),
                    }
                )

        notifications: list[dict[str, Any]] = []
        recommended_actions: list[str] = []
        if not kyc_complete:
            recommended_actions.append("Complete one-time KYC verification")
            notifications.append({"type": "kyc", "message": "Complete KYC to connect policies and file claims"})
        if kyc_complete and not policies:
            recommended_actions.append("Connect your insurance policy")
        for claim in submitted[:3]:
            if claim.status == ClaimStatus.REQUEST_MORE_INFO:
                notifications.append({"type": "documents", "message": f"Upload missing documents for {claim.claim_number}"})
            if claim.status == ClaimStatus.PENDING_REVIEW:
                notifications.append({"type": "expert", "message": f"Claim Expert assigned for {claim.claim_number}"})
            if claim.status == ClaimStatus.SUBMISSION_READY:
                recommended_actions.append(f"Submit {claim.claim_number} to your insurer")

        return {
            "active_policies": active_policies,
            "total_policies": len(policies),
            "total_claims": len(submitted),
            "draft_claims": draft_claims,
            "approved_claims": approved_claims,
            "pending_claims": pending_claims,
            "rejected_claims": rejected_claims,
            "total_claim_amount": total_claim_amount,
            "approved_payout": approved_payout,
            "claims_by_status": claims_by_status,
            "claims_by_month": claims_by_month,
            "claims_by_policy_type": claims_by_policy_type,
            "coverage_by_policy": coverage_by_policy,
            "recent_activity": recent_activity,
            "kyc_status": kyc_status,
            "kyc_complete": kyc_complete,
            "connected_policies": connected_policies,
            "recent_analyses": recent_analyses,
            "notifications": notifications,
            "recommended_actions": recommended_actions,
        }
