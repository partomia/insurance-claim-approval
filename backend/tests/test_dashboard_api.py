from datetime import datetime, timedelta

from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.policy import Policy, PolicyStatus, PremiumPayment, PremiumPaymentStatus
from dependencies import get_password_hash


def _login(client, db_session, email="dash@test.com"):
    customer = Customer(
        email=email,
        full_name="Dash User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="POL-DASH-1",
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

    for idx, status in enumerate(
        [
            ClaimStatus.APPROVED,
            ClaimStatus.APPROVED,
            ClaimStatus.PENDING_REVIEW,
            ClaimStatus.DRAFT,
        ]
    ):
        claim = Claim(
            claim_number=f"CLM-DASH-{idx + 1}",
            customer_id=customer.id,
            policy_id=policy.id,
            incident_description=f"Incident {idx + 1}",
            incident_datetime=datetime.utcnow() - timedelta(days=idx * 10),
            location="NY",
            claim_amount=1000 + idx * 500,
            status=status,
        )
        db_session.add(claim)
    db_session.commit()

    login = client.post("/auth/verify-otp", json={"email": email, "otp": "112233"})
    assert login.status_code == 200
    return login.json()["access_token"]


def test_dashboard_stats_requires_auth(client):
    response = client.get("/api/dashboard/stats")
    assert response.status_code == 401


def test_dashboard_stats_returns_live_counts(client, db_session):
    token = _login(client, db_session)
    response = client.get(
        "/api/dashboard/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["active_policies"] == 1
    assert data["total_claims"] == 3
    assert data["approved_claims"] == 2
    assert data["pending_claims"] == 1
    assert data["draft_claims"] == 1
    assert len(data["recent_activity"]) == 3
    assert data["recent_activity"][0]["claim_id"].startswith("CLM-DASH-")
