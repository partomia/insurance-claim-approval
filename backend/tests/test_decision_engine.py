from datetime import datetime, timedelta
from unittest.mock import patch

from models.claim import Claim, ClaimStatus
from models.policy import Policy, PolicyStatus
from services.decision_engine import DecisionEngine, DecisionInput
from services.escalation_service import EscalationService
from services.llm_payout_service import LLMPayoutService


def test_reject_expired_policy():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput(policy_expired=True))
    assert result.status == ClaimStatus.REJECTED


def test_reject_unpaid_premium():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput(premium_unpaid=True))
    assert result.status == ClaimStatus.REJECTED


def test_reject_excluded_incident():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput(incident_excluded=True))
    assert result.status == ClaimStatus.REJECTED


def test_request_more_info():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput(evidence_missing=True))
    assert result.status == ClaimStatus.REQUEST_MORE_INFO


def test_pending_review_with_escalation_flags():
    engine = DecisionEngine()
    result = engine.decide(
        DecisionInput(
            escalation_flags=["high_fraud_score"],
            escalation_messages=["Fraud risk (45%) exceeds review threshold (40%)"],
        )
    )
    assert result.status == ClaimStatus.PENDING_REVIEW
    assert result.human_review_required


def test_pending_review_high_fraud():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput(fraud_score=0.45))
    assert result.status == ClaimStatus.PENDING_REVIEW
    assert result.human_review_required


def test_pending_review_low_evidence():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput(evidence_confidence_score=0.50))
    assert result.status == ClaimStatus.PENDING_REVIEW


def test_pending_review_large_amount():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput(claim_amount=600_000))
    assert result.status == ClaimStatus.PENDING_REVIEW


def test_pending_review_low_confidence():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput(confidence_score=0.50))
    assert result.status == ClaimStatus.PENDING_REVIEW


def test_approve_default():
    engine = DecisionEngine()
    result = engine.decide(DecisionInput())
    assert result.status == ClaimStatus.APPROVED


def test_escalation_high_fraud():
    claim = _make_claim()
    result = EscalationService().evaluate(claim, {"fraud_score": 0.45})
    assert "high_fraud_score" in result.flags


def test_escalation_low_evidence():
    claim = _make_claim()
    result = EscalationService().evaluate(claim, {"evidence_confidence_score": 0.50})
    assert "low_evidence_confidence" in result.flags


def test_escalation_early_claim():
    claim = _make_claim(days_since_effective=5, claim_amount=10000)
    result = EscalationService().evaluate(claim, {})
    assert "early_claim_high_amount" in result.flags


def _make_claim(days_since_effective: int = 100, claim_amount: float = 5000) -> Claim:
    now = datetime.utcnow()
    policy = Policy(
        policy_number="POL-TEST",
        customer_id=1,
        policy_type="Health",
        status=PolicyStatus.ACTIVE,
        coverage_limit=50000,
        deductible=500,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=now - timedelta(days=days_since_effective),
        expiry_date=now + timedelta(days=265),
        depreciation_rate=0,
    )
    policy.id = 1
    claim = Claim(
        claim_number="CLM-TEST",
        customer_id=1,
        policy_id=1,
        incident_description="Hospital stay",
        incident_datetime=now,
        location="Austin, TX",
        claim_amount=claim_amount,
        status=ClaimStatus.PROCESSING,
    )
    claim.policy = policy
    claim.policy_context_json = {"key_sections": [{"ref": "Section 4.2", "summary": "Hospitalization"}]}
    return claim


def test_llm_payout_gross_copay():
    claim = _make_claim(claim_amount=18500)
    policy = claim.policy

    mock_params = {
        "apply_deductible": False,
        "deductible_amount": 0,
        "co_pay_pct": 10,
        "co_pay_basis": "gross",
        "apply_depreciation": False,
        "depreciation_pct": 0,
        "coverage_cap": 50000,
        "formula_steps": ["10% co-pay on gross"],
        "rationale": "Health policy co-pay on gross per schedule",
    }

    with patch("services.llm_payout_service.llm_service.extract_payout_parameters", return_value=mock_params):
        result = LLMPayoutService().calculate(claim, policy, [])

    assert result.payable_amount == 16650.0
    assert result.breakdown["co_pay_amount"] == 1850.0
