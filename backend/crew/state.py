"""Typed Pydantic state carried through the CrewAI ClaimFlow.

Replaces the untyped `dict` threaded through `claim_pipeline.py`. Every stage
result is optional so the state can be constructed empty at `@start` and
progressively filled in by each `@listen` node.
"""

# NOTE: we deliberately do NOT `from __future__ import annotations` here —
# Pydantic v2 evaluates field types at class-body time, and with deferred
# evaluation on an Optional/Any field it raises PydanticUserError
# ("`ClaimFlowState` is not fully defined") when constructed from a namespace
# where `Optional` isn't visible in the module's globals at rebuild time.

from typing import Any, Optional

from pydantic import BaseModel, Field


class ClaimFlowState(BaseModel):
    """Shared state for the motor claim adjudication flow."""

    claim_id: int = 0
    pipeline_run_id: int = 0

    # Parallel-fan-out stage results (populated by the 4 analysis @listen nodes).
    policy_validation: Optional[dict[str, Any]] = None
    rag_retrieval: Optional[dict[str, Any]] = None
    customer_profile: Optional[dict[str, Any]] = None
    evidence_analysis: Optional[dict[str, Any]] = None

    # Sequential stage results.
    fraud_detection: Optional[dict[str, Any]] = None
    escalation: Optional[dict[str, Any]] = None
    explainability: Optional[dict[str, Any]] = None
    decision: Optional[dict[str, Any]] = None
    payout: Optional[dict[str, Any]] = None

    # Final result packet emitted by finalize().
    final_result: Optional[dict[str, Any]] = Field(default=None)

    def merged_analysis(self) -> dict[str, Any]:
        """Merge every populated stage block into a flat dict.

        The legacy pipeline threads the same shape through `finalize_claim` and
        downstream services (fraud, escalation, decision) so this preserves the
        contract byte-for-byte.
        """
        merged: dict[str, Any] = {}
        for block in (
            self.policy_validation,
            self.rag_retrieval,
            self.customer_profile,
            self.evidence_analysis,
            self.fraud_detection,
        ):
            if block:
                merged.update(block)
        return merged
