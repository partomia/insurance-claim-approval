from datetime import datetime, timedelta

from models.customer import Customer
from models.policy import Policy, PolicyStatus, PremiumPayment, PremiumPaymentStatus
from dependencies import get_password_hash


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_policy_summary_requires_auth(client, db_session):
    customer = Customer(
        email="api@test.com",
        full_name="API User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="POL-API-1",
        customer_id=customer.id,
        policy_type="Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=100000,
        deductible=500,
        co_pay_pct=10,
        exclusions=["racing"],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=100),
        expiry_date=datetime.utcnow() + timedelta(days=265),
    )
    db_session.add(policy)
    db_session.commit()

    response = client.get("/api/policies/POL-API-1/summary")
    assert response.status_code == 401

    login = client.post(
        "/auth/verify-otp",
        json={"email": "api@test.com", "otp": "112233"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = client.get(
        "/api/policies/POL-API-1/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["policy_number"] == "POL-API-1"
    assert data["coverage_limit"] == 100000


def test_policies_me_empty_without_auto_create(client, db_session):
    from models.customer import Customer
    from dependencies import get_password_hash

    customer = Customer(
        email="empty@test.com",
        full_name="Empty User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    login = client.post("/auth/verify-otp", json={"email": "empty@test.com", "otp": "112233"})
    token = login.json()["access_token"]

    response = client.get("/api/policies/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_draft_without_policy_then_attach(client, db_session):
    from models.customer import Customer
    from dependencies import get_password_hash
    from models.policy import Policy, PolicyStatus
    from datetime import datetime, timedelta

    customer = Customer(
        email="draft@test.com",
        full_name="Draft User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="POL-DRAFT-1",
        customer_id=customer.id,
        policy_type="Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=100000,
        deductible=500,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=100),
        expiry_date=datetime.utcnow() + timedelta(days=265),
    )
    db_session.add(policy)
    db_session.commit()

    login = client.post("/auth/verify-otp", json={"email": "draft@test.com", "otp": "112233"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    draft = client.post(
        "/api/claims/draft",
        headers=headers,
        json={
            "incident_description": "Rear-end collision",
            "incident_datetime": datetime.utcnow().isoformat(),
            "location": "Austin, TX",
            "claim_amount": 5000,
        },
    )
    assert draft.status_code == 201
    data = draft.json()
    assert data["policy_number"] is None
    claim_id = data["id"]

    patched = client.patch(
        f"/api/claims/{claim_id}/draft",
        headers=headers,
        json={"policy_number": "POL-DRAFT-1"},
    )
    assert patched.status_code == 200
    assert patched.json()["policy_number"] == "POL-DRAFT-1"


def test_create_policy_via_api(client, db_session):
    from models.customer import Customer
    from dependencies import get_password_hash

    customer = Customer(
        email="createpol@test.com",
        full_name="Policy User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    login = client.post("/auth/verify-otp", json={"email": "createpol@test.com", "otp": "112233"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/policies",
        headers=headers,
        json={
            "policy_type": "Health",
            "coverage_limit": 250000,
            "deductible": 1000,
            "co_pay_pct": 20,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["policy_type"] == "Health"
    assert data["coverage_limit"] == 250000
    assert data["document_count"] == 0
    assert data["policy_number"].startswith("POL-")


def test_create_policy_from_document_upload(client, db_session):
    from models.customer import Customer
    from dependencies import get_password_hash

    customer = Customer(
        email="uploaddoc@test.com",
        full_name="Upload User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    login = client.post("/auth/verify-otp", json={"email": "uploaddoc@test.com", "otp": "112233"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    policy_text = (
        "AUTO INSURANCE POLICY SCHEDULE\n"
        "Policy Number: POL-DOC-123\n"
        "Policy Type: Auto\n"
        "Coverage Limit: $300,000\n"
        "Deductible: $750\n"
        "Co-pay: 15%\n"
        "Exclusions: racing, intentional damage\n"
    )
    response = client.post(
        "/api/policies/from-document",
        headers=headers,
        files={"file": ("schedule.txt", policy_text.encode(), "text/plain")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["policy_number"].startswith("POL-")
    assert data["document_count"] == 1
    assert data["coverage_limit"] > 0


def test_delete_policy(client, db_session):
    from models.customer import Customer
    from dependencies import get_password_hash
    from models.policy import Policy, PolicyStatus
    from datetime import datetime, timedelta

    customer = Customer(
        email="deletepol@test.com",
        full_name="Delete User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="POL-DELETE-1",
        customer_id=customer.id,
        policy_type="Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=100000,
        deductible=500,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=100),
        expiry_date=datetime.utcnow() + timedelta(days=265),
    )
    db_session.add(policy)
    db_session.commit()

    login = client.post("/auth/verify-otp", json={"email": "deletepol@test.com", "otp": "112233"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.delete("/api/policies/POL-DELETE-1", headers=headers)
    assert response.status_code == 200

    listed = client.get("/api/policies/me", headers=headers)
    assert listed.json() == []
