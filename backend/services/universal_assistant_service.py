import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.assistant_memory import AssistantOwnerType, AssistantPersona
from models.claim import Claim
from models.customer import Customer
from models.platform import CustomerProfile
from models.policy import Policy
from services.assistant_memory_service import assistant_memory_service
from services.assistant_response_service import (
    AssistantIntent,
    build_llm_reply,
    build_template_reply,
    detect_intent,
    normalize_structured_reply,
    slim_rag_lines,
    uses_template_reply,
)
from services.claim_assistant_service import ClaimAssistantService
from services.rag_service import rag_service


class UniversalAssistantService:
    def __init__(self) -> None:
        self._claim_assistant = ClaimAssistantService()
        self._memory = assistant_memory_service

    def _customer_session(self, db: Session, customer: Customer):
        return self._memory.get_or_create_session(
            db,
            owner_type=AssistantOwnerType.CUSTOMER,
            owner_id=customer.id,
            persona=AssistantPersona.CUSTOMER_COPILOT,
        )

    def list_threads(self, db: Session, customer: Customer) -> list[dict[str, Any]]:
        session = self._customer_session(db, customer)
        return [self._memory.thread_to_dict(t) for t in self._memory.list_threads(db, session)]

    def create_thread(self, db: Session, customer: Customer, *, title: str | None = None) -> dict[str, Any]:
        session = self._customer_session(db, customer)
        thread = self._memory.create_general_thread(db, session, title=title)
        return self._memory.thread_to_dict(thread)

    def get_history(
        self,
        db: Session,
        customer: Customer,
        *,
        thread_id: Optional[int] = None,
        claim_id: Optional[int] = None,
    ) -> list[dict]:
        session = self._customer_session(db, customer)
        try:
            thread = self._memory.resolve_thread(db, session, thread_id=thread_id, claim_id=claim_id)
        except ValueError:
            return []
        return self._memory.get_thread_history(db, thread)

    def _system_prompt(self) -> str:
        return (
            "You are ClaimCopilot, a friendly insurance assistant for policyholders. "
            "The user is the customer filing or tracking a claim — NOT an internal expert. "
            "Use plain language, reassurance where appropriate, and practical next steps. "
            "When ACTIVE CLAIM includes CUSTOMER-FACING AI ANALYSIS, those figures match the Track Claim page — never contradict them. "
            "Policy RAG excerpts are supplementary only. Never approve or reject claims."
        )

    def _build_account_context(self, db: Session, customer: Customer) -> str:
        parts: list[str] = [f"Customer: {customer.full_name}"]

        profile = (
            db.query(CustomerProfile)
            .filter(CustomerProfile.customer_id == customer.id)
            .first()
        )
        if profile:
            parts.append(f"KYC: {profile.kyc_status.value}")

        policies = (
            db.query(Policy)
            .filter(Policy.customer_id == customer.id)
            .order_by(Policy.id.desc())
            .limit(3)
            .all()
        )
        if policies:
            parts.append("Policies:")
            for policy in policies:
                parts.append(
                    f"- {policy.policy_number} ({policy.policy_type}), "
                    f"limit ${policy.coverage_limit:,.0f}"
                )
        else:
            parts.append("Policies: none")

        return "\n".join(parts)

    def _retrieve_policy_clauses(
        self,
        db: Session,
        customer_id: int,
        query: str,
        policy_number: Optional[str] = None,
        *,
        max_clauses: int = 2,
        max_chars: int = 120,
    ) -> str:
        policy_query = db.query(Policy).filter(Policy.customer_id == customer_id)
        if policy_number:
            policy_query = policy_query.filter(Policy.policy_number == policy_number)
        policies = policy_query.all()
        if not policies:
            return "No indexed policy documents available."

        allowed_ids = {p.id for p in policies}
        clauses = rag_service.retrieve(query, top_k=6)
        filtered = [c for c in clauses if c.policy_id in allowed_ids]
        filtered.sort(key=lambda c: c.similarity_score, reverse=True)
        filtered = filtered[:max_clauses]

        if not filtered:
            return "No matching policy clauses found."

        policy_by_id = {p.id: p for p in policies}
        lines: list[str] = []
        for clause in filtered:
            policy = policy_by_id.get(clause.policy_id)
            policy_label = policy.policy_number if policy else str(clause.policy_id)
            text = clause.clause_text[:max_chars]
            lines.append(f"- [{policy_label} | {clause.section_ref}] {text}")

        return slim_rag_lines(lines, max_clauses=max_clauses, max_chars=max_chars + 40)

    def _build_claim_context(
        self,
        db: Session,
        customer_id: int,
        claim_id: int,
        intent: AssistantIntent,
    ) -> tuple[Optional[Claim], str]:
        claim = self._claim_assistant.load_claim(db, claim_id, customer_id)
        if not claim:
            return None, ""
        return claim, self._claim_assistant._build_context(claim, intent)

    def chat(
        self,
        db: Session,
        customer: Customer,
        user_message: str,
        *,
        thread_id: Optional[int] = None,
        claim_id: Optional[int] = None,
        policy_number: Optional[str] = None,
        page_route: Optional[str] = None,
    ) -> str:
        session = self._customer_session(db, customer)
        try:
            thread = self._memory.resolve_thread(db, session, thread_id=thread_id, claim_id=claim_id)
        except ValueError:
            return "**In short:** Conversation not found.\n\n**Do this next:** Start a new chat."

        intent = detect_intent(user_message)
        claim: Optional[Claim] = None
        active_claim_id = claim_id or thread.claim_id

        if active_claim_id:
            claim = self._claim_assistant.load_claim(db, active_claim_id, customer.id)

        if uses_template_reply(intent, claim):
            assert claim is not None
            reply = build_template_reply(claim, intent)
            self._persist_exchange(
                db, session, thread, customer, user_message, reply,
                active_claim_id, policy_number, page_route,
            )
            return reply

        summary_text, recent_messages = self._memory.load_context_window(db, thread)
        ltm = self._memory.format_long_term_memory(session)

        account_ctx = self._build_account_context(db, customer)
        claim_ctx = ""
        if active_claim_id:
            _, claim_ctx = self._build_claim_context(db, customer.id, active_claim_id, intent)

        rag_query = user_message
        if claim:
            rag_query = f"{claim.incident_description[:120]} {user_message}"

        rag_ctx = ""
        if intent in (AssistantIntent.COVERAGE, AssistantIntent.GENERAL):
            rag_ctx = self._retrieve_policy_clauses(
                db, customer.id, rag_query, policy_number
            )

        context_parts = []
        if ltm:
            context_parts.append(ltm)
        context_parts.append(f"ACCOUNT:\n{account_ctx}")
        if claim_ctx:
            context_parts.append(f"ACTIVE CLAIM:\n{claim_ctx}")
        if rag_ctx:
            context_parts.append(f"POLICY RAG (supplementary):\n{rag_ctx}")
        if page_route:
            context_parts.append(f"Page: {page_route}")
        if summary_text:
            context_parts.append(f"THREAD SUMMARY:\n{summary_text}")

        history_text = self._memory.format_history_text(recent_messages)
        reply = build_llm_reply(
            self._system_prompt(),
            f"""{chr(10).join(context_parts)}

HISTORY:
{history_text}

USER: {user_message}""",
        )
        reply = normalize_structured_reply(reply)

        if not reply:
            reply = (
                "**In short:** I can help with coverage, documents, and claim prep.\n\n"
                "**Do this next:** Ask a specific question about your policy or claim."
            )

        self._persist_exchange(
            db, session, thread, customer, user_message, reply,
            active_claim_id, policy_number, page_route,
        )
        return reply

    def _persist_exchange(
        self,
        db: Session,
        session,
        thread,
        customer: Customer,
        user_message: str,
        reply: str,
        claim_id: Optional[int],
        policy_number: Optional[str],
        page_route: Optional[str],
    ) -> None:
        audit_context: dict[str, Any] = {}
        if claim_id is not None:
            audit_context["claim_id"] = claim_id
        if policy_number:
            audit_context["policy_number"] = policy_number
        if page_route:
            audit_context["page_route"] = page_route

        self._memory.persist_exchange(
            db, thread, user_message, reply,
            context_json=audit_context or None,
        )
        self._memory.maybe_compact_thread(db, thread, session)


universal_assistant_service = UniversalAssistantService()
