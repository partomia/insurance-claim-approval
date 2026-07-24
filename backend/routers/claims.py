from datetime import datetime
import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload

import schemas
from config import get_settings
from database import get_db, SessionLocal
from dependencies import get_current_customer, get_customer_flexible
from models.claim import Claim, ClaimDocument, ClaimStatus, DocumentType
from models.customer import Customer
from models.policy import Policy
from models.platform import CustomerProfile
from services.kyc_service import is_kyc_verified
from models.policy_agent import PolicyAgent
from models.audit import HumanReview, HumanReviewStatus
from services.claim_service import ClaimService, save_upload
from services.claim_assistant_service import ClaimAssistantService
from services.analysis_service import analysis_to_dict
from services.document_serving import resolve_claim_document_path, serve_claim_document_file
from services.escalation_service import EscalationService
from services.expert_review_service import build_expert_review_summary
from services.evidence_service import EvidenceService
from services.explainability import ExplainabilityService
from services.insights_service import InsightsService
from services.orchestrator import ClaimOrchestrator
from services.policy_context_service import PolicyContextService
from services.progress_service import progress_service

router = APIRouter(prefix="/api/claims", tags=["Claims"])
settings = get_settings()
claim_service = ClaimService()
explainability = ExplainabilityService()
policy_context_service = PolicyContextService()
assistant_service = ClaimAssistantService()
insights_service = InsightsService()
evidence_service = EvidenceService()


@router.get("", response_model=list[schemas.ClaimStatusResponse])
def list_claims(
    status: str | None = Query(None),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Claim)
        .options(
            joinedload(Claim.decision),
            joinedload(Claim.policy),
            joinedload(Claim.documents),
        )
        .filter(Claim.customer_id == customer.id)
    )
    if status:
        try:
            query = query.filter(Claim.status == ClaimStatus(status.upper()))
        except ValueError:
            pass
    claims = query.order_by(Claim.updated_at.desc()).all()
    return [
        _claim_status_response(c, db, include_documents=False)
        for c in claims
    ]


def _decision_response(claim: Claim) -> Optional[schemas.ClaimDecisionResponse]:
    if not claim.decision:
        return None
    d = claim.decision
    refs = d.retrieved_clauses if isinstance(d.retrieved_clauses, list) else []
    section_refs = [
        r.get("section_ref", r) if isinstance(r, dict) else str(r) for r in refs
    ]
    analysis = analysis_to_dict(d, claim)
    return schemas.ClaimDecisionResponse(
        claim_id=claim.claim_number,
        status=d.status.value,
        payable_amount=d.payable_amount,
        fraud_score=d.fraud_score,
        confidence_score=d.confidence_score,
        retrieved_clauses=section_refs,
        reasoning=d.reasoning,
        human_review_required=d.human_review_required,
        approval_probability=analysis["approval_probability"],
        coverage_estimate=analysis["coverage_estimate"],
        expected_settlement=analysis["expected_settlement"],
        potential_problems=analysis["potential_problems"],
        recommendations=analysis["recommendations"],
        missing_documents=analysis["missing_documents"],
        policy_clause_matches=analysis["policy_clause_matches"],
        fraud_signals=analysis["fraud_signals"],
        next_best_action=analysis["next_best_action"],
        ai_explanation=analysis["ai_explanation"],
    )


