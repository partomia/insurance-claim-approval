from typing import Optional

from sqlalchemy.orm import Session, joinedload

from models.assistant_memory import AssistantOwnerType, AssistantPersona
from models.claim import Claim
from services.assistant_memory_service import assistant_memory_service
from services.assistant_response_service import (
    AssistantIntent,
    build_llm_reply,
    build_template_reply,
    detect_intent,
    normalize_structured_reply,
    uses_template_reply,
)


class ClaimAssistantService:
    def __init__(self) -> None:
        self._memory = assistant_memory_service

    def get_history(self, db: Session, claim_id: int, customer_id: int) -> list[dict]:
        session = self._memory.get_or_create_session(
            db,
            owner_type=AssistantOwnerType.CUSTOMER,
            owner_id=customer_id,
            persona=AssistantPersona.CUSTOMER_COPILOT,
        )
        thread = self._memory.get_or_create_claim_thread(db, session, claim_id)
        return self._memory.get_thread_history(db, thread)

    def _build_context(
        self,
        claim: Claim,
        intent: AssistantIntent = AssistantIntent.GENERAL,
    ) -> str:
        parts = [
            f"Claim: {claim.claim_number}",
            f"Status: {claim.status.value}",
            f"Incident: {claim.incident_description[:200]}",
            f"Location: {claim.location}",
            f"Amount: ${claim.claim_amount:,.2f}",
        ]

        include_policy_detail = intent in (AssistantIntent.COVERAGE, AssistantIntent.DOCUMENTS)
        if include_policy_detail:
            ctx = claim.policy_context_json or {}
            if ctx.get("coverage_summary"):
                parts.append(f"Policy summary: {str(ctx.get('coverage_summary', ''))[:200]}")
            if ctx.get("exclusions"):
                parts.append(f"Exclusions: {ctx.get('exclusions', [])[:3]}")

        if claim.policy:
            parts.append(
                f"Policy: {claim.policy.policy_number} ({claim.policy.policy_type}), "
                f"limit ${claim.policy.coverage_limit:,.0f}, deductible ${claim.policy.deductible:,.0f}"
            )

        if intent in (AssistantIntent.DOCUMENTS, AssistantIntent.COVERAGE):
            for doc in claim.documents or []:
                if doc.ocr_text:
                    parts.append(
                        f"Document [{doc.doc_type.value}] {doc.original_filename}: {doc.ocr_text[:150]}"
                    )

        from services.analysis_service import format_analysis_context_for_assistant

        if claim.decision:
            parts.append(format_analysis_context_for_assistant(claim))

        if intent == AssistantIntent.DOCUMENTS:
            issues = claim.evidence_issues if isinstance(claim.evidence_issues, list) else []
            if issues:
                parts.append("Evidence issues:")
                for issue in issues[:3]:
                    if isinstance(issue, dict):
                        parts.append(f"- {issue.get('field')}: {issue.get('reason', '')[:100]}")

        flags = claim.escalation_flags if isinstance(claim.escalation_flags, list) else []
        if flags and intent != AssistantIntent.GENERAL:
            parts.append(f"Escalation flags: {flags[:3]}")
        if claim.assigned_agent:
            parts.append(f"Assigned agent: {claim.assigned_agent}")

        return "\n".join(parts)

    def _system_prompt(self, claim: Claim) -> str:
        return (
            "You are ClaimCopilot, a friendly insurance assistant for policyholders. "
            "The user is the customer — speak to them directly with plain language and helpful next steps. "
            "When CUSTOMER-FACING AI ANALYSIS is provided, those numbers match the Track Claim page — never contradict them. "
            "Policy excerpts are supplementary only."
        )

    def chat(self, db: Session, claim: Claim, user_message: str) -> str:
        session = self._memory.get_or_create_session(
            db,
            owner_type=AssistantOwnerType.CUSTOMER,
            owner_id=claim.customer_id,
            persona=AssistantPersona.CUSTOMER_COPILOT,
        )
        thread = self._memory.get_or_create_claim_thread(db, session, claim.id)

        intent = detect_intent(user_message)

        if uses_template_reply(intent, claim):
            reply = build_template_reply(claim, intent)
            self._memory.persist_exchange(db, thread, user_message, reply)
            self._memory.maybe_compact_thread(db, thread, session)
            return reply

        summary_text, recent_messages = self._memory.load_context_window(db, thread)
        ltm = self._memory.format_long_term_memory(session)
        context = self._build_context(claim, intent)
        history_text = self._memory.format_history_text(recent_messages)

        context_parts = []
        if ltm:
            context_parts.append(ltm)
        context_parts.append(f"CLAIM CONTEXT:\n{context}")
        if summary_text:
            context_parts.append(f"THREAD SUMMARY:\n{summary_text}")

        reply = build_llm_reply(
            self._system_prompt(claim),
            f"""{chr(10).join(context_parts)}

CONVERSATION HISTORY:
{history_text}

USER: {user_message}""",
        )
        reply = normalize_structured_reply(reply)

        self._memory.persist_exchange(db, thread, user_message, reply)
        self._memory.maybe_compact_thread(db, thread, session)
        return reply

    def load_claim(self, db: Session, claim_id: int, customer_id: int) -> Claim | None:
        return (
            db.query(Claim)
            .options(
                joinedload(Claim.policy),
                joinedload(Claim.documents),
                joinedload(Claim.decision),
            )
            .filter(Claim.id == claim_id, Claim.customer_id == customer_id)
            .first()
        )


assistant_service = ClaimAssistantService()
