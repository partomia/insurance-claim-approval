"""Thin wrappers over the existing pipeline services so CrewAI Agents can call
them as tools. Every wrapper:

- opens its own `SessionLocal` and closes it in a `finally`,
- returns a plain `dict` matching what the legacy pipeline emits,
- publishes to `progress_service` with the SAME event names / payload shape
  the frontend SSE stream consumes today — this is a hard contract.

We intentionally do NOT re-implement the service logic here — we delegate to
the private `_run_*` helpers already living in `services/claim_pipeline.py` so
the CrewAI path stays bit-identical to the legacy path.
"""

from __future__ import annotations

from typing import Any

from services.claim_pipeline import (
    _run_customer_profile,
    _run_evidence_analysis,
    _run_fraud_detection,
    _run_policy_validation,
    _run_rag_retrieval,
    finalize_claim as _finalize_claim,
)


def policy_validation_tool(claim_id: int) -> dict[str, Any]:
    """Check policy expiry, premium status, and exclusions."""
    return _run_policy_validation(claim_id)


def rag_retrieval_tool(claim_id: int) -> dict[str, Any]:
    """Retrieve motor policy clauses matching the incident from ChromaDB."""
    return _run_rag_retrieval(claim_id)


def customer_profile_tool(claim_id: int) -> dict[str, Any]:
    """Score the customer's risk profile from claim + payment history."""
    return _run_customer_profile(claim_id)


def evidence_analysis_tool(claim_id: int) -> dict[str, Any]:
    """OCR + validate every uploaded motor-claim document."""
    return _run_evidence_analysis(claim_id)


def fraud_detection_tool(claim_id: int, evidence_data: dict[str, Any]) -> dict[str, Any]:
    """Rules-based + LLM fraud scoring. Requires evidence results as input."""
    return _run_fraud_detection(claim_id, evidence_data)


def finalize_tool(claim_id: int, merged_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Run escalation → explainability → decision → payout → LLM reasoning.

    This wraps `services.claim_pipeline.finalize_claim` verbatim so the audit
    trail (`PARALLEL_ANALYSIS_COMPLETE`, `DECISION_GENERATED`) is preserved.
    """
    return _finalize_claim(claim_id, merged_results)


# Public tool registry — used by `agents.py` when composing CrewAI Agents.
PIPELINE_TOOLS = {
    "policy_validation": policy_validation_tool,
    "rag_retrieval": rag_retrieval_tool,
    "customer_profile": customer_profile_tool,
    "evidence_analysis": evidence_analysis_tool,
    "fraud_detection": fraud_detection_tool,
    "finalize": finalize_tool,
}
