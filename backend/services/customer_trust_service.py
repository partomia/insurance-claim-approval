"""Customer Trust Score — a 0-100 score + tier + reason codes built from a
customer's bureau / driving-record / relationship data (CustomerProfileSignal)
plus a few in-app facts (KYC status, the policy's No-Claim Bonus).

How the tier is used (services/claim_pipeline.py -> decision_engine.py):
  - PREFERRED: auto-approval amount limit x trust_preferred_amount_multiplier
  - STANDARD:  unchanged
  - WATCH:     auto-approval amount limit x trust_watch_amount_multiplier
  - UNSCORED:  no profile data on file -> unchanged (pre-trust behaviour)

The tier decides how fast a claim moves, never whether a covered claim is
paid: nothing here can produce REJECTED. Two financial/behavioural patterns
are additionally exposed as *soft* fraud signals (fraud_signals()), weighted
in fraud_detection.py so neither can reach the review threshold on its own.

driver_age is deliberately not an input (experience is measured by
years_licensed instead), and no protected attribute is stored at all.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import get_settings
from models.customer import Customer
from models.customer_profile_signal import CustomerProfileSignal
from models.platform import CustomerProfile
from models.policy import Policy
from services.kyc_service import is_kyc_verified

settings = get_settings()

TIER_PREFERRED = "PREFERRED"
TIER_STANDARD = "STANDARD"
TIER_WATCH = "WATCH"
TIER_UNSCORED = "UNSCORED"

COMPONENT_WEIGHTS = {
    "credit": 0.30,
    "financial_stability": 0.10,
    "driving_record": 0.20,
    "relationship": 0.15,
    "claims_elsewhere": 0.15,
    "identity": 0.10,
}

FINANCIAL_STRESS_CREDIT_MAX = 600
CROSS_INSURER_CLAIMS_MIN = 3


@dataclass
class TrustReason:
    code: str
    label: str
    impact: str  # positive / negative / neutral


@dataclass
class TrustScoreResult:
    score: Optional[int]
    tier: str
    reasons: list[TrustReason] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    credit_score: Optional[int] = None
    credit_band: Optional[str] = None
    driving_record_band: Optional[str] = None
    source: Optional[str] = None
    as_of: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["as_of"] = self.as_of.isoformat() if self.as_of else None
        return data


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def tier_for_score(score: Optional[int]) -> str:
    if score is None:
        return TIER_UNSCORED
    if score >= settings.trust_preferred_min_score:
        return TIER_PREFERRED
    if score >= settings.trust_standard_min_score:
        return TIER_STANDARD
    return TIER_WATCH


def amount_multiplier_for_tier(tier: str) -> float:
    if tier == TIER_PREFERRED:
        return settings.trust_preferred_amount_multiplier
    if tier == TIER_WATCH:
        return settings.trust_watch_amount_multiplier
    return 1.0


def compute_trust_score(
    signal: Optional[CustomerProfileSignal],
    *,
    kyc_verified: bool = False,
    ncb_pct: Optional[float] = None,
) -> TrustScoreResult:
    """Pure scoring function — no DB access, so it's trivially testable."""
    if signal is None:
        return TrustScoreResult(
            score=None,
            tier=TIER_UNSCORED,
            reasons=[TrustReason("no_profile_data", "No bureau or driving-record data on file — standard rules apply", "neutral")],
        )

    reasons: list[TrustReason] = []
    components: dict[str, float] = {}

    # Credit
    cs = signal.credit_score
    if cs is None:
        components["credit"] = 0.5
        reasons.append(TrustReason("credit_no_hit", "No credit bureau record (treated as neutral)", "neutral"))
    else:
        components["credit"] = _clamp((cs - 500) / 300)
        if cs >= 750:
            reasons.append(TrustReason("credit_excellent", f"Excellent credit score ({cs})", "positive"))
        elif cs >= 700:
            reasons.append(TrustReason("credit_good", f"Good credit score ({cs})", "positive"))
        elif cs < 650:
            reasons.append(TrustReason("credit_low", f"Low credit score ({cs})", "negative"))

    # Financial stability
    defaults = signal.loan_defaults_12m or 0
    components["financial_stability"] = {0: 1.0, 1: 0.4}.get(defaults, 0.0)
    if defaults:
        reasons.append(TrustReason("loan_defaults", f"{defaults} loan default(s) in the last 12 months", "negative"))

    # Driving record
    yl = signal.years_licensed
    experience = 0.5 if yl is None else _clamp(yl / 8)
    violations = signal.traffic_violations_3y or 0
    record = 0.0 if signal.dui_history else _clamp(1 - 0.25 * violations)
    components["driving_record"] = round(0.4 * experience + 0.6 * record, 4)
    if signal.dui_history:
        reasons.append(TrustReason("dui_history", "Drunk-driving offence on record", "negative"))
    if violations:
        reasons.append(TrustReason("traffic_violations", f"{violations} traffic violation(s) in the last 3 years", "negative"))
    elif not signal.dui_history and yl is not None and yl >= 5:
        reasons.append(TrustReason("clean_record", f"Clean driving record, licensed {yl} years", "positive"))
    if yl is not None and yl < 2:
        reasons.append(TrustReason("new_driver", f"Newly licensed driver ({yl} yr)", "negative"))

    # Relationship with the insurer
    tenure_years = signal.years_with_insurer or 0.0
    tenure = _clamp(tenure_years / 5)
    multi_policy = 1.0 if (signal.policies_held or 1) >= 2 else 0.5
    ncb = 0.5 if ncb_pct is None else _clamp(ncb_pct / 50)
    components["relationship"] = round(0.5 * tenure + 0.2 * multi_policy + 0.3 * ncb, 4)
    if tenure_years >= 3:
        reasons.append(TrustReason("long_tenure", f"Customer for {tenure_years:g} years", "positive"))
    if ncb_pct is not None and ncb_pct >= 20:
        reasons.append(TrustReason("no_claim_bonus", f"{ncb_pct:g}% No-Claim Bonus on this policy", "positive"))

    # Claims at other insurers (industry bureau)
    other_claims = signal.other_insurer_claims_3y or 0
    components["claims_elsewhere"] = {0: 1.0, 1: 0.75, 2: 0.45}.get(other_claims, 0.0)
    if other_claims >= 2:
        reasons.append(TrustReason("claims_elsewhere", f"{other_claims} claims with other insurers in 3 years", "negative"))

    # Identity
    identity = 1.0 if kyc_verified else 0.5
    if signal.address_changed_90d:
        identity -= 0.5
        reasons.append(TrustReason("address_changed", "Address changed in the last 90 days", "negative"))
    components["identity"] = _clamp(identity)
    if kyc_verified:
        reasons.append(TrustReason("kyc_verified", "KYC verified", "positive"))

    total = sum(COMPONENT_WEIGHTS[k] * v for k, v in components.items())
    score = int(round(100 * total))

    order = {"negative": 0, "positive": 1, "neutral": 2}
    reasons.sort(key=lambda r: order[r.impact])

    return TrustScoreResult(
        score=score,
        tier=tier_for_score(score),
        reasons=reasons,
        components={k: round(v, 4) for k, v in components.items()},
        credit_score=cs,
        credit_band=signal.credit_band,
        driving_record_band=signal.driving_record_band,
        source=signal.source,
        as_of=signal.ingested_at,
    )


