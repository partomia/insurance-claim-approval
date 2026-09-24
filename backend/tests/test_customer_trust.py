import uuid

from config import get_settings
from models.claim import ClaimStatus
from models.customer import Customer
from models.customer_profile_signal import CustomerProfileSignal
from services.customer_trust_service import (
    TIER_PREFERRED,
    TIER_STANDARD,
    TIER_UNSCORED,
    TIER_WATCH,
    amount_multiplier_for_tier,
    compute_trust_score,
    customer_trust_service,
    fraud_signals,
)
from services.decision_engine import DecisionEngine, DecisionInput
from services.fraud_detection import FraudDetectionService


def _signal(**overrides) -> CustomerProfileSignal:
    base = dict(
        credit_score=720,
        credit_band="GOOD",
        loan_defaults_12m=0,
        active_vehicle_loan=False,
        driver_age=40,
        years_licensed=6,
        traffic_violations_3y=0,
        dui_history=False,
        driving_record_band="CLEAN",
        address_changed_90d=False,
        years_with_insurer=2.0,
        policies_held=1,
        other_insurer_claims_3y=0,
        source="GOLD_PIPELINE",
    )
    base.update(overrides)
    return CustomerProfileSignal(**base)


STRONG = dict(credit_score=790, years_licensed=15, years_with_insurer=6.0, policies_held=2)
STRESSED = dict(
    credit_score=540, loan_defaults_12m=2, traffic_violations_3y=3, years_licensed=1,
    years_with_insurer=0.2, address_changed_90d=True, other_insurer_claims_3y=4,
)


def test_no_profile_is_unscored_and_neutral():
    result = compute_trust_score(None)
    assert result.score is None
    assert result.tier == TIER_UNSCORED
    assert amount_multiplier_for_tier(result.tier) == 1.0


def test_tiers_span_preferred_standard_watch():
    assert compute_trust_score(_signal(**STRONG), kyc_verified=True, ncb_pct=35).tier == TIER_PREFERRED
    assert compute_trust_score(_signal(credit_score=660, years_licensed=3, traffic_violations_3y=1)).tier == TIER_STANDARD
    assert compute_trust_score(_signal(**STRESSED)).tier == TIER_WATCH


def test_reasons_explain_the_score():
    strong = compute_trust_score(_signal(**STRONG), kyc_verified=True, ncb_pct=35)
    codes = {r.code for r in strong.reasons}
    assert {"credit_excellent", "clean_record", "long_tenure", "no_claim_bonus", "kyc_verified"} <= codes
    assert all(r.impact != "negative" for r in strong.reasons)

    weak = compute_trust_score(_signal(**STRESSED))
    weak_codes = {r.code for r in weak.reasons}
    assert {"credit_low", "loan_defaults", "traffic_violations", "new_driver", "address_changed",
            "claims_elsewhere"} <= weak_codes
    assert weak.reasons[0].impact == "negative"


def test_no_credit_hit_is_neutral_not_penalised():
    no_hit = compute_trust_score(_signal(credit_score=None, credit_band="NO_HIT"))
    low = compute_trust_score(_signal(credit_score=620))
    assert no_hit.components["credit"] == 0.5
    assert no_hit.score > low.score


def test_driver_age_does_not_affect_score():
    young = compute_trust_score(_signal(driver_age=22))
    old = compute_trust_score(_signal(driver_age=66))
    assert young.score == old.score


def test_profile_fraud_signals_are_soft():
    keys = [k for k, _ in fraud_signals(_signal(**STRESSED))]
    assert keys == ["financial_stress", "cross_insurer_claims"]
    assert fraud_signals(_signal(**STRONG)) == []
    assert fraud_signals(None) == []

    stacked = sum(FraudDetectionService.SIGNAL_WEIGHTS[k] for k in keys)
    assert stacked < get_settings().fraud_review_threshold


def _decide(amount: float, tier: str) -> DecisionInput:
    base = get_settings().human_review_amount_threshold
    return DecisionInput(
        claim_amount=amount,
        human_review_amount_threshold=base * amount_multiplier_for_tier(tier),
    )


def test_preferred_tier_raises_auto_approval_limit():
    base = get_settings().human_review_amount_threshold
    amount = base * 1.2
    assert DecisionEngine().decide(_decide(amount, TIER_UNSCORED)).status == ClaimStatus.PENDING_REVIEW
    assert DecisionEngine().decide(_decide(amount, TIER_STANDARD)).status == ClaimStatus.PENDING_REVIEW
    assert DecisionEngine().decide(_decide(amount, TIER_PREFERRED)).status == ClaimStatus.ANALYSIS_COMPLETE


def test_watch_tier_lowers_limit_but_never_rejects():
    base = get_settings().human_review_amount_threshold
    result = DecisionEngine().decide(_decide(base * 0.8, TIER_WATCH))
    assert result.status == ClaimStatus.PENDING_REVIEW
    assert "trust" not in result.reasoning.lower()

    small = DecisionEngine().decide(_decide(base * 0.1, TIER_WATCH))
    assert small.status == ClaimStatus.ANALYSIS_COMPLETE


def test_service_reads_profile_from_db(db_session):
    customer = Customer(
        email=f"trust-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Trust Test",
        hashed_password="x",
    )
    db_session.add(customer)
    db_session.flush()

    assert customer_trust_service.for_customer(db_session, customer).tier == TIER_UNSCORED

    signal = _signal(**STRONG)
    signal.customer_id = customer.id
    db_session.add(signal)
    db_session.flush()

    result = customer_trust_service.for_customer(db_session, customer)
    assert result.tier == TIER_PREFERRED
    assert result.to_dict()["credit_score"] == 790
