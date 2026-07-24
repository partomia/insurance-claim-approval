"""Customer-facing expert review summaries from HumanReview + consultation audit events."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models.audit import AuditLog, HumanReview
from models.claim import Claim, ClaimStatus
from services.document_request_service import build_requested_document_items

ACTION_LABELS = {
    "NEEDS_IMPROVEMENT": "Documents or details needed",
    "SUBMISSION_READY": "Ready for insurer submission",
    "CONTINUE_REVIEW": "Review in progress",
}


def build_expert_review_summary(db: Session, claim: Claim) -> Optional[dict]:
    if not claim.assigned_agent:
        return None

    review = (
        db.query(HumanReview)
        .filter(HumanReview.claim_id == claim.id)
        .order_by(HumanReview.updated_at.desc())
        .first()
    )
    consultation = (
        db.query(AuditLog)
        .filter(AuditLog.claim_id == claim.id, AuditLog.event_type == "EXPERT_CONSULTATION")
        .order_by(AuditLog.timestamp.desc())
        .first()
    )

    message: str | None = None
    action: str | None = None
    updated_at: datetime | None = claim.assigned_at
    requested_raw: list[str] = []

    if review and review.reviewer_notes and review.reviewer_notes.strip():
        message = review.reviewer_notes.strip()
        if review.decision_override:
            action = _action_from_status(review.decision_override)
        updated_at = review.updated_at
    elif consultation and isinstance(consultation.payload, dict):
        notes = (consultation.payload.get("notes") or "").strip()
        if notes:
            message = notes
            action = consultation.payload.get("action")
            updated_at = consultation.timestamp

    if consultation and isinstance(consultation.payload, dict):
        raw = consultation.payload.get("requested_documents")
        if isinstance(raw, list):
            requested_raw = [str(x) for x in raw if str(x).strip()]
        if not requested_raw and claim.decision and claim.decision.missing_documents:
            requested_raw = list(claim.decision.missing_documents or [])

    if not message:
        message = (
            f"Hi — I'm {claim.assigned_agent}, your Claim Expert. "
            "I'm reviewing your submission and documents. I'll post updates here as my review progresses."
        )

    action_label = ACTION_LABELS.get(action or "", "Expert review update")
    if claim.status == ClaimStatus.REQUEST_MORE_INFO and not action:
        action = "NEEDS_IMPROVEMENT"
        action_label = ACTION_LABELS["NEEDS_IMPROVEMENT"]

    request_after = updated_at if action == "NEEDS_IMPROVEMENT" else None
    requested_documents = build_requested_document_items(
        requested_raw,
        claim.documents or [],
        requested_after=request_after,
    )

    return {
        "expert_name": claim.assigned_agent,
        "message": message,
        "action": action,
        "action_label": action_label,
        "updated_at": updated_at,
        "requested_documents": requested_documents,
    }


def _action_from_status(status: ClaimStatus) -> str | None:
    mapping = {
        ClaimStatus.SUBMISSION_READY: "SUBMISSION_READY",
        ClaimStatus.REQUEST_MORE_INFO: "NEEDS_IMPROVEMENT",
        ClaimStatus.PENDING_REVIEW: "CONTINUE_REVIEW",
        ClaimStatus.HUMAN_REVIEW: "CONTINUE_REVIEW",
    }
    return mapping.get(status)
