from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

import schemas
from database import get_db
from dependencies import get_current_agent
from models.audit import HumanReview, HumanReviewStatus
from models.claim import Claim, ClaimDocument, ClaimStatus
from models.policy_agent import PolicyAgent
from routers.claims import _claim_status_response, _decision_response
from services.agent_service import agent_service
from services.expert_queue_service import backfill_unassigned_queue_claims
from services.document_serving import resolve_claim_document_path, serve_claim_document_file
from services.document_request_service import STANDARD_DOCUMENT_TYPES, normalize_requested_documents
from services.explainability import ExplainabilityService
from services.insights_service import InsightsService

router = APIRouter(prefix="/api/agent", tags=["Agent Portal"])
insights_service = InsightsService()
explainability = ExplainabilityService()


@router.get("/dashboard/stats", response_model=schemas.AgentDashboardStatsResponse)
def agent_dashboard_stats(
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    backfill_unassigned_queue_claims(db)
    return agent_service.get_dashboard_stats(db, agent)


@router.get("/claims", response_model=list[schemas.AgentClaimListItem])
def agent_list_claims(
    status: str | None = Query(None),
    customer_id: int | None = Query(None),
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    backfill_unassigned_queue_claims(db)
    return agent_service.list_claims(db, agent, status=status, customer_id=customer_id)


@router.get("/customers", response_model=list[schemas.AgentCustomerSummary])
def agent_list_customers(
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    return agent_service.list_customers(db, agent)


@router.get("/customers/{customer_id}", response_model=schemas.AgentCustomerDetail)
def agent_customer_detail(
    customer_id: int,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    detail = agent_service.get_customer_detail(db, agent, customer_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Customer not found or not assigned to you")
    return detail


@router.get("/customers/{customer_id}/insights", response_model=schemas.DashboardStatsResponse)
def agent_customer_insights(
    customer_id: int,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    data = agent_service.get_customer_insights(db, agent, customer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Customer not found or not assigned to you")
    return schemas.DashboardStatsResponse(**data)


@router.get("/claims/{claim_id}", response_model=schemas.ClaimStatusResponse)
def agent_get_claim(
    claim_id: int,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    claim = agent_service.get_assigned_claim(db, agent, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found or not assigned to you")
    return _claim_status_response(claim)


@router.get("/claims/{claim_id}/documents", response_model=list[schemas.AgentClaimDocumentSummary])
def agent_list_claim_documents(
    claim_id: int,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    claim = (
        agent_service._assigned_query(db, agent.id)
        .options(joinedload(Claim.documents))
        .filter_by(id=claim_id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found or not assigned to you")
    return [schemas.AgentClaimDocumentSummary(**d) for d in agent_service.list_claim_documents(claim)]


@router.get("/claims/{claim_id}/documents/{document_id}/file")
def agent_get_claim_document_file(
    claim_id: int,
    document_id: int,
    download: bool = Query(False),
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    claim = agent_service.get_assigned_claim(db, agent, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found or not assigned to you")
    doc = (
        db.query(ClaimDocument)
        .filter(ClaimDocument.id == document_id, ClaimDocument.claim_id == claim_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    resolved = resolve_claim_document_path(doc.file_path)
    return serve_claim_document_file(resolved, doc.original_filename, download=download)


@router.get("/claims/{claim_id}/policy-requirements", response_model=schemas.AgentPolicyRequirementsResponse)
def agent_claim_policy_requirements(
    claim_id: int,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    claim = (
        agent_service._assigned_query(db, agent.id)
        .options(joinedload(Claim.policy), joinedload(Claim.decision))
        .filter_by(id=claim_id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found or not assigned to you")
    return schemas.AgentPolicyRequirementsResponse(**agent_service.build_policy_requirements(claim))


@router.get("/claims/{claim_id}/insights", response_model=schemas.InsightsResponse)
def agent_claim_insights(
    claim_id: int,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    claim = agent_service.get_assigned_claim(db, agent, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found or not assigned to you")
    data = insights_service.build(db, claim_id)
    return schemas.InsightsResponse(**data)


@router.get("/claims/{claim_id}/audit", response_model=schemas.AuditReportResponse)
def agent_claim_audit(
    claim_id: int,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    claim = (
        agent_service._assigned_query(db, agent.id)
        .options(
            joinedload(Claim.decision),
            joinedload(Claim.fraud_assessment),
            joinedload(Claim.audit_logs),
            joinedload(Claim.documents),
            joinedload(Claim.customer),
            joinedload(Claim.policy),
        )
        .filter_by(id=claim_id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found or not assigned to you")
    report = explainability.build_audit_report(db, claim)
    decision = _decision_response(claim)
    details = report.get("claim_details") or {}
    issues_raw = report.get("evidence_issues", [])
    return schemas.AuditReportResponse(
        claim_id=report["claim_id"],
        claim_number=report["claim_number"],
        status=report["status"],
        claim_details=schemas.ClaimDetailsSummary(
            incident_description=details.get("incident_description", ""),
            incident_datetime=details.get("incident_datetime"),
            location=details.get("location", ""),
            claim_amount=details.get("claim_amount", 0),
            customer_name=details.get("customer_name", ""),
            policy_number=details.get("policy_number"),
            policy_type=details.get("policy_type"),
        ),
        documents=[
            schemas.ClaimDocumentSummary(
                id=d["id"],
                doc_type=d["doc_type"],
                filename=d["filename"],
                uploaded_at=d["uploaded_at"],
            )
            for d in report.get("documents", [])
        ],
        escalation_flags=report.get("escalation_flags", []),
        escalation_messages=report.get("escalation_messages", []),
        decision=decision,
        fraud_assessment=report.get("fraud_assessment"),
        evidence_results=report.get("evidence_results", []),
        retrieved_clauses=report.get("retrieved_clauses", []),
        evidence_issues=[
            schemas.EvidenceIssueResponse(
                field=i.get("field", ""),
                document_id=i.get("document_id", 0),
                filename=i.get("filename", ""),
                reason=i.get("reason", ""),
                issue_code=i.get("issue_code", ""),
                acknowledged=bool(i.get("acknowledged")),
            )
            for i in issues_raw
        ],
        audit_trail=report.get("audit_trail", []),
        generated_at=datetime.utcnow(),
    )


@router.get("/document-types")
def agent_document_types(_agent: PolicyAgent = Depends(get_current_agent)):
    return {"document_types": STANDARD_DOCUMENT_TYPES}


@router.post("/claims/{claim_id}/consult")
def agent_submit_consultation(
    claim_id: int,
    review: schemas.HumanReviewSubmit,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    claim = agent_service.get_assigned_claim(db, agent, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found or not assigned to you")
    if claim.status not in (
        ClaimStatus.ANALYSIS_COMPLETE,
        ClaimStatus.PENDING_REVIEW,
        ClaimStatus.REQUEST_MORE_INFO,
        ClaimStatus.HUMAN_REVIEW,
    ):
        raise HTTPException(status_code=400, detail="Claim is not in expert review state")

    action = review.action.upper()
    status_map = {
        "SUBMISSION_READY": ClaimStatus.SUBMISSION_READY,
        "NEEDS_IMPROVEMENT": ClaimStatus.REQUEST_MORE_INFO,
        "CONTINUE_REVIEW": ClaimStatus.PENDING_REVIEW,
    }
    new_status = status_map.get(action)
    if not new_status:
        raise HTTPException(
            status_code=400,
            detail="Action must be SUBMISSION_READY, NEEDS_IMPROVEMENT, or CONTINUE_REVIEW",
        )

    requested_documents = normalize_requested_documents(review.requested_documents)
    if action == "NEEDS_IMPROVEMENT" and not requested_documents:
        raise HTTPException(
            status_code=400,
            detail="Select at least one document type the customer must upload",
        )

    claim.status = new_status
    if claim.decision:
        claim.decision.human_review_required = new_status != ClaimStatus.SUBMISSION_READY
        if review.reviewer_notes:
            claim.decision.recommendations = list(claim.decision.recommendations or []) + [review.reviewer_notes]
        if new_status == ClaimStatus.SUBMISSION_READY:
            claim.decision.next_best_action = "Submit to insurance company"
        if action == "NEEDS_IMPROVEMENT":
            claim.decision.missing_documents = [item["label"] for item in requested_documents]

    human_review = (
        db.query(HumanReview)
        .filter(HumanReview.claim_id == claim.id)
        .order_by(HumanReview.created_at.desc())
        .first()
    )
    if human_review:
        human_review.status = HumanReviewStatus.COMPLETED if new_status == ClaimStatus.SUBMISSION_READY else HumanReviewStatus.IN_PROGRESS
        human_review.reviewer_notes = review.reviewer_notes
        human_review.decision_override = new_status
        human_review.assigned_to = agent.full_name

    requested_keys = [item["id"] for item in requested_documents]

    explainability.log_audit(
        db,
        claim.id,
        "EXPERT_CONSULTATION",
        {
            "action": action,
            "notes": review.reviewer_notes,
            "checklist": review.checklist,
            "internal_notes": review.internal_notes,
            "requested_documents": requested_keys,
            "expert": agent.email,
        },
        actor=agent.email,
    )
    db.commit()
    return {"claim_id": claim.claim_number, "status": new_status.value, "action": action}


@router.post("/claims/{claim_id}/submit-to-insurer")
def agent_submit_to_insurer(
    claim_id: int,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    claim = agent_service.get_assigned_claim(db, agent, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found or not assigned to you")
    if claim.status != ClaimStatus.SUBMISSION_READY:
        raise HTTPException(status_code=400, detail="Claim must be submission-ready")

    claim.status = ClaimStatus.SUBMITTED_TO_INSURER
    explainability.log_audit(
        db,
        claim.id,
        "SUBMITTED_TO_INSURER",
        {"expert": agent.email},
        actor=agent.email,
    )
    db.commit()
    return {"claim_id": claim.claim_number, "status": claim.status.value}


@router.post("/claims/{claim_id}/review")
def agent_submit_review(
    claim_id: int,
    review: schemas.HumanReviewSubmit,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Legacy endpoint — redirects to consultation workflow."""
    return agent_submit_consultation(claim_id, review, agent, db)
