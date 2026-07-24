from datetime import datetime, timedelta
from unittest.mock import patch

from dependencies import get_password_hash
from models.audit import ClaimDecision
from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.policy import Policy, PolicyStatus
from models.policy_agent import PolicyAgent


def _seed_assigned_claim(db_session, agent: PolicyAgent):
    customer = Customer(
        email="copilot-customer@test.com",
        full_name="Copilot Customer",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="POL-COPILOT",
        customer_id=customer.id,
        policy_type="Health",
        status=PolicyStatus.ACTIVE,
        coverage_limit=100000,
        deductible=1000,
        co_pay_pct=10,
        exclusions=["Cosmetic surgery", "Self-inflicted injury"],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=60),
        expiry_date=datetime.utcnow() + timedelta(days=300),
    )
    db_session.add(policy)
    db_session.commit()

    claim = Claim(
        claim_number="CLM-COPILOT",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="Hospital stay for surgery",
        incident_datetime=datetime.utcnow(),
        location="Mumbai",
        claim_amount=4444,
        status=ClaimStatus.ANALYSIS_COMPLETE,
        assigned_agent_id=agent.id,
        assigned_agent=agent.full_name,
        assigned_at=datetime.utcnow(),
        policy_context_json={
            "coverage_summary": "Inpatient hospitalization covered up to sum insured with 10% co-pay.",
            "exclusions": ["Cosmetic or plastic surgery (Section 7.1)", "Self-inflicted injury (Section 7.2)"],
            "key_sections": [{"ref": "4.2", "summary": "Hospitalization and surgical procedures covered."}],
        },
    )
    db_session.add(claim)
    db_session.commit()

    decision = ClaimDecision(
        claim_id=claim.id,
        status=ClaimStatus.ANALYSIS_COMPLETE,
        payable_amount=4000,
        confidence_score=0.82,
        fraud_score=0.08,
        reasoning="Strong claim with supporting documents.",
        retrieved_clauses=[{"section_ref": "4.2", "summary": "Hospitalization"}],
        missing_documents=["Discharge summary"],
        human_review_required=True,
        approval_probability=0.82,
        coverage_estimate=4444,
        expected_settlement=4000,
        next_best_action="Confirm discharge summary with customer",
    )
    db_session.add(decision)
    db_session.commit()
    return claim


