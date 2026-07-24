from datetime import datetime, timedelta
from pathlib import Path

from dependencies import get_password_hash
from models.audit import ClaimDecision, HumanReview
from models.claim import Claim, ClaimDocument, ClaimStatus, DocumentType
from models.customer import Customer
from models.policy import Policy, PolicyStatus
from models.policy_agent import PolicyAgent
from services.expert_queue_service import assign_least_loaded_expert


def _seed_claim(db_session, *, agent_id: int | None = None, agent_name: str | None = None, status=ClaimStatus.PENDING_REVIEW):
    customer = Customer(
        email="agent-api@test.com",
        full_name="Agent API Customer",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="POL-AGENT-API",
        customer_id=customer.id,
        policy_type="Auto",
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
        claim_number="CLM-AGENT-API",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="Test incident",
        incident_datetime=datetime.utcnow(),
        location="Austin",
        claim_amount=10000,
        status=status,
        assigned_agent=agent_name,
        assigned_agent_id=agent_id,
        assigned_at=datetime.utcnow() if agent_id else None,
    )
    db_session.add(claim)
    db_session.commit()
    return claim, customer


def _agent_headers(client, db_session, email="assigned-agent@test.com"):
    agent = PolicyAgent(
        email=email,
        full_name="Assigned Agent",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)

    tokens = client.post("/agent/auth/verify-otp", json={"email": email, "otp": "112233"})
    return {"Authorization": f"Bearer {tokens.json()['access_token']}"}, agent


def test_agent_sees_only_assigned_claims(client, db_session):
    headers, agent = _agent_headers(client, db_session)
    assigned, _ = _seed_claim(db_session, agent_id=agent.id, agent_name=agent.full_name)

    other_customer = Customer(
        email="other@test.com",
        full_name="Other",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(other_customer)
    db_session.commit()
    other_policy = Policy(
        policy_number="POL-OTHER",
        customer_id=other_customer.id,
        policy_type="Health",
        status=PolicyStatus.ACTIVE,
        coverage_limit=10000,
        deductible=100,
        co_pay_pct=0,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=10),
        expiry_date=datetime.utcnow() + timedelta(days=355),
    )
    db_session.add(other_policy)
    db_session.commit()
    unassigned = Claim(
        claim_number="CLM-UNASSIGNED",
        customer_id=other_customer.id,
        policy_id=other_policy.id,
        incident_description="Other",
        incident_datetime=datetime.utcnow(),
        location="Dallas",
        claim_amount=5000,
        status=ClaimStatus.PENDING_REVIEW,
    )
    db_session.add(unassigned)
    db_session.commit()

    response = client.get("/api/agent/claims", headers=headers)
    assert response.status_code == 200
    ids = [c["id"] for c in response.json()]
    assert assigned.id in ids
    assert unassigned.id not in ids


def test_agent_cannot_review_unassigned_claim(client, db_session):
    headers, _agent = _agent_headers(client, db_session)
    claim, _ = _seed_claim(db_session)

    response = client.post(
        f"/api/agent/claims/{claim.id}/review",
        headers=headers,
        json={"action": "SUBMISSION_READY", "reviewer_notes": "Looks good"},
    )
    assert response.status_code == 404


