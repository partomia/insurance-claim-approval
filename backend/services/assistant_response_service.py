"""Structured, short assistant replies — templates for claim intents, constrained LLM for general."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from models.claim import Claim
from services.analysis_service import analysis_to_dict
from services.llm_service import llm_service

ASSISTANT_FORMAT_RULES = """
Reply format (required, max 100 words):
**In short:** one plain-English sentence
**What this means for you:**
- max 2 bullet points
**Do this next:** one action the customer can take today
Rules: no legalese, no repeating dashboard numbers unless asked, no section-by-section policy quotes.
""".strip()

EXPERT_ASSISTANT_FORMAT_RULES = """
Reply format (strict — aim for 70-100 words total):
**Summary:** one sentence that directly answers the expert's latest question
**Key findings:**
- most important fact (required)
- second fact only if essential (optional)
**Recommended action:** one concrete expert next step

Rules:
- Match the expert's topic: POLICY questions → policy facts; CLAIM questions → claim status/payout; DOCUMENT questions → files/evidence
- If the expert corrected you or changed topic, answer the NEW topic — do not repeat your previous reply
- Internal expert tone; refer to "the customer", not "you"
- Be accurate to CONTEXT only; no filler or legalese
""".strip()

MAX_EXPERT_WORDS = 110
MAX_ASSISTANT_WORDS = 120


class AssistantIntent(str, Enum):
    NEXT_STEP = "next_step"
    STATUS = "status"
    DOCUMENTS = "documents"
    COVERAGE = "coverage"
    GENERAL = "general"


_TEMPLATE_INTENTS = frozenset(
    {AssistantIntent.NEXT_STEP, AssistantIntent.STATUS, AssistantIntent.DOCUMENTS}
)


def detect_intent(message: str) -> AssistantIntent:
    text = message.lower().strip()
    if any(
        k in text
        for k in (
            "next step",
            "what should i do",
            "review and submit",
            "help me with this next step",
            "what do i do now",
            "how do i submit",
        )
    ):
        return AssistantIntent.NEXT_STEP
    if any(
        k in text
        for k in (
            "approval",
            "approve",
            "settlement",
            "payout",
            "payable",
            "how much",
            "probability",
            "status of my claim",
            "claim status",
        )
    ):
        return AssistantIntent.STATUS
    if any(
        k in text
        for k in (
            "document",
            "upload",
            "missing",
            "proof",
            "evidence",
            "what do i need to submit",
        )
    ):
        return AssistantIntent.DOCUMENTS
    if any(
        k in text
        for k in (
            "covered",
            "coverage",
            "deductible",
            "co-pay",
            "copay",
            "policy",
            "clause",
            "hospital",
            "motor",
        )
    ):
        return AssistantIntent.COVERAGE
    return AssistantIntent.GENERAL


def uses_template_reply(intent: AssistantIntent, claim: Optional[Claim]) -> bool:
    return claim is not None and claim.decision is not None and intent in _TEMPLATE_INTENTS


def _format_money(amount: float) -> str:
    return f"${amount:,.2f}"


def _approval_headline(approval_pct: int) -> str:
    if approval_pct >= 85:
        return f"Your claim looks strong — about {approval_pct}% likely to be approved."
    if approval_pct >= 60:
        return f"Your claim has a fair chance — about {approval_pct}% approval likelihood."
    return f"Your claim needs attention — about {approval_pct}% approval likelihood right now."


def build_template_reply(claim: Claim, intent: AssistantIntent) -> str:
    if not claim.decision:
        return (
            "**In short:** Your claim is still being reviewed.\n\n"
            "**Do this next:** Check back on the Track Claim page in a few minutes.\n\n"
            "_Need help? Ask about coverage or documents._"
        )

    analysis = analysis_to_dict(claim.decision, claim)
    approval_pct = round(float(analysis["approval_probability"]) * 100)
    coverage = float(analysis["coverage_estimate"])
    settlement = float(analysis["expected_settlement"])
    next_action = analysis.get("next_best_action") or "Review claim details"

    if intent == AssistantIntent.DOCUMENTS:
        missing = analysis.get("missing_documents") or []
        recs = (analysis.get("recommendations") or [])[:2]
        lines = [
            "**In short:** Here is what you need for a stronger claim.",
            "",
            "**Your numbers**",
        ]
        if missing:
            for doc in missing[:4]:
                lines.append(f"- Upload: {doc}")
        elif recs:
            for rec in recs:
                lines.append(f"- {rec}")
        else:
            lines.append("- Your documents look complete so far.")
        lines.extend(
            [
                "",
                f"**Do this next:** {next_action}",
                "",
                "_Questions? Ask about approval odds or coverage._",
            ]
        )
        return "\n".join(lines)

    headline = _approval_headline(approval_pct)
    if intent == AssistantIntent.NEXT_STEP:
        headline = f"Here is your best next move for claim {claim.claim_number}."

    return "\n".join(
        [
            f"**In short:** {headline}",
            "",
            "**Your numbers**",
            f"- Approval chance: {approval_pct}%",
            f"- Coverage estimate: {_format_money(coverage)}",
            f"- Expected payout: {_format_money(settlement)}",
            "",
            f"**Do this next:** {next_action}",
            "",
            "_Need help? Ask about documents or coverage._",
        ]
    )


def enforce_limits(text: str, max_words: int = MAX_ASSISTANT_WORDS) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned
    trimmed = " ".join(words[:max_words]).rstrip(".,;:")
    return trimmed + "…"


def build_llm_reply(
    system_prompt: str,
    user_payload: str,
    *,
    max_tokens: int = 280,
    format_rules: str | None = None,
    temperature: float = 0,
) -> str:
    rules = format_rules or ASSISTANT_FORMAT_RULES
    full_system = f"{system_prompt}\n\n{rules}"
    raw = llm_service.invoke_assistant(
        full_system,
        user_payload,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if not raw:
        return (
            "**In short:** I can help with coverage, documents, and claim prep.\n\n"
            "**Do this next:** Ask a specific question about your policy or claim.\n\n"
            "_Configure GROQ_API_KEY for full AI responses._"
        )
    return enforce_limits(raw)


def build_expert_llm_reply(
    system_prompt: str,
    user_payload: str,
    *,
    max_tokens: int = 512,
) -> str | None:
    """Return LLM text, or None when the caller should use a context fallback."""
    if not llm_service._has_valid_key():
        return None
    raw = build_llm_reply(
        system_prompt,
        user_payload,
        max_tokens=max_tokens,
        format_rules=EXPERT_ASSISTANT_FORMAT_RULES,
        temperature=0.15,
    )
    if not raw or "Configure GROQ_API_KEY" in raw:
        return None
    return raw


def _trim_expert_bullets(text: str, max_bullets: int = 2) -> str:
    lines = text.splitlines()
    out: list[str] = []
    bullet_count = 0
    in_findings = False

    for line in lines:
        lower = line.lower()
        if "**key findings:**" in lower:
            in_findings = True
            out.append(line)
            continue
        if in_findings and lower.startswith("**") and "key findings" not in lower:
            in_findings = False

        if in_findings and line.strip().startswith("-"):
            bullet_count += 1
            if bullet_count > max_bullets:
                continue
        out.append(line)

    return "\n".join(out)


def normalize_expert_structured_reply(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return (
            "**Summary:** I couldn't generate a reply.\n\n"
            "**Recommended action:** Rephrase your question about the policy, claim, or documents."
        )

    if "**Summary:**" not in cleaned and "**In short:**" not in cleaned:
        cleaned = f"**Summary:** {cleaned}"
    if "**Recommended action:**" not in cleaned and "**Do this next:**" not in cleaned:
        cleaned = f"{cleaned}\n\n**Recommended action:** Ask a follow-up if you need more detail."
    if "**Key findings:**" not in cleaned and "**What this means for you:**" not in cleaned:
        cleaned = cleaned.replace(
            "**Recommended action:**",
            "**Key findings:**\n- See summary above.\n\n**Recommended action:**",
            1,
        )

    cleaned = _trim_expert_bullets(cleaned, max_bullets=2)
    return enforce_limits(cleaned, max_words=MAX_EXPERT_WORDS)


def normalize_structured_reply(text: str) -> str:
    """Ensure minimum structure if the model omitted section headers."""
    if "**In short:**" in text:
        return enforce_limits(text)
    return enforce_limits(f"**In short:** {text}\n\n**Do this next:** Reply with more detail if you need help.")


def slim_rag_lines(clause_lines: list[str], *, max_clauses: int = 2, max_chars: int = 120) -> str:
    if not clause_lines:
        return "No matching policy clauses found."
    trimmed = []
    for line in clause_lines[:max_clauses]:
        if len(line) > max_chars:
            trimmed.append(line[: max_chars - 1] + "…")
        else:
            trimmed.append(line)
    return "\n".join(trimmed)
