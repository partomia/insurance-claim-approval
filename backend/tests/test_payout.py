from datetime import datetime, timedelta

from models.policy import Policy, PolicyStatus


def test_payout_with_deductible_and_copay():
    from services.payout_calculation import PayoutCalculationService

    policy = Policy(
        policy_number="P1",
        customer_id=1,
        policy_type="Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=500000,
        deductible=500,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=365),
        expiry_date=datetime.utcnow() + timedelta(days=365),
        depreciation_rate=5,
    )
    result = PayoutCalculationService().calculate(policy, 10000)
    assert result.deductible_applied == 500
    assert result.payable_amount > 0
    assert result.payable_amount < 10000


def test_payout_capped_at_coverage_limit():
    from services.payout_calculation import PayoutCalculationService

    policy = Policy(
        policy_number="P2",
        customer_id=1,
        policy_type="Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=5000,
        deductible=0,
        co_pay_pct=0,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=365),
        expiry_date=datetime.utcnow() + timedelta(days=365),
        depreciation_rate=0,
    )
    result = PayoutCalculationService().calculate(policy, 50000)
    assert result.payable_amount == 5000
