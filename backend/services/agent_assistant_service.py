"""Expert Copilot — scoped assistant for policy agents reviewing assigned claims."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session, joinedload

from models.assistant_memory import AssistantOwnerType, AssistantPersona
from models.chat import ChatRole
from models.claim import Claim
from models.customer import Customer
from models.platform import CustomerProfile
from models.policy_agent import PolicyAgent
from services.agent_service import agent_service
from services.analysis_service import analysis_to_dict, format_analysis_context_for_assistant
from services.assistant_memory_service import assistant_memory_service
from services.assistant_response_service import (
    build_expert_llm_reply,
    normalize_expert_structured_reply,
)
from services.llm_service import llm_service
from services.customer_profile import CustomerProfileService
from services.kyc_service import effective_kyc_status

EXPERT_SYSTEM_PROMPT = (
    "You are Expert Copilot for insurance claim experts (internal tool). "
    "Answer the expert's LATEST message using CONTEXT facts only. "
    "POLICY questions → explain the policy product (limits, co-pay, deductible, exclusions, sections). "
    "CLAIM questions → status, payout, approval, fraud, next steps. "
    "DOCUMENT questions → uploaded files and evidence issues. "
    "CUSTOMER questions → risk/KYC/history. "
    "If the expert corrected you or changed topic, do NOT repeat your previous answer — address the new topic. "
    "Keep replies concise, structured, and accurate."
)


def detect_expert_focus(message: str, history: list) -> str:
    text = message.lower().strip()

    if any(p in text for p in ("not claim", "not the claim", "policy not claim", "i said policy", "about policy not")):
        return "policy"
    if any(p in text for p in ("not policy", "i said claim", "about claim not", "claim not policy")):
        return "claim"

    scores = {
        "policy": 0,
        "claim": 0,
        "documents": 0,
        "customer": 0,
    }
    policy_kw = (
        "policy", "coverage limit", "deductible", "co-pay", "copay", "exclusion",
        "clause", "schedule", "sum insured", "premium", "policy insights", "his policy",
        "her policy", "policy of this user", "policy details", "policy number",
    )
    claim_kw = (
        "claim status", "approval", "payout", "settlement", "payable", "fraud",
        "what is this claim", "claim about", "this claim", "missing requirement",
    )
    doc_kw = ("document", "upload", "discharge", "invoice", "ocr", "evidence", "file", "proof")
    customer_kw = ("customer", "risk profile", "kyc", "prior claim", "account")

    for kw in policy_kw:
        if kw in text:
            scores["policy"] += 2 if "policy" == kw else 1
    for kw in claim_kw:
        if kw in text:
            scores["claim"] += 2 if "claim" in kw else 1
    for kw in doc_kw:
        if kw in text:
            scores["documents"] += 1
    for kw in customer_kw:
        if kw in text:
            scores["customer"] += 1

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        # infer from recent user turns
        for msg in reversed(history):
            if getattr(msg, "role", None) and msg.role.value == "user":
                return detect_expert_focus(msg.content, [])
        return "general"
    return best


FOCUS_INSTRUCTIONS = {
    "policy": (
        "FOCUS: POLICY — Explain the customer's insurance policy (product, limits, co-pay, deductible, exclusions, key sections). "
        "Do not lead with claim payout or approval % unless the expert asked for both."
    ),
    "claim": (
        "FOCUS: CLAIM — Explain claim status, incident, AI analysis, payout/approval, and review next steps. "
        "Keep policy details brief unless relevant."
    ),
    "documents": (
        "FOCUS: DOCUMENTS — List uploaded files, gaps, and evidence issues. Recommend specific document actions."
    ),
    "customer": (
        "FOCUS: CUSTOMER — Summarize customer profile, KYC, and risk signals relevant to this case."
    ),
    "general": (
        "FOCUS: Answer the expert's question directly using the most relevant CONTEXT section."
    ),
}


class AgentAssistantService:
    MEMORY_LIMIT = 20

    def _session(self, db: Session, agent_id: int):
        return assistant_memory_service.get_or_create_session(
            db,
            owner_type=AssistantOwnerType.AGENT,
            owner_id=agent_id,
            persona=AssistantPersona.EXPERT_COPILOT,
        )

    def get_history(self, db: Session, agent_id: int) -> list[dict]:
        # Legacy agent chat was a flat table keyed by agent_id, so the router
        # doesn't scope by thread. Aggregate across every thread for this session
        # to preserve that behavior.
        from models.assistant_memory import AssistantMessage, AssistantThread

        session = self._session(db, agent_id)
        messages = (
            db.query(AssistantMessage)
            .join(AssistantThread, AssistantThread.id == AssistantMessage.thread_id)
            .filter(AssistantThread.session_id == session.id)
            .order_by(AssistantMessage.created_at.asc())
            .limit(50)
            .all()
        )
        return [
            {
                "role": m.role.value,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]

    def _load_claim(self, db: Session, agent: PolicyAgent, claim_id: int) -> Claim | None:
        return (
            agent_service._assigned_query(db, agent.id)
            .options(
                joinedload(Claim.policy),
                joinedload(Claim.documents),
                joinedload(Claim.decision),
                joinedload(Claim.customer),
            )
            .filter(Claim.id == claim_id)
            .first()
        )

    def _verify_customer(self, db: Session, agent: PolicyAgent, customer_id: int) -> Customer | None:
        has_claim = (
            agent_service._assigned_query(db, agent.id)
            .filter(Claim.customer_id == customer_id)
            .first()
        )
        if not has_claim:
            return None
        return db.query(Customer).filter(Customer.id == customer_id).first()

    def _format_policy_section(self, claim: Claim) -> list[str]:
        lines = ["POLICY (customer's insurance product):"]
        policy = claim.policy
        if policy:
            lines.extend(
                [
                    f"- Policy number: {policy.policy_number}",
                    f"- Type: {policy.policy_type}",
                    f"- Status: {policy.status.value if hasattr(policy.status, 'value') else policy.status}",
                    f"- Coverage limit: ${policy.coverage_limit:,.2f}",
                    f"- Deductible: ${policy.deductible:,.2f}",
                    f"- Co-pay: {policy.co_pay_pct}%",
                    f"- Effective: {policy.effective_date.date() if policy.effective_date else 'n/a'} to {policy.expiry_date.date() if policy.expiry_date else 'n/a'}",
                ]
            )
            if policy.exclusions:
                lines.append(f"- Policy exclusions (DB): {', '.join(str(x) for x in policy.exclusions[:6])}")

        requirements = agent_service.build_policy_requirements(claim)
        if requirements.get("coverage_summary"):
            lines.append(f"- Coverage summary: {str(requirements['coverage_summary'])[:400]}")
        exclusions = requirements.get("exclusions") or []
        if exclusions:
            lines.append("- Schedule exclusions:")
            for item in exclusions[:8]:
                lines.append(f"  • {item}")
        key_sections = requirements.get("key_sections") or []
        if key_sections:
            lines.append("- Key policy sections:")
            for section in key_sections[:6]:
                if isinstance(section, dict):
                    ref = section.get("ref", section.get("section_ref", ""))
                    summary = str(section.get("summary", section.get("content", "")))[:160]
                    lines.append(f"  • {ref}: {summary}")
        key_clauses = requirements.get("key_clauses") or []
        if key_clauses:
            lines.append("- Clauses matched / retrieved for this claim:")
            for clause in key_clauses[:6]:
                if isinstance(clause, dict):
                    lines.append(
                        f"  • {clause.get('section_ref', '')}: "
                        f"{str(clause.get('summary', ''))[:160]}"
                    )
        matches = requirements.get("policy_clause_matches") or []
        if matches:
            lines.append("- Clause alignment notes:")
            for match in matches[:4]:
                if isinstance(match, dict):
                    lines.append(f"  • {match}")
                else:
                    lines.append(f"  • {match}")
        if len(lines) == 1:
            lines.append("- No indexed policy context on this claim yet.")
        return lines

    def _build_context(
        self,
        db: Session,
        claim: Claim | None,
        customer: Customer | None,
        document_id: Optional[int] = None,
        *,
        focus: str = "general",
    ) -> str:
        parts: list[str] = ["Internal expert review context. Audience: claim expert only."]

        if customer and focus in ("customer", "general", "policy"):
            parts.append("")
            parts.append("CUSTOMER:")
            parts.append(f"- Name: {customer.full_name}")
            parts.append(f"- Email: {customer.email}")
            profile = (
                db.query(CustomerProfile)
                .filter(CustomerProfile.customer_id == customer.id)
                .first()
            )
            if profile:
                parts.append(f"- KYC: {effective_kyc_status(profile).value}")

        if not claim:
            return "\n".join(parts)

        if focus in ("policy", "general", "claim"):
            parts.extend(self._format_policy_section(claim))

        if focus in ("claim", "general", "documents"):
            parts.append("")
            parts.append("CLAIM:")
            parts.append(f"- Number: {claim.claim_number}")
            parts.append(f"- Status: {claim.status.value}")
            parts.append(f"- Incident: {claim.incident_description[:220]}")
            parts.append(f"- Location: {claim.location}")
            parts.append(f"- Claimed amount: ${claim.claim_amount:,.2f}")
            if claim.assigned_agent:
                parts.append(f"- Assigned expert: {claim.assigned_agent}")

            if claim.decision and focus != "policy":
                parts.append("")
                parts.append(format_analysis_context_for_assistant(claim))
            elif claim.decision and focus == "policy":
                parts.append(f"- AI approval (reference only): {round(float(claim.decision.approval_probability or 0) * 100)}%")

        if focus in ("documents", "general", "claim"):
            parts.append("")
            parts.append("DOCUMENTS:")
            docs = claim.documents or []
            if document_id:
                docs = [d for d in docs if d.id == document_id] or docs
            if docs:
                for doc in docs[:6 if focus == "documents" else 4]:
                    snippet = (doc.ocr_text or "")[:140]
                    parts.append(
                        f"- [{doc.doc_type.value}] {doc.original_filename}: {snippet or 'no OCR text'}"
                    )
            else:
                parts.append("- None uploaded.")

            issues = claim.evidence_issues if isinstance(claim.evidence_issues, list) else []
            if issues:
                parts.append("")
                parts.append("EVIDENCE ISSUES:")
                for issue in issues[:4]:
                    if isinstance(issue, dict):
                        parts.append(
                            f"- {issue.get('filename', 'file')}: {issue.get('reason', '')[:100]}"
                        )

        if focus in ("claim", "general") and claim.escalation_flags:
            flags = claim.escalation_flags if isinstance(claim.escalation_flags, list) else []
            if flags:
                parts.append(f"Escalation flags: {flags[:4]}")

        if focus in ("customer", "general") and claim.policy:
            try:
                risk = CustomerProfileService().analyze(db, claim)
                parts.append("")
                parts.append("CUSTOMER RISK:")
                parts.append(f"- Risk score: {risk.customer_risk_score:.2f}")
                parts.append(f"- Prior claims: {risk.prior_claims_count}")
                if risk.signals:
                    parts.append(f"- Signals: {', '.join(str(s) for s in risk.signals[:4])}")
            except Exception:
                pass

        return "\n".join(parts)

    def _structured_fallback(
        self,
        focus: str,
        claim: Claim | None,
        message: str,
    ) -> str:
        if not claim:
            if not llm_service._has_valid_key():
                return (
                    "**Summary:** Expert Copilot needs GROQ_API_KEY in the backend .env file.\n\n"
                    "**Recommended action:** Add GROQ_API_KEY and restart the backend."
                )
            return (
                "**Summary:** No claim is loaded in this workspace.\n\n"
                "**Recommended action:** Open an assigned claim and ask again."
            )

        policy = claim.policy
        requirements = agent_service.build_policy_requirements(claim)

        if focus == "policy" or "policy" in message.lower():
            if policy:
                exclusions = requirements.get("exclusions") or list(policy.exclusions or [])[:3]
                excl_text = "; ".join(str(x) for x in exclusions[:2]) if exclusions else "none listed"
                sections = requirements.get("key_sections") or []
                section_hint = ""
                if sections and isinstance(sections[0], dict):
                    section_hint = f" Key section: {sections[0].get('ref', '')} — {str(sections[0].get('summary', ''))[:80]}."
                return "\n".join(
                    [
                        f"**Summary:** {policy.policy_number} is an active {policy.policy_type} policy with ${policy.coverage_limit:,.0f} sum insured.",
                        "",
                        "**Key findings:**",
                        f"- Deductible ${policy.deductible:,.0f}, co-pay {policy.co_pay_pct}%",
                        f"- Exclusions include: {excl_text}{section_hint}",
                        "",
                        "**Recommended action:** Explain coverage and exclusions to the customer before requesting missing policy documents.",
                    ]
                )

        if focus == "documents" or any(k in message.lower() for k in ("document", "upload", "file", "evidence")):
            docs = claim.documents or []
            missing = list(requirements.get("missing_documents") or [])
            doc_names = ", ".join(d.original_filename for d in docs[:3]) if docs else "none uploaded"
            return "\n".join(
                [
                    f"**Summary:** {len(docs)} document(s) on file for {claim.claim_number}.",
                    "",
                    "**Key findings:**",
                    f"- Files: {doc_names}",
                    f"- Missing / flagged: {', '.join(missing[:3]) if missing else 'none flagged'}",
                    "",
                    "**Recommended action:** Request any missing items via the consultation workflow.",
                ]
            )

        if focus == "customer":
            return "\n".join(
                [
                    f"**Summary:** Customer on claim {claim.claim_number} — review profile and risk before consultation.",
                    "",
                    "**Key findings:**",
                    f"- Claim amount ${claim.claim_amount:,.2f} at {claim.location}",
                    "",
                    "**Recommended action:** Open the customer profile and verify KYC plus prior claims.",
                ]
            )

        if claim.decision:
            analysis = analysis_to_dict(claim.decision, claim)
            approval_pct = round(float(analysis.get("approval_probability", 0)) * 100)
            missing = analysis.get("missing_documents") or []
            missing_line = ", ".join(missing[:2]) if missing else "none flagged"
            return "\n".join(
                [
                    f"**Summary:** {claim.claim_number} is {claim.status.value.replace('_', ' ').lower()} with {approval_pct}% AI approval likelihood.",
                    "",
                    "**Key findings:**",
                    f"- Expected settlement ${float(analysis.get('expected_settlement', 0)):,.2f}",
                    f"- Missing items: {missing_line}",
                    "",
                    f"**Recommended action:** {analysis.get('next_best_action') or 'Continue expert review.'}",
                ]
            )

        return "\n".join(
            [
                f"**Summary:** {claim.claim_number} — ${claim.claim_amount:,.2f} {policy.policy_type if policy else ''} claim.",
                "",
                "**Recommended action:** Review submission, policy requirements, and documents.",
            ]
        )

    def chat(
        self,
        db: Session,
        agent: PolicyAgent,
        message: str,
        *,
        claim_id: Optional[int] = None,
        customer_id: Optional[int] = None,
        document_id: Optional[int] = None,
    ) -> str:
        claim = self._load_claim(db, agent, claim_id) if claim_id else None
        customer = None
        if customer_id:
            customer = self._verify_customer(db, agent, customer_id)
        elif claim and claim.customer:
            customer = claim.customer

        if claim_id and not claim:
            return "**Summary:** That claim is not in your assigned queue.\n\n**Recommended action:** Pick a claim from your work queue."

        session = self._session(db, agent.id)
        thread = assistant_memory_service.resolve_thread(
            db, session, claim_id=claim_id
        )
        _, history = assistant_memory_service.load_context_window(db, thread)
        # detect_expert_focus reads .role.value and .content, both present on AssistantMessage.
        focus = detect_expert_focus(message, history)
        context = self._build_context(db, claim, customer, document_id, focus=focus)
        history_text = "\n".join(f"{m.role.value}: {m.content}" for m in history)
        last_assistant = next((m.content for m in reversed(history) if m.role == ChatRole.ASSISTANT), "")

        focus_block = FOCUS_INSTRUCTIONS.get(focus, FOCUS_INSTRUCTIONS["general"])
        anti_repeat = ""
        if last_assistant:
            anti_repeat = (
                f"\nPREVIOUS ASSISTANT REPLY (do not copy if the expert changed topic or corrected you):\n"
                f"{last_assistant[:500]}\n"
            )

        reply = build_expert_llm_reply(
            EXPERT_SYSTEM_PROMPT,
            f"""{focus_block}

CONTEXT:
{context}
{anti_repeat}
CONVERSATION:
{history_text or 'No prior messages.'}

EXPERT QUESTION: {message}

Write a fresh structured reply for the question above. Match FOCUS. 70-100 words.""",
            max_tokens=512,
        )
        if not reply:
            reply = self._structured_fallback(focus, claim, message)
        reply = normalize_expert_structured_reply(reply)

        context_payload = {
            "claim_id": claim_id,
            "customer_id": customer_id,
            "document_id": document_id,
        }
        assistant_memory_service.persist_exchange(
            db, thread, message, reply, context_json=context_payload
        )
        assistant_memory_service.maybe_compact_thread(db, thread, session)
        return reply


agent_assistant_service = AgentAssistantService()
