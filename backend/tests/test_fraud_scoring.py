from datetime import datetime, timedelta

from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.policy import Policy, PolicyStatus


def test_fraud_blacklist(db_session):
    from services.fraud_detection import FraudDetectionService

    customer = Customer(
        email="fraud@test.com",
        full_name="Fraud User",
        hashed_password="x",
        blacklist_flag=True,
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="FP1",
        customer_id=customer.id,
        policy_type="Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=100000,
        deductible=500,
        co_pay_pct=0,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=365),
        expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    db_session.add(policy)
    db_session.commit()

    claim = Claim(
        claim_number="CLMFRAUD1",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="accident",
        incident_datetime=datetime.utcnow(),
        location="NYC",
        claim_amount=5000,
        status=ClaimStatus.PENDING,
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)
    claim.policy = policy

    result = FraudDetectionService().detect(db_session, claim)
    assert result.fraud_score >= 0.35
    assert result.blacklist_hit


def test_fraud_duplicate_claim(db_session):
    from services.fraud_detection import FraudDetectionService

    customer = Customer(email="dup@test.com", full_name="Dup", hashed_password="x")
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="DP1",
        customer_id=customer.id,
        policy_type="Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=100000,
        deductible=500,
        co_pay_pct=0,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=365),
        expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    db_session.add(policy)
    db_session.commit()

    claim1 = Claim(
        claim_number="CLMDUP1",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="same incident",
        incident_datetime=datetime.utcnow(),
        location="LA",
        claim_amount=1000,
        status=ClaimStatus.APPROVED,
    )
    claim2 = Claim(
        claim_number="CLMDUP2",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="same incident",
        incident_datetime=datetime.utcnow(),
        location="LA",
        claim_amount=1000,
        status=ClaimStatus.PENDING,
    )
    db_session.add_all([claim1, claim2])
    db_session.commit()
    claim2.policy = policy

    result = FraudDetectionService().detect(db_session, claim2)
    assert result.fraud_score > 0
