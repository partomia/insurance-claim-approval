from datetime import datetime, timedelta

from dependencies import get_password_hash
from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.insurer_user import InsurerUser
from models.policy import Policy, PolicyStatus


def test_insurer_login_and_otp(client, db_session):
    insurer = InsurerUser(
        email="insurer@test.com",
        full_name="Insurer User",
        hashed_password=get_password_hash("password123"),
        department="Claims Adjuster",
    )
    db_session.add(insurer)
    db_session.commit()

    login = client.post("/insurer/auth/login", json={"email": "insurer@test.com", "password": "password123"})
    assert login.status_code == 200

    verify = client.post("/insurer/auth/verify-otp", json={"email": "insurer@test.com", "otp": "112233"})
    assert verify.status_code == 200
    data = verify.json()
    assert "access_token" in data
    assert "refresh_token" in data


def test_insurer_list_and_approve_claim(client, db_session):
    insurer = InsurerUser(
        email="insurer@test.com",
        full_name="Insurer User",
        hashed_password=get_password_hash("password123"),
    )
    customer = Customer(
        email="customer-ins@test.com",
        full_name="Customer Ins",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add_all([insurer, customer])
    db_session.commit()

    policy = Policy(
        policy_number="POL-INS",
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
        claim_number="CLM-INS-1",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="Hospital stay",
        incident_datetime=datetime.utcnow(),
        location="Mumbai",
        claim_amount=5440,
        status=ClaimStatus.SUBMITTED_TO_INSURER,
        assigned_agent="Ananya Desai",
    )
    db_session.add(claim)
    db_session.commit()

    verify = client.post("/insurer/auth/verify-otp", json={"email": "insurer@test.com", "otp": "112233"})
    headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}

    listed = client.get("/api/insurer/claims", headers=headers)
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["claim_id"] == "CLM-INS-1"

    decision = client.post(
        f"/api/insurer/claims/{claim.id}/decision",
        headers=headers,
        json={"action": "APPROVED", "notes": "Approved after review", "payable_amount": 5000},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "APPROVED"

    db_session.refresh(claim)
    assert claim.status == ClaimStatus.APPROVED


def test_insurer_reject_non_submitted_claim(client, db_session):
    insurer = InsurerUser(
        email="insurer@test.com",
        full_name="Insurer User",
        hashed_password=get_password_hash("password123"),
    )
    customer = Customer(
        email="customer-ins2@test.com",
        full_name="Customer Ins 2",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add_all([insurer, customer])
    db_session.commit()

    policy = Policy(
        policy_number="POL-INS2",
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
        claim_number="CLM-INS-2",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="Draft claim",
        incident_datetime=datetime.utcnow(),
        location="Delhi",
        claim_amount=1000,
        status=ClaimStatus.SUBMISSION_READY,
    )
    db_session.add(claim)
    db_session.commit()

    verify = client.post("/insurer/auth/verify-otp", json={"email": "insurer@test.com", "otp": "112233"})
    headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}

    decision = client.post(
        f"/api/insurer/claims/{claim.id}/decision",
        headers=headers,
        json={"action": "REJECTED", "notes": "Not submitted yet"},
    )
    assert decision.status_code == 400