def test_agent_review_updates_claim_status(client, db_session):
    headers, agent = _agent_headers(client, db_session, email="reviewer@test.com")
    claim, _ = _seed_claim(db_session, agent_id=agent.id, agent_name=agent.full_name)

    response = client.post(
        f"/api/agent/claims/{claim.id}/review",
        headers=headers,
        json={"action": "SUBMISSION_READY", "reviewer_notes": "Approved after review"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUBMISSION_READY"

    detail = client.get(f"/api/agent/claims/{claim.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "SUBMISSION_READY"


def test_list_available_agents(client, db_session):
    agent = PolicyAgent(
        email="available@test.com",
        full_name="Available Agent",
        hashed_password=get_password_hash("pass"),
        is_active=True,
    )
    db_session.add(agent)
    db_session.commit()

    response = client.get("/api/agents/available")
    assert response.status_code == 200
    emails = [a["email"] for a in response.json()]
    assert "available@test.com" in emails


def test_auto_assign_sets_assigned_agent_id(db_session):
    expert = PolicyAgent(
        email="expert-auto@test.com",
        full_name="Auto Expert",
        hashed_password=get_password_hash("pass"),
        is_active=True,
    )
    db_session.add(expert)
    db_session.commit()

    claim, _ = _seed_claim(db_session, status=ClaimStatus.ANALYSIS_COMPLETE)
    assigned = assign_least_loaded_expert(db_session, claim)

    assert assigned is not None
    assert assigned.id == expert.id
    db_session.refresh(claim)
    assert claim.assigned_agent_id == expert.id
    assert claim.assigned_agent == expert.full_name
    assert claim.assigned_at is not None

    review = db_session.query(HumanReview).filter(HumanReview.claim_id == claim.id).first()
    assert review is not None
    assert review.assigned_to == expert.full_name


def test_backfill_assigns_existing_analysis_complete_claims(db_session):
    expert = PolicyAgent(
        email="backfill-expert@test.com",
        full_name="Backfill Expert",
        hashed_password=get_password_hash("pass"),
        is_active=True,
    )
    db_session.add(expert)
    db_session.commit()

    claim, _ = _seed_claim(db_session, status=ClaimStatus.ANALYSIS_COMPLETE)
    from services.expert_queue_service import backfill_unassigned_queue_claims

    count = backfill_unassigned_queue_claims(db_session)
    assert count == 1
    db_session.refresh(claim)
    assert claim.assigned_agent_id == expert.id


def test_agent_cannot_access_unassigned_claim_documents(client, db_session):
    headers, _agent = _agent_headers(client, db_session, email="doc-agent@test.com")
    claim, _ = _seed_claim(db_session)

    response = client.get(f"/api/agent/claims/{claim.id}/documents", headers=headers)
    assert response.status_code == 404


def test_agent_document_file_returns_200_for_assigned_claim(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    from config import get_settings

    get_settings.cache_clear()

    headers, agent = _agent_headers(client, db_session, email="doc-file-agent@test.com")
    claim, _ = _seed_claim(db_session, agent_id=agent.id, agent_name=agent.full_name)

    upload_file = tmp_path / "proof.pdf"
    upload_file.write_bytes(b"%PDF-1.4 test")

    doc = ClaimDocument(
        claim_id=claim.id,
        doc_type=DocumentType.PROOF,
        original_filename="proof.pdf",
        file_path=str(upload_file),
        checksum="test-checksum",
        ocr_text="sample text",
    )
    db_session.add(doc)
    db_session.commit()

    response = client.get(
        f"/api/agent/claims/{claim.id}/documents/{doc.id}/file",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_agent_audit_includes_evidence_results(client, db_session):
    headers, agent = _agent_headers(client, db_session, email="audit-agent@test.com")
    claim, _ = _seed_claim(db_session, agent_id=agent.id, agent_name=agent.full_name)
    decision = ClaimDecision(
        claim_id=claim.id,
        status=ClaimStatus.ANALYSIS_COMPLETE,
        payable_amount=4000,
        confidence_score=0.82,
        fraud_score=0.1,
        reasoning="Test reasoning",
        retrieved_clauses=[{"section_ref": "4.2", "summary": "Hospitalization covered"}],
        evidence_results=[{"filename": "bill.pdf", "confidence": 0.9, "valid": True}],
        human_review_required=True,
        approval_probability=0.82,
    )
    db_session.add(decision)
    db_session.commit()

    response = client.get(f"/api/agent/claims/{claim.id}/audit", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data.get("evidence_results", [])) == 1
    assert data.get("escalation_flags") is not None
    assert len(data.get("documents", [])) >= 0


def test_agent_policy_requirements(client, db_session):
    headers, agent = _agent_headers(client, db_session, email="policy-req-agent@test.com")
    claim, _ = _seed_claim(db_session, agent_id=agent.id, agent_name=agent.full_name)
    claim.policy_context_json = {
        "coverage_summary": "Hospitalization covered up to policy limit.",
        "exclusions": ["cosmetic"],
        "key_sections": [{"ref": "4.2", "summary": "Inpatient care"}],
    }
    decision = ClaimDecision(
        claim_id=claim.id,
        status=ClaimStatus.ANALYSIS_COMPLETE,
        payable_amount=3000,
        confidence_score=0.8,
        fraud_score=0.05,
        reasoning="Coverage applies",
        retrieved_clauses=[{"section_ref": "4.2", "summary": "Hospitalization"}],
        missing_documents=["Discharge summary"],
        human_review_required=True,
    )
    db_session.add(decision)
    db_session.commit()

    response = client.get(f"/api/agent/claims/{claim.id}/policy-requirements", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["claim_id"] == claim.claim_number
    assert "Discharge summary" in data["missing_documents"]
    assert data["coverage_summary"]


def test_agent_consult_requires_documents_for_needs_improvement(client, db_session):
    headers, agent = _agent_headers(client, db_session, email="consult-agent@test.com")
    claim, _ = _seed_claim(
        db_session,
        agent_id=agent.id,
        agent_name=agent.full_name,
        status=ClaimStatus.PENDING_REVIEW,
    )

    missing = client.post(
        f"/api/agent/claims/{claim.id}/consult",
        headers=headers,
        json={"action": "NEEDS_IMPROVEMENT", "reviewer_notes": "Need more docs"},
    )
    assert missing.status_code == 400

    ok = client.post(
        f"/api/agent/claims/{claim.id}/consult",
        headers=headers,
        json={
            "action": "NEEDS_IMPROVEMENT",
            "reviewer_notes": "Please upload medical bill and invoice.",
            "requested_documents": ["MEDICAL", "INVOICE"],
        },
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "REQUEST_MORE_INFO"

    customer = db_session.query(Customer).filter(Customer.email == "agent-api@test.com").first()
    login = client.post("/auth/verify-otp", json={"email": customer.email, "otp": "112233"})
    cust_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    status = client.get(f"/api/claims/{claim.id}/status", headers=cust_headers)
    assert status.status_code == 200
    requested = status.json()["expert_review"]["requested_documents"]
    assert len(requested) == 2
    assert requested[0]["document_type"] in {"MEDICAL", "INVOICE"}
