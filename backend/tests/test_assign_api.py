from datetime import datetime, timedelta

from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.policy import Policy, PolicyStatus
from dependencies import get_password_hash


def test_assign_claim_agent(client, db_session):
    customer = Customer(
        email="assign@test.com",
        full_name="Assign User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="POL-ASSIGN",
        customer_id=customer.id,
        policy_type="Health",
        status=PolicyStatus.ACTIVE,
        coverage_limit=50000,
        deductible=500,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=30),
        expiry_date=datetime.utcnow() + timedelta(days=335),
    )
    db_session.add(policy)
    db_session.commit()

    claim = Claim(
        claim_number="CLM-ASSIGN",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="Test",
        incident_datetime=datetime.utcnow(),
        location="Austin",
        claim_amount=10000,
        status=ClaimStatus.PENDING_REVIEW,
        escalation_flags=["high_fraud_score"],
        escalation_messages=["Fraud risk (45%) exceeds review threshold (40%)"],
    )
    db_session.add(claim)
    db_session.commit()

    login = client.post("/auth/verify-otp", json={"email": "assign@test.com", "otp": "112233"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.post(
        f"/api/claims/{claim.id}/assign",
        headers=headers,
        json={"agent_name": "Jane Policy Agent"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["assigned_agent"] == "Jane Policy Agent"
    assert data["escalation_flags"] == ["high_fraud_score"]
