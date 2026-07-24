from typing import Optional

from sqlalchemy.orm import Session, joinedload

from models.chat import ChatRole, ClaimChatMessage
from models.claim import Claim
from services.analysis_service import format_analysis_context_for_assistant
from services.assistant_response_service import (
    AssistantIntent,
    build_llm_reply,
    build_template_reply,
    detect_intent,
    normalize_structured_reply,
    uses_template_reply,
)


class ClaimAssistantService:
    MEMORY_LIMIT = 20

    def get_history(self, db: Session, claim_id: int) -> list[dict]:
        messages = (
            db.query(ClaimChatMessage)
            .filter(ClaimChatMessage.claim_id == claim_id)
            .order_by(ClaimChatMessage.created_at.asc())
            .all()
        )
        return [
            {"role": m.role.value, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in messages
        ]

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
        intent = detect_intent(user_message)

        if uses_template_reply(intent, claim):
            return build_template_reply(claim, intent)

        history = (
            db.query(ClaimChatMessage)
            .filter(ClaimChatMessage.claim_id == claim.id)
            .order_by(ClaimChatMessage.created_at.desc())
            .limit(self.MEMORY_LIMIT)
            .all()
        )
        history.reverse()

        context = self._build_context(claim, intent)
        history_text = "\n".join(f"{m.role.value}: {m.content}" for m in history)

        reply = build_llm_reply(
            self._system_prompt(claim),
            f"""CLAIM CONTEXT:
{context}

CONVERSATION HISTORY:
{history_text or 'No prior messages.'}

USER: {user_message}""",
        )
        reply = normalize_structured_reply(reply)

        db.add(ClaimChatMessage(claim_id=claim.id, role=ChatRole.USER, content=user_message))
        db.add(ClaimChatMessage(claim_id=claim.id, role=ChatRole.ASSISTANT, content=reply))
        db.commit()
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