def fraud_signals(signal: Optional[CustomerProfileSignal]) -> list[tuple[str, str]]:
    """Soft fraud signals derived from profile data, as (weight_key, message)."""
    if signal is None:
        return []
    out: list[tuple[str, str]] = []
    if (
        signal.credit_score is not None
        and signal.credit_score < FINANCIAL_STRESS_CREDIT_MAX
        and (signal.loan_defaults_12m or 0) >= 1
    ):
        out.append((
            "financial_stress",
            f"Financial stress indicators (credit score {signal.credit_score}, "
            f"{signal.loan_defaults_12m} recent loan default(s))",
        ))
    if (signal.other_insurer_claims_3y or 0) >= CROSS_INSURER_CLAIMS_MIN:
        out.append((
            "cross_insurer_claims",
            f"{signal.other_insurer_claims_3y} claims filed with other insurers in the last 3 years",
        ))
    return out


class CustomerTrustService:
    def for_customer(self, db: Session, customer: Customer, policy: Optional[Policy] = None) -> TrustScoreResult:
        signal = (
            db.query(CustomerProfileSignal).filter(CustomerProfileSignal.customer_id == customer.id).first()
        )
        profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer.id).first()
        return compute_trust_score(
            signal,
            kyc_verified=is_kyc_verified(profile),
            ncb_pct=policy.no_claim_bonus_pct if policy else None,
        )

    def for_customer_id(self, db: Session, customer_id: int, policy: Optional[Policy] = None) -> TrustScoreResult:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer is None:
            return compute_trust_score(None)
        return self.for_customer(db, customer, policy)


customer_trust_service = CustomerTrustService()
