"""CrewAI Agent definitions for the motor claim adjudication pipeline.

Role / goal / backstory strings are lifted verbatim from `docs/agents/AGENTS.md`
so the docs stay the single source of truth for agent identity.

Note: the current flow (`flow.py`) invokes the underlying services directly via
`crew/tools.py` for parity + performance. These Agent objects are here so
future work — e.g. an LLM-driven `Crew` variant, or exposing individual agents
via a debug endpoint — can compose them without re-authoring the metadata.
"""

from __future__ import annotations

from typing import Optional

from config import get_settings

_settings = get_settings()

try:
    from crewai import Agent  # type: ignore
    from crewai.llm import LLM  # type: ignore

    _CREWAI_AVAILABLE = True
except Exception:  # pragma: no cover — dep may be absent in test envs
    Agent = None  # type: ignore
    LLM = None  # type: ignore
    _CREWAI_AVAILABLE = False


def _groq_llm() -> Optional["LLM"]:
    """Build a CrewAI LLM handle pointed at Groq, or None if crewai isn't installed."""
    if not _CREWAI_AVAILABLE:
        return None
    if not _settings.groq_api_key or _settings.groq_api_key.startswith("your_"):
        return None
    return LLM(
        model=f"groq/{_settings.groq_model}",
        api_key=_settings.groq_api_key,
        temperature=0,
    )


def build_agents() -> dict[str, "Agent"]:
    """Instantiate every pipeline Agent. Returns {} if CrewAI isn't installed."""
    if not _CREWAI_AVAILABLE:
        return {}

    llm = _groq_llm()

    policy_validator = Agent(
        role="Policy Validator Agent",
        goal=(
            "Return eligible, policy_expired, premium_unpaid, incident_excluded, "
            "violations[], and policy_match_score for the claim."
        ),
        backstory=(
            "Not every claim can proceed — a lapsed policy, unpaid premium, or "
            "an incident that falls under a listed exclusion must be caught "
            "before further analysis wastes compute. First hard gate."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    rag_retrieval = Agent(
        role="RAG Retrieval Agent",
        goal=(
            "Return retrieved_clauses[], clause_clarity_score, and llm_coverage "
            "(is_covered, confidence, summary) for the claim incident."
        ),
        backstory=(
            "Motor insurance policies are dense legal documents. When a claim "
            "arrives, the adjudicator needs the exact policy section that "
            "applies. Embeds the incident query and retrieves top-k clauses "
            "from ChromaDB, then uses Groq to confirm coverage."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    customer_profile = Agent(
        role="Customer Profile Agent",
        goal="Return customer_risk_score, prior_claims_count, signals[].",
        backstory=(
            "A first-time claimant with perfect payment history is a very "
            "different risk than one with three prior escalated claims and "
            "missed premiums. Scores the customer so the Decision Engine can "
            "weigh individual risk alongside the incident facts."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    evidence_analysis = Agent(
        role="Evidence Analysis Agent",
        goal=(
            "Return evidence_confidence_score, evidence_missing, "
            "evidence_results[], duplicate_uploads[], evidence_mismatch, "
            "evidence_issues[]."
        ),
        backstory=(
            "Fraudulent claims often hinge on mismatched or fabricated "
            "documents. Runs OCR on each upload, pattern-matches against "
            "expected content, and escalates to Groq for tie-break when "
            "rule-based matching is inconclusive."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    fraud_detection = Agent(
        role="Fraud Detection Agent",
        goal=(
            "Return fraud_score (0-1), signals[], blacklist_hit; persist a "
            "FraudAssessment record."
        ),
        backstory=(
            "Motor insurance is one of the most fraud-prone lines. Staged "
            "accidents, VIN mismatches, exaggerated repair estimates, and "
            "shared submission devices are common red flags. Weighted signal "
            "model + Groq risk score averaged for the final."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    escalation_evaluator = Agent(
        role="Escalation Evaluator Agent",
        goal=(
            "Return flags[] and messages[]; update claim.escalation_flags and "
            "claim.escalation_messages in the database."
        ),
        backstory=(
            "Some claims are technically processable by the automated "
            "pipeline but still need a human eye — total-loss suspected, VIN "
            "mismatch, third-party injuries, large claim without a police "
            "report."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    decision_engine = Agent(
        role="Decision Engine Agent",
        goal=(
            "Return ClaimStatus (REJECTED / REQUEST_MORE_INFO / PENDING_REVIEW "
            "/ ANALYSIS_COMPLETE / APPROVED), reasoning, human_review_required."
        ),
        backstory=(
            "Applies a strict priority-ordered rule set — hard rejects first "
            "(expired policy, exclusion), then escalations and fraud "
            "thresholds, then low-confidence triggers — to arrive at a "
            "deterministic and auditable decision. No LLM in the final call."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    payout_calculation = Agent(
        role="Payout Calculation Agent",
        goal=(
            "Return payable_amount and a detailed breakdown dict (gross, "
            "deductible, depreciation, co-pay, cap, OD/TP split, GST, salvage, "
            "NCB)."
        ),
        backstory=(
            "Motor payouts involve deductibles, age-based depreciation, "
            "co-pay, total-loss detection against IDV, GST, own-damage vs "
            "third-party split, and next-cycle NCB. Rules engine handles "
            "total-loss (> 75% IDV); partial-loss claims go through Groq "
            "parameter extraction."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    explainability = Agent(
        role="Explainability Agent",
        goal=(
            "Return confidence_score, reasoning, retrieved_clauses[], "
            "evidence_results[], fraud_score; persist ClaimDecision and "
            "AuditLog records."
        ),
        backstory=(
            "Regulators require every automated insurance decision be "
            "explainable and auditable. Combines policy match, evidence "
            "confidence, customer risk, and clause clarity into a weighted "
            "confidence score."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    llm_reasoning = Agent(
        role="LLM Reasoning Agent",
        goal=(
            "Provide structured JSON or natural-language outputs for coverage "
            "assessment, fraud risk, payout parameters, evidence validation, "
            "clause alignment, and decision reasoning."
        ),
        backstory=(
            "Central Groq LLM wrapper. All LLM calls in the platform route "
            "through a single service with key validation, retries, JSON "
            "extraction, and token budgeting."
        ),
        tools=[],
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    return {
        "policy_validator": policy_validator,
        "rag_retrieval": rag_retrieval,
        "customer_profile": customer_profile,
        "evidence_analysis": evidence_analysis,
        "fraud_detection": fraud_detection,
        "escalation_evaluator": escalation_evaluator,
        "decision_engine": decision_engine,
        "payout_calculation": payout_calculation,
        "explainability": explainability,
        "llm_reasoning": llm_reasoning,
    }
