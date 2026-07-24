import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.chat import ChatRole, CustomerChatMessage
from models.claim import Claim
from models.customer import Customer
from models.platform import CustomerProfile
from models.policy import Policy
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
    MEMORY_LIMIT = 20
    HISTORY_LIMIT = 30

    def __init__(self) -> None:
        self._claim_assistant = ClaimAssistantService()

    def get_history(self, db: Session, customer_id: int) -> list[dict]:
        messages = (
            db.query(CustomerChatMessage)
            .filter(CustomerChatMessage.customer_id == customer_id)
            .order_by(CustomerChatMessage.created_at.desc())
            .limit(self.HISTORY_LIMIT)
            .all()
        )
        messages.reverse()
        return [
            {
                "role": m.role.value,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]

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
        claim_id: Optional[int] = None,
        policy_number: Optional[str] = None,
        page_route: Optional[str] = None,
    ) -> str:
        intent = detect_intent(user_message)
        claim: Optional[Claim] = None

        if claim_id:
            claim = self._claim_assistant.load_claim(db, claim_id, customer.id)

        if uses_template_reply(intent, claim):
            assert claim is not None
            reply = build_template_reply(claim, intent)
            self._persist_exchange(db, customer, user_message, reply, claim_id, policy_number, page_route)
            return reply

        history = (
            db.query(CustomerChatMessage)
            .filter(CustomerChatMessage.customer_id == customer.id)
            .order_by(CustomerChatMessage.created_at.desc())
            .limit(self.MEMORY_LIMIT)
            .all()
        )
        history.reverse()

        account_ctx = self._build_account_context(db, customer)
        claim_ctx = ""
        if claim_id:
            _, claim_ctx = self._build_claim_context(db, customer.id, claim_id, intent)

        rag_query = user_message
        if claim:
            rag_query = f"{claim.incident_description[:120]} {user_message}"

        rag_ctx = ""
        if intent in (AssistantIntent.COVERAGE, AssistantIntent.GENERAL):
            rag_ctx = self._retrieve_policy_clauses(
                db, customer.id, rag_query, policy_number
            )

        context_parts = [f"ACCOUNT:\n{account_ctx}"]
        if claim_ctx:
            context_parts.append(f"ACTIVE CLAIM:\n{claim_ctx}")
        if rag_ctx:
            context_parts.append(f"POLICY RAG (supplementary):\n{rag_ctx}")
        if page_route:
            context_parts.append(f"Page: {page_route}")

        history_text = "\n".join(f"{m.role.value}: {m.content}" for m in history)
        reply = build_llm_reply(
            self._system_prompt(),
            f"""{chr(10).join(context_parts)}

HISTORY:
{history_text or 'No prior messages.'}

USER: {user_message}""",
        )
        reply = normalize_structured_reply(reply)

        if not reply:
            reply = (
                "**In short:** I can help with coverage, documents, and claim prep.\n\n"
                "**Do this next:** Ask a specific question about your policy or claim."
            )

        self._persist_exchange(db, customer, user_message, reply, claim_id, policy_number, page_route)
        return reply

    def _persist_exchange(
        self,
        db: Session,
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

        db.add(
            CustomerChatMessage(
                customer_id=customer.id,
                role=ChatRole.USER,
                content=user_message,
                context_json=json.dumps(audit_context) if audit_context else None,
            )
        )
        db.add(
            CustomerChatMessage(
                customer_id=customer.id,
                role=ChatRole.ASSISTANT,
                content=reply,
            )
        )
        db.commit()


universal_assistant_service = UniversalAssistantService()
