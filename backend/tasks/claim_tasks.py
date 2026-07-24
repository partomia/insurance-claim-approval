import logging
from typing import Any

from celery import chord, group

from config import get_settings
from database import SessionLocal
from models.claim import Claim, ClaimStatus
from services.claim_pipeline import (
    _run_customer_profile,
    _run_evidence_analysis,
    _run_fraud_detection,
    _run_policy_validation,
    _run_rag_retrieval,
    finalize_claim,
)
from services.progress_service import progress_service
from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(name="validate_policy_task")
def validate_policy_task(claim_id: int) -> dict[str, Any]:
    return _run_policy_validation(claim_id)


@celery_app.task(name="retrieve_policy_clauses_task")
def retrieve_policy_clauses_task(claim_id: int) -> dict[str, Any]:
    return _run_rag_retrieval(claim_id)


@celery_app.task(name="analyze_customer_profile_task")
def analyze_customer_profile_task(claim_id: int) -> dict[str, Any]:
    return _run_customer_profile(claim_id)


@celery_app.task(name="analyze_evidence_task")
def analyze_evidence_task(claim_id: int) -> dict[str, Any]:
    return _run_evidence_analysis(claim_id)


@celery_app.task(name="fraud_detection_task")
def fraud_detection_task(claim_id: int) -> dict[str, Any]:
    from services.claim_pipeline import _get_claim
    from services.evidence_analysis import EvidenceAnalysisService

    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}
        service = EvidenceAnalysisService()
        result = service.analyze(db, claim)
        evidence_data = {
            "evidence_confidence_score": result.evidence_confidence_score,
            "evidence_missing": result.evidence_missing,
            "evidence_results": service.to_dict_list(result),
            "duplicate_uploads": result.duplicate_uploads,
        }
    finally:
        db.close()
    return _run_fraud_detection(claim_id, evidence_data)


@celery_app.task(name="calculate_payout_task")
def calculate_payout_task(claim_id: int) -> dict[str, Any]:
    from services.claim_pipeline import _get_claim
    from services.payout_calculation import PayoutCalculationService

    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim or not claim.policy:
            return {"payable_amount": 0.0}
        result = PayoutCalculationService().calculate(claim.policy, claim.claim_amount)
        return {"payable_amount": result.payable_amount, "breakdown": result.breakdown}
    finally:
        db.close()


@celery_app.task(name="generate_decision_task")
def generate_decision_task(claim_id: int, parallel_results: list[dict]) -> dict[str, Any]:
    return finalize_claim(claim_id, parallel_results)


@celery_app.task(name="notify_customer_task")
def notify_customer_task(claim_id: int) -> dict[str, Any]:
    from sqlalchemy.orm import joinedload

    from services.explainability import ExplainabilityService
    from services.notification import NotificationService

    db = SessionLocal()
    try:
        claim = (
            db.query(Claim)
            .options(joinedload(Claim.customer))
            .filter(Claim.id == claim_id)
            .first()
        )
        if not claim:
            return {"error": "claim not found"}
        result = NotificationService().notify_customer(db, claim, claim.status)
        ExplainabilityService().log_audit(db, claim_id, "CUSTOMER_NOTIFIED", result)
        return result
    finally:
        db.close()


@celery_app.task(name="orchestrate_claim_task")
def orchestrate_claim_task(claim_id: int) -> str:
    db = SessionLocal()
    try:
        claim = db.query(Claim).filter(Claim.id == claim_id).first()
        if claim:
            claim.status = ClaimStatus.PROCESSING
            db.commit()
    finally:
        db.close()

    progress_service.publish(claim_id, "claim_submitted", "completed", "Claim received — starting agent pipeline")

    workflow = chord(
        group(
            validate_policy_task.s(claim_id),
            retrieve_policy_clauses_task.s(claim_id),
            analyze_customer_profile_task.s(claim_id),
            analyze_evidence_task.s(claim_id),
            fraud_detection_task.s(claim_id),
        ),
        generate_decision_task.s(claim_id),
    )
    workflow.apply_async()
    return f"orchestration started for claim {claim_id}"


@celery_app.task(name="finalize_claim_task")
def finalize_claim_task(parallel_results: list[dict], claim_id: int) -> dict[str, Any]:
    return finalize_claim(claim_id, parallel_results)
