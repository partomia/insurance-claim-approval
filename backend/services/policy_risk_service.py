"""Single source of truth for reading PolicyRiskSignal data (Phase 4).

Backs two UI surfaces that must show identical numbers for the same policy:
  - Insurer "Book of Business" page (list/filter/sort all lakehouse-ingested
    policies by risk) — see routers/insurer.py book_of_business endpoints.
  - Claim Insights panel (Option B) — surfaces a policy's risk signal
    alongside the AI fraud assessment when reviewing a specific claim — see
    services/insights_service.py.

Data here is read-only from the app's perspective: it's populated exclusively
by scripts/ingest_lakehouse.py (Phase 3), which itself pulls from CDE's
claims-analytics gold table (cde/README.md).
"""

from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from models.policy import Policy
from models.policy_risk_signal import PolicyRiskSignal


def risk_signal_to_dict(rs: PolicyRiskSignal) -> dict[str, Any]:
    return {
        "total_claims_count": rs.total_claims_count,
        "claims_count_12m": rs.claims_count_12m,
        "total_claimed_amount": rs.total_claimed_amount,
        "avg_claim_amount": rs.avg_claim_amount,
        "amount_vs_segment_avg_pct": rs.amount_vs_segment_avg_pct,
        "claim_frequency_percentile": rs.claim_frequency_percentile,
        "linked_high_risk_garage": rs.linked_high_risk_garage,
        "fraud_risk_score": rs.fraud_risk_score,
        "claim_risk_band": rs.claim_risk_band,
        "source": rs.source,
        "ingested_at": rs.ingested_at,
    }


class PolicyRiskService:
    def get_for_policy(self, db: Session, policy_id: int) -> Optional[dict[str, Any]]:
        rs = db.query(PolicyRiskSignal).filter(PolicyRiskSignal.policy_id == policy_id).first()
        return risk_signal_to_dict(rs) if rs else None

    def _base_query(self, db: Session):
        return (
            db.query(Policy)
            .join(PolicyRiskSignal, PolicyRiskSignal.policy_id == Policy.id)
            .options(
                joinedload(Policy.customer),
                joinedload(Policy.provider),
                joinedload(Policy.risk_signal),
            )
        )

    def policy_to_item(self, policy: Policy) -> dict[str, Any]:
        rs = policy.risk_signal
        return {
            "policy_id": policy.id,
            "policy_number": policy.policy_number,
            "customer_name": policy.customer.full_name if policy.customer else "",
            "customer_email": policy.customer.email if policy.customer else "",
            "provider_name": policy.provider.name if policy.provider else None,
            "policy_type": policy.policy_type,
            "status": policy.status.value,
            "coverage_limit": policy.coverage_limit,
            "premium_amount": policy.premium_amount,
            "covered_make": policy.covered_make,
            "covered_model": policy.covered_model,
            "risk": risk_signal_to_dict(rs) if rs else None,
        }

    def list_policies(
        self,
        db: Session,
        *,
        risk_band: Optional[str] = None,
        min_score: Optional[float] = None,
        high_risk_garage_only: bool = False,
        sort: str = "score_desc",
    ) -> list[dict[str, Any]]:
        query = self._base_query(db)

        if risk_band:
            query = query.filter(PolicyRiskSignal.claim_risk_band == risk_band.upper())
        if min_score is not None:
            query = query.filter(PolicyRiskSignal.fraud_risk_score >= min_score)
        if high_risk_garage_only:
            query = query.filter(PolicyRiskSignal.linked_high_risk_garage.is_(True))

        if sort == "score_asc":
            query = query.order_by(PolicyRiskSignal.fraud_risk_score.asc())
        elif sort == "claims_desc":
            query = query.order_by(PolicyRiskSignal.total_claims_count.desc())
        else:
            query = query.order_by(PolicyRiskSignal.fraud_risk_score.desc())

        return [self.policy_to_item(p) for p in query.all()]

    def get_stats(self, db: Session) -> dict[str, Any]:
        rows = db.query(PolicyRiskSignal).all()
        total = len(rows)
        low = sum(1 for r in rows if r.claim_risk_band == "LOW")
        medium = sum(1 for r in rows if r.claim_risk_band == "MEDIUM")
        high = sum(1 for r in rows if r.claim_risk_band == "HIGH")
        garage_linked = sum(1 for r in rows if r.linked_high_risk_garage)
        avg_score = round(sum(r.fraud_risk_score for r in rows) / total, 2) if total else 0.0
        return {
            "total_policies": total,
            "low_count": low,
            "medium_count": medium,
            "high_count": high,
            "high_risk_garage_linked_count": garage_linked,
            "avg_fraud_risk_score": avg_score,
        }


policy_risk_service = PolicyRiskService()
