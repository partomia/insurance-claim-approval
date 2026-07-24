from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

import schemas
from database import get_db
from dependencies import get_current_customer
from models.customer import Customer
from models.policy import Policy, PremiumPayment, PremiumPaymentStatus
from services.policy_context_service import PolicyContextService
from services.policy_service import (
    create_policy,
    create_policy_from_document,
    delete_policy_if_allowed,
    document_count,
    ingest_policy_document,
    save_pending_policy_upload,
    save_policy_upload,
)
from services.rag_service import rag_service

router = APIRouter(prefix="/api/policies", tags=["Policies"])
policy_context_service = PolicyContextService()


def _policy_summary(policy: Policy, db: Session) -> schemas.PolicySummaryResponse:
    latest_payment = (
        db.query(PremiumPayment)
        .filter(PremiumPayment.policy_id == policy.id)
        .order_by(PremiumPayment.paid_at.desc())
        .first()
    )
    premium_status = latest_payment.status.value if latest_payment else PremiumPaymentStatus.PAID.value
    return schemas.PolicySummaryResponse(
        id=policy.id,
        policy_number=policy.policy_number,
        policy_type=policy.policy_type,
        status=policy.status.value,
        coverage_limit=policy.coverage_limit,
        deductible=policy.deductible,
        co_pay_pct=policy.co_pay_pct,
        exclusions=policy.exclusions or [],
        premium_status=premium_status,
        effective_date=policy.effective_date,
        expiry_date=policy.expiry_date,
        document_count=document_count(db, policy.id),
    )


def _policy_from_document_response(
    policy: Policy,
    db: Session,
    extracted: dict,
    chunks: int,
    rag_status: str,
) -> schemas.PolicyFromDocumentResponse:
    summary = _policy_summary(policy, db)
    return schemas.PolicyFromDocumentResponse(
        **summary.model_dump(),
        rag_chunks_indexed=chunks,
        rag_status=rag_status,
        extracted_fields=extracted,
    )


def _get_owned_policy(db: Session, policy_number: str, customer_id: int) -> Policy:
    policy = db.query(Policy).filter(Policy.policy_number == policy_number).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    if policy.customer_id != customer_id:
        raise HTTPException(status_code=403, detail="Policy not linked to your account")
    return policy


@router.get("/me", response_model=list[schemas.PolicySummaryResponse])
def list_my_policies(
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    policies = db.query(Policy).filter(Policy.customer_id == customer.id).order_by(Policy.id.desc()).all()
    return [_policy_summary(p, db) for p in policies]


@router.post("/from-document", response_model=schemas.PolicyFromDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_policy_from_document_upload(
    file: UploadFile = File(...),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    path, _checksum = await save_pending_policy_upload(file, customer.id)
    policy, _doc, extracted, chunks, rag_status = create_policy_from_document(
        db, customer.id, path, file.filename or "schedule.pdf"
    )
    return _policy_from_document_response(policy, db, extracted, chunks, rag_status)


@router.post("", response_model=schemas.PolicySummaryResponse, status_code=status.HTTP_201_CREATED)
def create_my_policy(
    body: schemas.PolicyCreateRequest,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    policy = create_policy(
        db=db,
        customer_id=customer.id,
        policy_type=body.policy_type,
        coverage_limit=body.coverage_limit,
        deductible=body.deductible,
        co_pay_pct=body.co_pay_pct,
        exclusions=body.exclusions,
    )
    return _policy_summary(policy, db)


@router.get("/{policy_number}/summary", response_model=schemas.PolicySummaryResponse)
def get_policy_summary(
    policy_number: str,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    policy = _get_owned_policy(db, policy_number, customer.id)
    return _policy_summary(policy, db)


@router.get("/{policy_number}/documents", response_model=list[schemas.PolicyDocumentItem])
def list_policy_documents(
    policy_number: str,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    policy = _get_owned_policy(db, policy_number, customer.id)
    return policy_context_service.list_policy_documents(db, policy.id)


@router.post("/{policy_number}/documents", status_code=status.HTTP_201_CREATED)
async def upload_policy_document(
    policy_number: str,
    file: UploadFile = File(...),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    policy = _get_owned_policy(db, policy_number, customer.id)
    path, _checksum = await save_policy_upload(file, policy_number)
    doc, chunks, rag_status = ingest_policy_document(db, policy, path, file.filename or "schedule.pdf")
    return {
        "message": "Policy schedule uploaded",
        "document_id": doc.id,
        "document_count": document_count(db, policy.id),
        "rag_chunks_indexed": chunks,
        "rag_status": rag_status,
    }


@router.get("/{policy_number}/rag-status", response_model=schemas.PolicyRagStatusResponse)
def get_policy_rag_status(
    policy_number: str,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    policy = _get_owned_policy(db, policy_number, customer.id)
    return schemas.PolicyRagStatusResponse(
        policy_number=policy.policy_number,
        policy_id=policy.id,
        rag_chunks_indexed=rag_service.count_for_policy(policy.id),
        chroma_total=rag_service.count(),
    )


@router.delete("/{policy_number}", status_code=status.HTTP_200_OK)
def delete_my_policy(
    policy_number: str,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    policy = _get_owned_policy(db, policy_number, customer.id)
    try:
        delete_policy_if_allowed(db, policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Policy deleted"}
