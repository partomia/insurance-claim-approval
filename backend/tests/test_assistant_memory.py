"""Regressions for the assistant-memory refactor bug fixes.

Covers:
- B1: universal_assistant_service.get_history accepts a Customer (not int).
- B2: claim_assistant_service.get_history accepts (claim_id, customer_id).
- B3: llm_service.validate_evidence_document does not raise when the key is unset.
- B4: maybe_compact_thread does not re-summarize old messages every turn.
- B5: backfill_legacy_messages is idempotent and picks up new legacy rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from dependencies import get_password_hash
from models.assistant_memory import (
    AssistantMessage,
    AssistantOwnerType,
    AssistantPersona,
)
from models.chat import ChatRole, ClaimChatMessage, CustomerChatMessage, AgentChatMessage
from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.policy import Policy, PolicyStatus
from models.policy_agent import PolicyAgent


# --- shared seed helpers --------------------------------------------------


def _seed_customer(db, email="mem-user@test.com") -> Customer:
    customer = Customer(
        email=email,
        full_name="Memory User",
        hashed_password=get_password_hash("pw"),
    )
    db.add(customer)
    db.commit()
    return customer


def _seed_policy_and_claim(db, customer: Customer) -> Claim:
    policy = Policy(
        policy_number="POL-MEM",
        customer_id=customer.id,
        policy_type="Health",
        status=PolicyStatus.ACTIVE,
        coverage_limit=100000,
        deductible=1000,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=30),
        expiry_date=datetime.utcnow() + timedelta(days=300),
    )
    db.add(policy)
    db.commit()

    claim = Claim(
        claim_number="CLM-MEM",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="Test incident",
        incident_datetime=datetime.utcnow(),
        location="Mumbai",
        claim_amount=1000,
        status=ClaimStatus.PENDING,
    )
    db.add(claim)
    db.commit()
    return claim


# --- B1 regression --------------------------------------------------------


def test_universal_get_history_accepts_customer_object(db_session):
    """B1: passing an int used to crash with AttributeError inside the service."""
    from services.universal_assistant_service import universal_assistant_service

    customer = _seed_customer(db_session, "b1@test.com")
    result = universal_assistant_service.get_history(db_session, customer)
    assert result == []


# --- B2 regression --------------------------------------------------------


def test_claim_assistant_get_history_requires_customer_id(db_session):
    """B2: get_history now takes both claim_id and customer_id."""
    from services.claim_assistant_service import ClaimAssistantService

    customer = _seed_customer(db_session, "b2@test.com")
    claim = _seed_policy_and_claim(db_session, customer)
    svc = ClaimAssistantService()
    result = svc.get_history(db_session, claim.id, customer.id)
    assert result == []


# --- B3 regression --------------------------------------------------------


def test_validate_evidence_document_returns_none_without_key(monkeypatch):
    """B3: guard used `self.client`, which never existed → AttributeError.

    With no valid Groq key, the method must return None cleanly.
    """
    from services import llm_service as llm_mod

    monkeypatch.setattr(
        llm_mod.LLMService,
        "_has_valid_key",
        lambda self: False,
    )
    svc = llm_mod.LLMService()
    result = svc.validate_evidence_document("GOV_ID", "", "incident", "Health")
    assert result is None


# --- B4 regression --------------------------------------------------------


def test_maybe_compact_thread_only_folds_new_messages(db_session):
    """B4: after one compaction, a subsequent turn with no new *older* material
    must NOT call the summarizer again."""
    from services import assistant_memory_service as mod

    customer = _seed_customer(db_session, "b4@test.com")
    session = mod.assistant_memory_service.get_or_create_session(
        db_session,
        owner_type=AssistantOwnerType.CUSTOMER,
        owner_id=customer.id,
        persona=AssistantPersona.CUSTOMER_COPILOT,
    )
    thread = mod.assistant_memory_service.create_general_thread(db_session, session)

    # Seed enough messages to blow past both thresholds so compaction fires.
    base = datetime.utcnow() - timedelta(minutes=60)
    for i in range(20):
        db_session.add(
            AssistantMessage(
                thread_id=thread.id,
                role=ChatRole.USER if i % 2 == 0 else ChatRole.ASSISTANT,
                content="x" * 500,  # ensure char threshold trips
                created_at=base + timedelta(seconds=i),
            )
        )
    thread.message_count = 20
    db_session.commit()

    call_count = {"n": 0}

    def fake_summarize(system, user, **kwargs):
        call_count["n"] += 1
        return "summary of older turns"

    with patch.object(mod.llm_service, "invoke_summarize", side_effect=fake_summarize):
        mod.assistant_memory_service.maybe_compact_thread(db_session, thread, session)
        first_call_count = call_count["n"]
        assert first_call_count >= 1, "expected at least one summarize call on first compaction"

        # Second call: no new "older" messages added. Must NOT re-summarize.
        mod.assistant_memory_service.maybe_compact_thread(db_session, thread, session)
        assert call_count["n"] == first_call_count, (
            "compaction re-ran even though no new older material existed"
        )


# --- B5 regression --------------------------------------------------------


def test_backfill_is_idempotent_and_picks_up_new_agent_rows(db_session):
    """B5: second run must not double-write; new legacy rows added between
    runs must still be migrated."""
    from services import assistant_memory_service as mod

    # Seed a customer with two legacy customer-chat messages.
    customer = _seed_customer(db_session, "b5@test.com")
    base = datetime.utcnow() - timedelta(minutes=30)
    db_session.add_all(
        [
            CustomerChatMessage(
                customer_id=customer.id,
                role=ChatRole.USER,
                content="hi",
                created_at=base,
            ),
            CustomerChatMessage(
                customer_id=customer.id,
                role=ChatRole.ASSISTANT,
                content="hello",
                created_at=base + timedelta(seconds=1),
            ),
        ]
    )
    db_session.commit()

    mod.backfill_legacy_messages(db_session)
    first_count = db_session.query(AssistantMessage).count()
    assert first_count == 2

    # Add a new legacy agent-chat row after first backfill.
    agent = PolicyAgent(
        email="expert@test.com",
        full_name="Expert",
        hashed_password=get_password_hash("pw"),
    )
    db_session.add(agent)
    db_session.commit()
    db_session.add(
        AgentChatMessage(
            agent_id=agent.id,
            role=ChatRole.USER,
            content="expert question",
            created_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    # Re-run backfill: must not duplicate the customer rows, must pick up the agent row.
    mod.backfill_legacy_messages(db_session)
    second_count = db_session.query(AssistantMessage).count()
    assert second_count == 3, (
        f"expected 3 messages after re-running with new agent row, got {second_count}"
    )


# --- M1 regression: default general thread is stable ---------------------


def test_resolve_thread_returns_stable_primary_general(db_session):
    """M1: `resolve_thread(no args)` must return the oldest general thread —
    creating a second general thread must not switch the default."""
    from services import assistant_memory_service as mod

    customer = _seed_customer(db_session, "m1@test.com")
    session = mod.assistant_memory_service.get_or_create_session(
        db_session,
        owner_type=AssistantOwnerType.CUSTOMER,
        owner_id=customer.id,
        persona=AssistantPersona.CUSTOMER_COPILOT,
    )
    primary = mod.assistant_memory_service.create_general_thread(
        db_session, session, title="Primary"
    )
    # Second general thread, freshly touched — used to hijack the default.
    secondary = mod.assistant_memory_service.create_general_thread(
        db_session, session, title="Second"
    )
    secondary.updated_at = datetime.utcnow() + timedelta(minutes=5)
    db_session.commit()

    resolved = mod.assistant_memory_service.resolve_thread(db_session, session)
    assert resolved.id == primary.id, (
        f"expected primary thread {primary.id}, got {resolved.id}"
    )


# --- M2 regression: LTM upgrade + slug de-dup + eviction -----------------


def test_ltm_merge_upgrades_legacy_and_dedups_by_slug(db_session, monkeypatch):
    """M2: legacy `{key, fact}` entries are upgraded with timestamps/hits;
    duplicate keys bump `hits` instead of overwriting; capacity is honored."""
    import json

    from services import assistant_memory_service as mod
    from config import get_settings

    # Shrink cap for a deterministic eviction test.
    monkeypatch.setattr(get_settings(), "assistant_max_long_term_facts", 3)

    customer = _seed_customer(db_session, "m2@test.com")
    sess = mod.assistant_memory_service.get_or_create_session(
        db_session,
        owner_type=AssistantOwnerType.CUSTOMER,
        owner_id=customer.id,
        persona=AssistantPersona.CUSTOMER_COPILOT,
    )
    # Seed with legacy shape (no timestamps).
    sess.long_term_memory_json = json.dumps(
        [{"key": "Prefers Email", "fact": "prefers email"}]
    )
    db_session.commit()

    # Merge same key — should bump hits, not duplicate.
    mod.assistant_memory_service._merge_long_term_facts(
        db_session, sess, [{"key": "prefers email", "fact": "prefers email"}]
    )
    facts = mod.assistant_memory_service.load_long_term_memory(sess)
    assert len(facts) == 1
    assert facts[0]["hits"] == 2

    # Add 3 more distinct facts; cap=3 must evict the least-useful.
    mod.assistant_memory_service._merge_long_term_facts(
        db_session,
        sess,
        [
            {"key": "family-4", "fact": "has 4 dependents"},
            {"key": "hindi-fluent", "fact": "prefers Hindi replies"},
            {"key": "smoker", "fact": "smokes 1 pack/day"},
        ],
    )
    facts = mod.assistant_memory_service.load_long_term_memory(sess)
    assert len(facts) == 3, f"expected cap=3, got {len(facts)} facts"
    # `prefers email` had hits=2 → highest score → must survive.
    slugs = {f["key"] for f in facts}
    assert "prefers-email" in slugs


# --- M4 regression: combined summary+facts single LLM call ---------------


def test_compaction_uses_single_combined_llm_call(db_session):
    """M4: compaction should make one `invoke_summarize` call and update
    both the thread summary AND the session LTM from its JSON payload."""
    from services import assistant_memory_service as mod

    customer = _seed_customer(db_session, "m4@test.com")
    session = mod.assistant_memory_service.get_or_create_session(
        db_session,
        owner_type=AssistantOwnerType.CUSTOMER,
        owner_id=customer.id,
        persona=AssistantPersona.CUSTOMER_COPILOT,
    )
    thread = mod.assistant_memory_service.create_general_thread(db_session, session)

    base = datetime.utcnow() - timedelta(minutes=60)
    for i in range(20):
        db_session.add(
            AssistantMessage(
                thread_id=thread.id,
                role=ChatRole.USER if i % 2 == 0 else ChatRole.ASSISTANT,
                content="x" * 500,
                created_at=base + timedelta(seconds=i),
            )
        )
    thread.message_count = 20
    db_session.commit()

    combined_payload = (
        '{"summary": "user discussed policy Q&A over 10 turns", '
        '"facts": [{"key": "family-4", "fact": "has 4 dependents"}]}'
    )
    calls = {"n": 0}

    def fake(system, user, **kwargs):
        calls["n"] += 1
        return combined_payload

    with patch.object(mod.llm_service, "invoke_summarize", side_effect=fake):
        mod.assistant_memory_service.maybe_compact_thread(db_session, thread, session)

    assert calls["n"] == 1, f"expected exactly 1 LLM call, got {calls['n']}"
    db_session.refresh(thread)
    assert "policy Q&A" in (thread.summary_text or "")
    facts = mod.assistant_memory_service.load_long_term_memory(session)
    assert any(f["fact"] == "has 4 dependents" for f in facts), (
        f"LTM did not receive extracted fact: {facts}"
    )


# --- M6 regression: role-aware backfill dedup ----------------------------


def test_backfill_dedup_keeps_both_rows_at_same_timestamp(db_session):
    """M6: two legacy rows with the same microsecond timestamp but different
    roles (user + assistant of the same turn) must BOTH be migrated."""
    from services import assistant_memory_service as mod

    customer = _seed_customer(db_session, "m6@test.com")
    shared_ts = datetime.utcnow() - timedelta(minutes=10)
    db_session.add_all(
        [
            CustomerChatMessage(
                customer_id=customer.id,
                role=ChatRole.USER,
                content="hello",
                created_at=shared_ts,
            ),
            CustomerChatMessage(
                customer_id=customer.id,
                role=ChatRole.ASSISTANT,
                content="hi there",
                created_at=shared_ts,
            ),
        ]
    )
    db_session.commit()

    mod.backfill_legacy_messages(db_session)
    count = db_session.query(AssistantMessage).count()
    assert count == 2, (
        f"expected both roles migrated at same timestamp; got {count} rows"
    )
