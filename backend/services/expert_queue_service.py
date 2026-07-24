"""Auto-assign completed claims to the least-loaded active policy expert."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.audit import HumanReview, HumanReviewStatus
from models.claim import Claim, ClaimStatus
from models.policy_agent import PolicyAgent
from services.explainability import ExplainabilityService

OPEN_QUEUE_STATUSES = (
    ClaimStatus.ANALYSIS_COMPLETE,
    ClaimStatus.PENDING_REVIEW,
    ClaimStatus.SUBMISSION_READY,
    ClaimStatus.REQUEST_MORE_INFO,
)

explainability = ExplainabilityService()


def assign_least_loaded_expert(db: Session, claim: Claim) -> Optional[PolicyAgent]:
    """Pick the active expert with fewest open assigned claims and assign this claim."""
    if claim.assigned_agent_id is not None:
        return None
    if claim.status not in (ClaimStatus.ANALYSIS_COMPLETE, ClaimStatus.PENDING_REVIEW):
        return None

    load_subq = (
        db.query(Claim.assigned_agent_id, func.count(Claim.id).label("open_count"))
        .filter(
            Claim.assigned_agent_id.isnot(None),
            Claim.status.in_(OPEN_QUEUE_STATUSES),
        )
        .group_by(Claim.assigned_agent_id)
        .subquery()
    )

    expert = (
        db.query(PolicyAgent)
        .outerjoin(load_subq, PolicyAgent.id == load_subq.c.assigned_agent_id)
        .filter(PolicyAgent.is_active.is_(True))
        .order_by(func.coalesce(load_subq.c.open_count, 0).asc(), PolicyAgent.id.asc())
        .first()
    )
    if not expert:
        return None

    now = datetime.utcnow()
    claim.assigned_agent_id = expert.id
    claim.assigned_agent = expert.full_name
    claim.assigned_at = now

    review = (
        db.query(HumanReview)
        .filter(HumanReview.claim_id == claim.id)
        .order_by(HumanReview.created_at.desc())
        .first()
    )
    reason = "Auto-assigned after AI analysis completed"
    if review:
        review.assigned_to = expert.full_name
        review.status = HumanReviewStatus.IN_PROGRESS
    else:
        db.add(
            HumanReview(
                claim_id=claim.id,
                reason=reason,
                assigned_to=expert.full_name,
                status=HumanReviewStatus.IN_PROGRESS,
            )
        )

    explainability.log_audit(
        db,
        claim.id,
        "CLAIM_AUTO_ASSIGNED",
        {
            "assigned_agent": expert.full_name,
            "assigned_agent_id": expert.id,
            "assigned_at": now.isoformat(),
            "expert_email": expert.email,
        },
        actor="system",
    )
    db.commit()
    db.refresh(claim)
    return expert


def backfill_unassigned_queue_claims(db: Session) -> int:
    """Assign experts to queue-eligible claims that were never auto-assigned."""
    pending = (
        db.query(Claim)
        .filter(
            Claim.assigned_agent_id.is_(None),
            Claim.status.in_((ClaimStatus.ANALYSIS_COMPLETE, ClaimStatus.PENDING_REVIEW)),
        )
        .all()
    )
    assigned = 0
    for claim in pending:
        if assign_least_loaded_expert(db, claim):
            assigned += 1
    return assigned