def _agent_headers(client, db_session, email="copilot-agent@test.com"):
    agent = PolicyAgent(
        email=email,
        full_name="Copilot Agent",
        hashed_password=get_password_hash("pass"),
        is_active=True,
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    tokens = client.post("/agent/auth/verify-otp", json={"email": email, "otp": "112233"})
    return {"Authorization": f"Bearer {tokens.json()['access_token']}"}, agent


@patch("services.assistant_response_service.llm_service.invoke_assistant")
def test_agent_copilot_uses_llm_for_status(mock_llm, client, db_session):
    mock_llm.return_value = (
        "**Summary:** CLM-COPILOT is at 82% AI approval with analysis complete.\n\n"
        "**Key findings:**\n- Expected settlement: $4,000\n\n"
        "**Recommended action:** Confirm discharge summary with the customer."
    )
    headers, agent = _agent_headers(client, db_session)
    claim = _seed_assigned_claim(db_session, agent)

    response = client.post(
        "/api/agent/assistant/chat",
        headers=headers,
        json={"message": "What is the claim status and approval probability?", "claim_id": claim.id},
    )
    assert response.status_code == 200
    assert mock_llm.called
    assert "**Summary:**" in response.json()["content"]


@patch("services.assistant_response_service.llm_service.invoke_assistant")
def test_agent_copilot_claim_about_uses_llm(mock_llm, client, db_session):
    mock_llm.return_value = (
        "**Summary:** Health hospitalization claim for surgery in Mumbai.\n\n"
        "**Recommended action:** Review submission and documents."
    )
    headers, agent = _agent_headers(client, db_session, email="copilot-about@test.com")
    claim = _seed_assigned_claim(db_session, agent)

    response = client.post(
        "/api/agent/assistant/chat",
        headers=headers,
        json={"message": "what is this claim about", "claim_id": claim.id},
    )
    assert response.status_code == 200
    assert mock_llm.called
    payload = mock_llm.call_args[0][1]
    assert "CLAIM:" in payload
    assert "POLICY" in payload


@patch("services.assistant_response_service.llm_service.invoke_assistant")
def test_agent_copilot_policy_question_includes_policy_context(mock_llm, client, db_session):
    mock_llm.return_value = (
        "**Summary:** POL-COPILOT is an active Health policy with $100,000 limit and 10% co-pay.\n\n"
        "**Key findings:**\n- Excludes cosmetic surgery and self-inflicted injury\n\n"
        "**Recommended action:** Walk the customer through Section 4.2 hospitalization coverage."
    )
    headers, agent = _agent_headers(client, db_session, email="copilot-policy@test.com")
    claim = _seed_assigned_claim(db_session, agent)

    response = client.post(
        "/api/agent/assistant/chat",
        headers=headers,
        json={
            "message": "tell me about policy of this user, i don't have idea about his policy",
            "claim_id": claim.id,
        },
    )
    assert response.status_code == 200
    assert mock_llm.called
    payload = mock_llm.call_args[0][1]
    assert "POL-COPILOT" in payload
    assert "Coverage limit" in payload or "coverage limit" in payload.lower()
    content = response.json()["content"]
    assert "POL-COPILOT" in content or "policy" in content.lower()
    assert "Estimated coverage for this claim is" not in content


def test_agent_copilot_rejects_unassigned_claim(client, db_session):
    headers, agent = _agent_headers(client, db_session, email="copilot-other@test.com")

    other_agent = PolicyAgent(
        email="other-expert@test.com",
        full_name="Other Expert",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(other_agent)
    db_session.commit()
    claim = _seed_assigned_claim(db_session, other_agent)

    response = client.post(
        "/api/agent/assistant/chat",
        headers=headers,
        json={"message": "Summarize this claim", "claim_id": claim.id},
    )
    assert response.status_code == 200
    assert "not in your assigned queue" in response.json()["content"].lower()


@patch("services.assistant_response_service.llm_service.invoke_assistant")
def test_agent_copilot_llm_fallback(mock_llm, client, db_session):
    mock_llm.return_value = (
        "**Summary:** Customer risk is moderate based on prior activity.\n\n"
        "**Recommended action:** Review prior claims history before consultation."
    )
    headers, agent = _agent_headers(client, db_session, email="copilot-llm@test.com")
    claim = _seed_assigned_claim(db_session, agent)

    response = client.post(
        "/api/agent/assistant/chat",
        headers=headers,
        json={"message": "Tell me about this customer's behavioral patterns over time", "claim_id": claim.id},
    )
    assert response.status_code == 200
    assert "**Summary:**" in response.json()["content"]


@patch("services.assistant_response_service.llm_service.invoke_assistant")
def test_agent_copilot_followup_policy_correction(mock_llm, client, db_session):
    mock_llm.side_effect = [
        "**Summary:** Claim coverage estimate is $4,444.\n\n**Recommended action:** Review claim.",
        "**Summary:** POL-COPILOT Health policy — $100,000 limit, 10% co-pay, excludes cosmetic surgery.\n\n**Recommended action:** Explain Section 4.2 to the customer.",
    ]
    headers, agent = _agent_headers(client, db_session, email="copilot-followup@test.com")
    claim = _seed_assigned_claim(db_session, agent)

    client.post(
        "/api/agent/assistant/chat",
        headers=headers,
        json={"message": "approval status?", "claim_id": claim.id},
    )
    response = client.post(
        "/api/agent/assistant/chat",
        headers=headers,
        json={"message": "i said policy not claim", "claim_id": claim.id},
    )
    assert response.status_code == 200
    assert mock_llm.call_count == 2
    second_payload = mock_llm.call_args_list[1][0][1]
    assert "CONVERSATION:" in second_payload
    assert "i said policy not claim" in second_payload.lower()


def test_agent_copilot_policy_fallback_when_llm_empty(client, db_session):
    headers, agent = _agent_headers(client, db_session, email="copilot-fallback@test.com")
    claim = _seed_assigned_claim(db_session, agent)

    with patch("services.assistant_response_service.llm_service.invoke_assistant", return_value=""):
        response = client.post(
            "/api/agent/assistant/chat",
            headers=headers,
            json={
                "message": "tell me about policy of this user",
                "claim_id": claim.id,
            },
        )

    assert response.status_code == 200
    content = response.json()["content"]
    assert "**Summary:**" in content
    assert "POL-COPILOT" in content
    assert "GROQ_API_KEY" not in content


def test_agent_copilot_history(client, db_session):
    headers, agent = _agent_headers(client, db_session, email="copilot-history@test.com")
    claim = _seed_assigned_claim(db_session, agent)

    with patch("services.assistant_response_service.llm_service.invoke_assistant") as mock_llm:
        mock_llm.return_value = "**Summary:** Missing discharge summary.\n\n**Recommended action:** Request it."
        client.post(
            "/api/agent/assistant/chat",
            headers=headers,
            json={"message": "What documents are still missing?", "claim_id": claim.id},
        )

    history = client.get("/api/agent/assistant/chat", headers=headers)
    assert history.status_code == 200
    messages = history.json()
    assert len(messages) >= 2
    roles = {m["role"] for m in messages}
    assert "user" in roles
    assert "assistant" in roles