def _claim_status_response(
    claim: Claim,
    db: Session | None = None,
    *,
    include_documents: bool = True,
) -> schemas.ClaimStatusResponse:
    flags = claim.escalation_flags if isinstance(claim.escalation_flags, list) else []
    messages = claim.escalation_messages if isinstance(claim.escalation_messages, list) else []
    if flags and not messages:
        messages = EscalationService().build_messages(flags, {})
    issues_raw = claim.evidence_issues if isinstance(claim.evidence_issues, list) else []
    has_document_issues = any(
        isinstance(i, dict) and not bool(i.get("acknowledged")) for i in issues_raw
    )
    evidence_issues = [
        schemas.EvidenceIssueResponse(
            field=i.get("field", ""),
            document_id=i.get("document_id", 0),
            filename=i.get("filename", ""),
            reason=i.get("reason", ""),
            issue_code=i.get("issue_code", ""),
            acknowledged=bool(i.get("acknowledged")),
        )
        for i in issues_raw
    ]
    policy = claim.policy if hasattr(claim, "policy") else None
    documents: list[schemas.ClaimDocumentSummary] = []
    if include_documents:
        for doc in sorted(claim.documents or [], key=lambda d: d.created_at):
            documents.append(
                schemas.ClaimDocumentSummary(
                    id=doc.id,
                    doc_type=doc.doc_type.value,
                    filename=doc.original_filename,
                    uploaded_at=doc.created_at,
                )
            )
    expert_review = None
    if db and claim.assigned_agent:
        summary = build_expert_review_summary(db, claim)
        if summary:
            expert_review = schemas.ExpertReviewResponse(**summary)

    return schemas.ClaimStatusResponse(
        claim_id=claim.claim_number,
        id=claim.id,
        customer_id=claim.customer_id,
        status=claim.status.value,
        claim_amount=claim.claim_amount,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
        escalation_flags=flags,
        escalation_messages=messages,
        assigned_agent=claim.assigned_agent,
        assigned_at=claim.assigned_at,
        expert_review=expert_review,
        evidence_mismatch=bool(getattr(claim, "evidence_mismatch", False)),
        evidence_issues=evidence_issues,
        pipeline_run_id=getattr(claim, "pipeline_run_id", 0) or 0,
        document_count=len(claim.documents or []),
        has_document_issues=has_document_issues,
        decision=_decision_response(claim),
        submission=schemas.ClaimSubmissionResponse(
            incident_description=claim.incident_description,
            incident_datetime=claim.incident_datetime,
            location=claim.location,
            policy_number=policy.policy_number if policy else None,
            policy_type=policy.policy_type if policy else None,
        ),
        documents=documents,
    )


