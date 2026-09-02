"""CrewAI Flow for motor claim adjudication.

Shape:
    @start                        → claim_received
    ┌──────────────────────────────────────────────────┐
    │ @listen(claim_received) × 4  (parallel fan-out)   │
    │   • policy_validation                              │
    │   • rag_retrieval                                  │
    │   • customer_profile                               │
    │   • evidence_analysis                              │
    └──────────────────────────────────────────────────┘
                       │
                       ▼
        @listen(and_(4 above))  →  fraud_detection
                       │
                       ▼
                    finalize   (escalation → explainability →
                                decision → payout → LLM reasoning)

Every stage emits progress events with the same names / payload shapes the
legacy `services/claim_pipeline.py` publishes, so the frontend SSE stream is
unchanged.

If `crewai` is not installed we fall back to a synchronous drop-in that still
uses `ThreadPoolExecutor` for the parallel stage — this keeps deployments that
haven't updated their dep set working after the module is imported.
"""

from __future__ import annotations

import logging
from typing import Any

from database import SessionLocal
from models.claim import Claim, ClaimStatus
from services.claim_pipeline import _handle_pipeline_failure
from services.progress_service import progress_service

from crew.state import ClaimFlowState
from crew.tools import (
    customer_profile_tool,
    evidence_analysis_tool,
    finalize_tool,
    fraud_detection_tool,
    policy_validation_tool,
    rag_retrieval_tool,
)

logger = logging.getLogger(__name__)

try:
    from crewai.flow.flow import Flow, and_, listen, start  # type: ignore

    _CREWAI_FLOW_AVAILABLE = True
except Exception:  # pragma: no cover
    _CREWAI_FLOW_AVAILABLE = False

    # Stub Flow that stays subscriptable at class-definition time so
    # `class ClaimFlow(Flow[ClaimFlowState])` still parses. Using object[T]
    # raises `TypeError: type 'object' is not subscriptable` on Python <3.14.
    class Flow:  # type: ignore
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *_a, **_kw) -> None:
            self.state = None

        def kickoff(self, *_a, **_kw):
            raise RuntimeError(
                "crewai is not installed; use run_claim_flow() which routes "
                "to a ThreadPoolExecutor fallback instead of Flow.kickoff()."
            )

    def start(*_args, **_kwargs):  # type: ignore
        def _wrap(fn):
            return fn

        return _wrap

    def listen(*_args, **_kwargs):  # type: ignore
        def _wrap(fn):
            return fn

        return _wrap

    def and_(*_args, **_kwargs):  # type: ignore
        return None


def _mark_processing(claim_id: int) -> None:
    db = SessionLocal()
    try:
        claim = db.query(Claim).filter(Claim.id == claim_id).first()
        if claim:
            claim.status = ClaimStatus.PROCESSING
            db.commit()
    finally:
        db.close()


class ClaimFlow(Flow[ClaimFlowState]):  # type: ignore[misc]
    """CrewAI Flow orchestrating the motor claim adjudication pipeline."""

    @start()
    def claim_received(self) -> int:
        """Mark the claim PROCESSING and emit the initial progress event."""
        claim_id = self.state.claim_id
        _mark_processing(claim_id)
        progress_service.publish(
            claim_id, "claim_submitted", "completed",
            "Claim received — starting review",
        )
        return claim_id

    @listen(claim_received)
    def run_policy_validation(self, claim_id: int) -> dict[str, Any]:
        result = policy_validation_tool(claim_id)
        self.state.policy_validation = result
        return result

    @listen(claim_received)
    def run_rag_retrieval(self, claim_id: int) -> dict[str, Any]:
        result = rag_retrieval_tool(claim_id)
        self.state.rag_retrieval = result
        return result

    @listen(claim_received)
    def run_customer_profile(self, claim_id: int) -> dict[str, Any]:
        result = customer_profile_tool(claim_id)
        self.state.customer_profile = result
        return result

    @listen(claim_received)
    def run_evidence_analysis(self, claim_id: int) -> dict[str, Any]:
        result = evidence_analysis_tool(claim_id)
        self.state.evidence_analysis = result
        return result

    @listen(
        and_(
            run_policy_validation,
            run_rag_retrieval,
            run_customer_profile,
            run_evidence_analysis,
        )
    )
    def run_fraud_detection(self, *_prior_results: Any) -> dict[str, Any]:
        """Fraud detection needs the evidence result, so it runs after the gate."""
        evidence = self.state.evidence_analysis or {}
        result = fraud_detection_tool(self.state.claim_id, evidence)
        self.state.fraud_detection = result
        return result

    @listen(run_fraud_detection)
    def finalize(self, _fraud: dict[str, Any]) -> dict[str, Any]:
        """Merge stage results and run escalation → decision → payout → reasoning."""
        merged = [
            self.state.policy_validation or {},
            self.state.rag_retrieval or {},
            self.state.customer_profile or {},
            self.state.evidence_analysis or {},
            self.state.fraud_detection or {},
        ]
        result = finalize_tool(self.state.claim_id, merged)
        self.state.final_result = result
        return result


def run_claim_flow(claim_id: int) -> dict[str, Any]:
    """Public entrypoint — mirrors `services.claim_pipeline.run_claim_pipeline`.

    Falls back to a synchronous ThreadPoolExecutor path when `crewai.flow` is
    not importable so the feature flag remains safe to flip without the dep.
    """
    if _CREWAI_FLOW_AVAILABLE:
        try:
            flow = ClaimFlow()
            flow.state.claim_id = claim_id
            flow.kickoff()
            return flow.state.final_result or {}
        except Exception as exc:
            logger.exception("CrewAI ClaimFlow failed for claim %s", claim_id)
            return _handle_pipeline_failure(claim_id, exc)

    # ---- Fallback path (crewai missing OR runtime unavailable) ---------
    # Runs the exact same stage graph as the CrewAI Flow but sequentially,
    # so it works in synchronous contexts (Celery workers, threading dispatch,
    # tests) without needing an asyncio event loop.
    try:
        _mark_processing(claim_id)
        progress_service.publish(
            claim_id, "claim_submitted", "completed",
            "Claim received — starting review",
        )

        policy = policy_validation_tool(claim_id)
        rag = rag_retrieval_tool(claim_id)
        customer = customer_profile_tool(claim_id)
        evidence = evidence_analysis_tool(claim_id)
        fraud = fraud_detection_tool(claim_id, evidence)

        merged = [policy, rag, customer, evidence, fraud]
        return finalize_tool(claim_id, merged)
    except Exception as exc:
        return _handle_pipeline_failure(claim_id, exc)
