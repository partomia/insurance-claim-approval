from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

import schemas
from database import get_db
from dependencies import get_current_insurer
from models.audit import HumanReview, HumanReviewStatus
from models.claim import Claim, ClaimDocument, ClaimStatus
from models.insurer_user import InsurerUser
from routers.claims import _claim_status_response, _decision_response
from services.document_serving import resolve_claim_document_path, serve_claim_document_file
from services.explainability import ExplainabilityService
from services.insights_service import InsightsService
from services.insurer_service import insurer_service
from services.notification import NotificationService
from services.policy_risk_service import policy_risk_service

router = APIRouter(prefix="/api/insurer", tags=["Insurer Portal"])
insights_service = InsightsService()
explainability = ExplainabilityService()
notification_service = NotificationService()


@router.get("/dashboard/stats", response_model=schemas.InsurerDashboardStatsResponse)
def insurer_dashboard_stats(
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    return insurer_service.get_dashboard_stats(db)


@router.get("/book-of-business", response_model=list[schemas.BookOfBusinessPolicyItem])
def insurer_book_of_business(
    risk_band: str | None = Query(None, description="Filter to LOW, MEDIUM, or HIGH"),
    min_score: float | None = Query(None, ge=0, le=100),
    high_risk_garage_only: bool = Query(False),
    sort: str = Query("score_desc", description="score_desc | score_asc | claims_desc"),
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    """Lakehouse-ingested policies with their CDE-computed fraud risk signal.

    Only includes policies with a matching PolicyRiskSignal row (i.e. those
    ingested by scripts/ingest_lakehouse.py) — the seed.py demo policies
    (POL-MTR-*) never appear here since they have no lakehouse counterpart.
    """
    return policy_risk_service.list_policies(
        db,
        risk_band=risk_band,
        min_score=min_score,
        high_risk_garage_only=high_risk_garage_only,
        sort=sort,
    )


@router.get("/book-of-business/stats", response_model=schemas.BookOfBusinessStatsResponse)
def insurer_book_of_business_stats(
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    return policy_risk_service.get_stats(db)


@router.get("/claims", response_model=list[schemas.InsurerClaimListItem])
def insurer_list_claims(
    status: str | None = Query(None),
    all_statuses: bool = Query(False, description="When true, list all insurer-visible claims"),
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    if all_statuses or status == "":
        items = insurer_service.list_all_claims(db, status=status or None)
    elif status is None:
        items = insurer_service.list_claims(db)
    else:
        items = insurer_service.list_all_claims(db, status=status)
    return items


@router.get("/claims/{claim_id}", response_model=schemas.ClaimStatusResponse)
def insurer_get_claim(
    claim_id: int,
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    claim = insurer_service.get_claim(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return _claim_status_response(claim, db)


@router.get("/claims/{claim_id}/documents", response_model=list[schemas.AgentClaimDocumentSummary])
def insurer_list_claim_documents(
    claim_id: int,
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    claim = insurer_service.get_claim(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return [schemas.AgentClaimDocumentSummary(**d) for d in insurer_service.list_claim_documents(claim)]


@router.get("/claims/{claim_id}/documents/{document_id}/file")
def insurer_get_claim_document_file(
    claim_id: int,
    document_id: int,
    download: bool = Query(False),
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    claim = insurer_service.get_claim(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
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
def insurer_claim_policy_requirements(
    claim_id: int,
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    claim = insurer_service.get_claim(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return schemas.AgentPolicyRequirementsResponse(**insurer_service.build_policy_requirements(claim))


@router.get("/claims/{claim_id}/insights", response_model=schemas.InsightsResponse)
def insurer_claim_insights(
    claim_id: int,
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    claim = insurer_service.get_claim(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    data = insights_service.build(db, claim_id)
    return schemas.InsightsResponse(**data)


@router.get("/claims/{claim_id}/audit", response_model=schemas.AuditReportResponse)
def insurer_claim_audit(
    claim_id: int,
    _insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    claim = (
        db.query(Claim)
        .options(
            joinedload(Claim.decision),
            joinedload(Claim.fraud_assessment),
            joinedload(Claim.audit_logs),
            joinedload(Claim.documents),
            joinedload(Claim.customer),
            joinedload(Claim.policy),
        )
        .filter(
            Claim.id == claim_id,
            Claim.status.in_(insurer_service.INSURER_VISIBLE_STATUSES),
        )
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
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


@router.post("/claims/{claim_id}/decision")
def insurer_submit_decision(
    claim_id: int,
    body: schemas.InsurerDecisionSubmit,
    insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    claim = (
        db.query(Claim)
        .options(
            joinedload(Claim.decision),
            joinedload(Claim.customer),
            joinedload(Claim.policy),
        )
        .filter(Claim.id == claim_id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.status != ClaimStatus.SUBMITTED_TO_INSURER:
        raise HTTPException(
            status_code=400,
            detail="Only claims submitted to the insurer can be approved or rejected",
        )

    action = body.action.upper()
    if action not in ("APPROVED", "REJECTED"):
        raise HTTPException(status_code=400, detail="Action must be APPROVED or REJECTED")

    new_status = ClaimStatus.APPROVED if action == "APPROVED" else ClaimStatus.REJECTED
    claim.status = new_status

    if claim.decision:
        claim.decision.status = new_status
        if action == "APPROVED":
            payable = body.payable_amount
            if payable is None:
                payable = claim.decision.expected_settlement or claim.decision.payable_amount or claim.claim_amount
            claim.decision.payable_amount = float(payable)
            claim.decision.next_best_action = "Claim approved by insurer"
        else:
            claim.decision.payable_amount = 0.0
            claim.decision.next_best_action = "Claim rejected by insurer"
        if body.notes:
            claim.decision.reasoning = body.notes

    human_review = (
        db.query(HumanReview)
        .filter(HumanReview.claim_id == claim.id)
        .order_by(HumanReview.created_at.desc())
        .first()
    )
    if human_review:
        human_review.status = HumanReviewStatus.COMPLETED
        human_review.reviewer_notes = body.notes
        human_review.decision_override = new_status
        human_review.assigned_to = insurer.full_name
    else:
        db.add(
            HumanReview(
                claim_id=claim.id,
                reason=f"Insurer decision: {action.lower()}",
                assigned_to=insurer.full_name,
                status=HumanReviewStatus.COMPLETED,
                reviewer_notes=body.notes,
                decision_override=new_status,
            )
        )

    event_type = "INSURER_APPROVED" if action == "APPROVED" else "INSURER_REJECTED"
    explainability.log_audit(
        db,
        claim.id,
        event_type,
        {
            "notes": body.notes,
            "payable_amount": claim.decision.payable_amount if claim.decision else 0,
            "insurer": insurer.email,
        },
        actor=insurer.email,
    )
    db.commit()
    notification_service.notify_customer(db, claim, new_status)
    return {
        "claim_id": claim.claim_number,
        "status": new_status.value,
        "action": action,
    }