def _get_owned_claim(db: Session, claim_id: int, customer_id: int) -> Claim:
    claim = db.query(Claim).filter(Claim.id == claim_id, Claim.customer_id == customer_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


def _draft_response(claim: Claim, db: Session) -> schemas.DraftClaimResponse:
    policy_number = None
    if claim.policy_id:
        policy = db.query(Policy).filter(Policy.id == claim.policy_id).first()
        policy_number = policy.policy_number if policy else None
    return schemas.DraftClaimResponse(
        claim_id=claim.claim_number,
        id=claim.id,
        status=claim.status.value,
        submission_step=claim.submission_step,
        policy_context_ready=policy_context_service.has_policy_context(claim),
        policy_number=policy_number,
    )


@router.post("/draft", response_model=schemas.DraftClaimResponse, status_code=status.HTTP_201_CREATED)
def create_draft(
    body: schemas.DraftClaimCreate,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = claim_service.create_draft(
        db=db,
        customer_id=customer.id,
        incident_description=body.incident_description,
        incident_datetime=body.incident_datetime,
        location=body.location,
        claim_amount=body.claim_amount,
    )
    return _draft_response(claim, db)


@router.patch("/{claim_id}/draft", response_model=schemas.DraftClaimResponse)
def update_draft(
    claim_id: int,
    body: schemas.DraftClaimUpdate,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = _get_owned_claim(db, claim_id, customer.id)
    policy_id = None
    if body.policy_number:
        policy = db.query(Policy).filter(Policy.policy_number == body.policy_number).first()
        if not policy:
            raise HTTPException(status_code=404, detail="Policy not found")
        if policy.customer_id != customer.id:
            raise HTTPException(status_code=403, detail="Policy not linked to your account")
        policy_id = policy.id
    claim = claim_service.update_draft(
        db,
        claim,
        incident_description=body.incident_description,
        incident_datetime=body.incident_datetime,
        location=body.location,
        claim_amount=body.claim_amount,
        policy_id=policy_id,
    )
    db.refresh(claim)
    return _draft_response(claim, db)


@router.post("/{claim_id}/policy-documents/fetch", response_model=schemas.PolicyContextResponse)
def fetch_policy_documents(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = _get_owned_claim(db, claim_id, customer.id)
    if not claim.policy_id:
        raise HTTPException(status_code=400, detail="Select a policy from your account first")
    documents = policy_context_service.fetch_from_db(db, claim)
    if not documents:
        raise HTTPException(status_code=404, detail="No policy documents found in database")
    context = policy_context_service.analyze_with_groq(db, claim, documents, source="db")
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first()
    return schemas.PolicyContextResponse(**context, policy_number=policy.policy_number if policy else None)


@router.post("/{claim_id}/policy-documents/upload", response_model=schemas.PolicyContextResponse)
async def upload_policy_documents(
    claim_id: int,
    files: list[UploadFile] = File(...),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    from services.policy_service import create_policy_from_document, save_pending_policy_upload

    claim = _get_owned_claim(db, claim_id, customer.id)
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one policy schedule file")

    upload = files[0]
    path, _checksum = await save_pending_policy_upload(upload, customer.id)
    policy, _doc, _extracted, _chunks, _rag_status = create_policy_from_document(
        db, customer.id, path, upload.filename or "schedule.pdf"
    )
    claim.policy_id = policy.id
    db.commit()
    db.refresh(claim)

    documents = policy_context_service.fetch_from_db(db, claim)
    if not documents:
        raise HTTPException(status_code=404, detail="No policy documents found after upload")
    context = policy_context_service.analyze_with_groq(db, claim, documents, source="db")
    return schemas.PolicyContextResponse(**context, policy_number=policy.policy_number)


@router.get("/{claim_id}/policy-context", response_model=schemas.PolicyContextResponse)
def get_policy_context(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = _get_owned_claim(db, claim_id, customer.id)
    ctx = claim.policy_context_json or {}
    if not ctx:
        raise HTTPException(status_code=404, detail="Policy context not yet analyzed")
    return schemas.PolicyContextResponse(**ctx)


@router.post("/{claim_id}/evidence", status_code=status.HTTP_200_OK)
async def upload_evidence(
    claim_id: int,
    proofs: list[UploadFile] = File(default=[]),
    gov_id: Optional[UploadFile] = File(default=None),
    police_report: Optional[UploadFile] = File(default=None),
    medical_bills: Optional[UploadFile] = File(default=None),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = _get_owned_claim(db, claim_id, customer.id)
    if not policy_context_service.has_policy_context(claim):
        raise HTTPException(status_code=400, detail="Complete Step 2 (policy papers) first")

    profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer.id).first()
    kyc_verified = is_kyc_verified(profile)

    if not kyc_verified and not gov_id:
        raise HTTPException(status_code=400, detail="Upload government ID or complete KYC in your profile")
    if not proofs:
        raise HTTPException(status_code=400, detail="Upload at least one supporting document")

    uploads: list[tuple[DocumentType, UploadFile]] = []
    if gov_id:
        uploads.append((DocumentType.GOV_ID, gov_id))
    for proof in proofs:
        uploads.append((DocumentType.PROOF, proof))
    if police_report:
        uploads.append((DocumentType.POLICE_REPORT, police_report))
    if medical_bills:
        uploads.append((DocumentType.MEDICAL, medical_bills))

    for doc_type, upload in uploads:
        path, checksum = await save_upload(upload, claim.id)
        claim_service.add_document(db, claim, doc_type, path, upload.filename or "file", checksum)

    claim.submission_step = max(claim.submission_step, 3)
    db.commit()
    return {"message": "Evidence uploaded", "submission_step": claim.submission_step}


@router.post("/{claim_id}/submit", response_model=schemas.ClaimSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_draft_claim(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = _get_owned_claim(db, claim_id, customer.id)
    errors = claim_service.validate_submit_gates(db, claim)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    claim = claim_service.finalize_submit(db, claim)
    claim_service.trigger_processing(claim.id)
    return schemas.ClaimSubmitResponse(
        claim_id=claim.claim_number,
        id=claim.id,
        status=claim.status.value,
        message="Claim submitted and processing started",
    )


@router.get("/{claim_id}/insights", response_model=schemas.InsightsResponse)
def get_claim_insights(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    _get_owned_claim(db, claim_id, customer.id)
    data = insights_service.build(db, claim_id)
    return schemas.InsightsResponse(**data)


@router.get("/{claim_id}/chat", response_model=list[schemas.ChatMessageResponse])
def get_chat_history(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    _get_owned_claim(db, claim_id, customer.id)
    return assistant_service.get_history(db, claim_id)


@router.post("/{claim_id}/chat", response_model=schemas.ChatMessageResponse)
def send_chat_message(
    claim_id: int,
    body: schemas.ChatMessageRequest,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = assistant_service.load_claim(db, claim_id, customer.id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    reply = assistant_service.chat(db, claim, body.message)
    return schemas.ChatMessageResponse(role="assistant", content=reply)


@router.post("/submit", response_model=schemas.ClaimSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_claim_legacy(
    policy_number: str = Form(...),
    incident_description: str = Form(...),
    incident_datetime: datetime = Form(...),
    location: str = Form(...),
    claim_amount: float = Form(...),
    proofs: list[UploadFile] = File(default=[]),
    gov_id: UploadFile = File(...),
    police_report: Optional[UploadFile] = File(default=None),
    medical_bills: Optional[UploadFile] = File(default=None),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=400,
        detail="Use the 4-step wizard at /claim: create draft, load policy papers (Step 2), upload evidence, then submit.",
    )


@router.get("/{claim_id}/stream")
async def stream_claim_progress(
    claim_id: int,
    customer: Customer = Depends(get_customer_flexible),
):
    def _load_claim():
        db = SessionLocal()
        try:
            return (
                db.query(Claim)
                .filter(Claim.id == claim_id, Claim.customer_id == customer.id)
                .first()
            )
        finally:
            db.close()

    claim = await asyncio.to_thread(_load_claim)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    async def event_generator():
        seen = 0
        idle_ticks = 0
        max_idle_ticks = 150  # ~60s without new events
        while idle_ticks < max_idle_ticks:
            history = await asyncio.to_thread(progress_service.get_history, claim_id)
            new_events = history[seen:]
            for event in new_events:
                yield f"data: {json.dumps(event)}\n\n"
                idle_ticks = 0
            if not new_events:
                idle_ticks += 1
            seen = len(history)
            if history and history[-1].get("step") == "completed":
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/{claim_id}/progress")
def get_claim_progress(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = (
        db.query(Claim)
        .filter(Claim.id == claim_id, Claim.customer_id == customer.id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return {"events": progress_service.get_history(claim_id)}


@router.post("/{claim_id}/retry-processing", status_code=status.HTTP_202_ACCEPTED)
def retry_claim_processing(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = (
        db.query(Claim)
        .options(joinedload(Claim.decision))
        .filter(Claim.id == claim_id, Claim.customer_id == customer.id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.decision and claim.status not in (ClaimStatus.PROCESSING, ClaimStatus.PENDING):
        raise HTTPException(
            status_code=400,
            detail="Claim already has a decision — retry is only for incomplete processing",
        )

    claim.status = ClaimStatus.PROCESSING
    db.commit()
    ClaimOrchestrator().dispatch(claim.id)
    return {"message": "Claim processing restarted", "claim_id": claim.claim_number}


@router.get("/{claim_id}/status", response_model=schemas.ClaimStatusResponse)
def get_claim_status(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = (
        db.query(Claim)
        .options(
            joinedload(Claim.decision),
            joinedload(Claim.policy),
            joinedload(Claim.documents),
        )
        .filter(Claim.id == claim_id, Claim.customer_id == customer.id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    return _claim_status_response(claim, db)


@router.get("/{claim_id}/documents/{document_id}/file")
def get_claim_document_file(
    claim_id: int,
    document_id: int,
    download: bool = Query(False, description="Force download instead of inline preview"),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    _get_owned_claim(db, claim_id, customer.id)
    doc = (
        db.query(ClaimDocument)
        .filter(ClaimDocument.id == document_id, ClaimDocument.claim_id == claim_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    resolved = resolve_claim_document_path(doc.file_path)
    return serve_claim_document_file(resolved, doc.original_filename, download=download)


@router.post("/{claim_id}/assign", response_model=schemas.ClaimStatusResponse)
def assign_claim_agent(
    claim_id: int,
    body: schemas.AssignAgentRequest,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    if not body.agent_id and not (body.agent_name and body.agent_name.strip()):
        raise HTTPException(status_code=400, detail="Provide agent_name or agent_id")

    claim = (
        db.query(Claim)
        .options(joinedload(Claim.decision), joinedload(Claim.human_reviews))
        .filter(Claim.id == claim_id, Claim.customer_id == customer.id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.status != ClaimStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=400,
            detail="Only claims pending human review can be assigned",
        )

    agent_label: str
    agent_id: int | None = None
    if body.agent_id is not None:
        agent = (
            db.query(PolicyAgent)
            .filter(PolicyAgent.id == body.agent_id, PolicyAgent.is_active.is_(True))
            .first()
        )
        if not agent:
            raise HTTPException(status_code=404, detail="Policy agent not found")
        agent_label = agent.full_name
        agent_id = agent.id
    else:
        agent_label = body.agent_name.strip()
        agent = (
            db.query(PolicyAgent)
            .filter(
                PolicyAgent.is_active.is_(True),
                (PolicyAgent.email == agent_label) | (PolicyAgent.full_name == agent_label),
            )
            .first()
        )
        if agent:
            agent_id = agent.id
            agent_label = agent.full_name

    now = datetime.utcnow()
    claim.assigned_agent = agent_label
    claim.assigned_agent_id = agent_id
    claim.assigned_at = now

    review = (
        db.query(HumanReview)
        .filter(HumanReview.claim_id == claim.id)
        .order_by(HumanReview.created_at.desc())
        .first()
    )
    if review:
        review.assigned_to = agent_label
        review.status = HumanReviewStatus.IN_PROGRESS
    else:
        db.add(
            HumanReview(
                claim_id=claim.id,
                reason="Manual assignment",
                assigned_to=agent_label,
                status=HumanReviewStatus.IN_PROGRESS,
            )
        )

    explainability.log_audit(
        db,
        claim.id,
        "CLAIM_ASSIGNED",
        {
            "agent_name": agent_label,
            "agent_id": agent_id,
            "assigned_at": now.isoformat(),
        },
        actor=customer.email,
    )
    progress_service.publish(
        claim.id,
        "human_review",
        "completed",
        f"Assigned to policy agent: {agent_label}",
        {"assigned_agent": agent_label, "assigned_agent_id": agent_id, "assigned_at": now.isoformat()},
    )
    db.commit()
    db.refresh(claim)
    return _claim_status_response(claim, db)


@router.post("/{claim_id}/documents", status_code=status.HTTP_202_ACCEPTED)
async def add_documents(
    claim_id: int,
    doc_type: str = Form(...),
    files: list[UploadFile] = File(...),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    claim = (
        db.query(Claim)
        .filter(Claim.id == claim_id, Claim.customer_id == customer.id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    try:
        dtype = DocumentType(doc_type.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document type") from exc

    for upload in files:
        path, checksum = await save_upload(upload, claim.id)
        claim_service.add_document(db, claim, dtype, path, upload.filename or "file", checksum)

    ClaimOrchestrator().dispatch(claim.id)
    return {"message": "Documents uploaded; evidence re-analysis triggered"}


@router.post("/{claim_id}/evidence/replace", status_code=status.HTTP_202_ACCEPTED)
async def replace_evidence(
    claim_id: int,
    file: UploadFile = File(...),
    document_id: Optional[int] = Form(None),
    doc_type: Optional[str] = Form(None),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return await evidence_service.replace_document(
        db, claim_id, customer.id, file, document_id=document_id, doc_type=doc_type
    )


@router.post("/{claim_id}/evidence/{document_id}/acknowledge")
def acknowledge_evidence(
    claim_id: int,
    document_id: int,
    body: schemas.EvidenceAcknowledgeRequest,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return evidence_service.acknowledge_document(
        db, claim_id, customer.id, document_id, note=body.note
    )


@router.post("/{claim_id}/review")
def submit_human_review(
    claim_id: int,
    review: schemas.HumanReviewSubmit,
    customer: Customer = Depends(get_current_customer),
):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Claim review is restricted to policy agents. Use the agent portal at /agent/auth.",
    )


@router.get("/{claim_id}/audit", response_model=schemas.AuditReportResponse)
def get_claim_audit(
    claim_id: int,
    customer: Customer = Depends(get_current_customer),
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
        .filter(Claim.id == claim_id, Claim.customer_id == customer.id)
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
        )
        if details
        else None,
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
        decision=decision,
        fraud_assessment=report.get("fraud_assessment"),
        evidence_results=report.get("evidence_results", []),
        retrieved_clauses=report.get("retrieved_clauses", []),
        audit_trail=report.get("audit_trail", []),
        generated_at=datetime.utcnow(),
    )
