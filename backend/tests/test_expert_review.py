from datetime import datetime, timedelta

from dependencies import get_password_hash
from models.audit import AuditLog, ClaimDecision, HumanReview, HumanReviewStatus
from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.policy import Policy, PolicyStatus
from models.policy_agent import PolicyAgent
from services.expert_review_service import build_expert_review_summary


def _seed_assigned_claim_with_review(db_session):
    customer = Customer(
        email="expert-review@test.com",
        full_name="Expert Review Customer",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    agent = PolicyAgent(
        email="expert-review-agent@test.com",
        full_name="Ananya Desai",
        hashed_password=get_password_hash("pass"),
        is_active=True,
    )
    db_session.add(agent)
    db_session.commit()

    policy = Policy(
        policy_number="POL-EXPERT-REVIEW",
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
        claim_number="CLM-EXPERT-REVIEW",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="Hospital stay",
        incident_datetime=datetime.utcnow(),
        location="Mumbai",
        claim_amount=5000,
        status=ClaimStatus.REQUEST_MORE_INFO,
        assigned_agent_id=agent.id,
        assigned_agent=agent.full_name,
        assigned_at=datetime.utcnow(),
    )
    db_session.add(claim)
    db_session.commit()

    db_session.add(
        HumanReview(
            claim_id=claim.id,
            reason="Expert consultation",
            assigned_to=agent.full_name,
            status=HumanReviewStatus.IN_PROGRESS,
            reviewer_notes="Please upload your discharge summary and itemized hospital bill.",
            decision_override=ClaimStatus.REQUEST_MORE_INFO,
        )
    )
    db_session.add(
        AuditLog(
            claim_id=claim.id,
            event_type="EXPERT_CONSULTATION",
            payload={
                "action": "NEEDS_IMPROVEMENT",
                "notes": "Please upload your discharge summary and itemized hospital bill.",
                "requested_documents": ["MEDICAL", "INVOICE"],
                "expert": agent.email,
            },
            actor=agent.email,
        )
    )
    db_session.commit()
    return claim, customer


def test_expert_review_summary_from_human_review(db_session):
    claim, _ = _seed_assigned_claim_with_review(db_session)
    summary = build_expert_review_summary(db_session, claim)
    assert summary is not None
    assert "discharge summary" in summary["message"].lower()
    assert summary["action"] == "NEEDS_IMPROVEMENT"
    assert summary["expert_name"] == "Ananya Desai"
    assert len(summary["requested_documents"]) == 2
    assert summary["requested_documents"][0]["document_type"] == "MEDICAL"
    assert summary["requested_documents"][0]["fulfilled"] is False


def test_claim_status_includes_expert_review(client, db_session):
    claim, customer = _seed_assigned_claim_with_review(db_session)
    login = client.post("/auth/verify-otp", json={"email": customer.email, "otp": "112233"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get(f"/api/claims/{claim.id}/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["expert_review"] is not None
    assert "discharge summary" in data["expert_review"]["message"].lower()
    assert data["expert_review"]["action_label"] == "Documents or details needed"
    assert len(data["expert_review"]["requested_documents"]) == 2
    labels = {d["label"] for d in data["expert_review"]["requested_documents"]}
    assert "Medical bill / discharge summary" in labels
    assert "Invoice / itemized bill" in labels
