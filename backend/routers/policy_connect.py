from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas
from database import get_db
from dependencies import get_current_customer
from models.customer import Customer
from models.platform import CustomerProfile, InsuranceProvider
from services.kyc_service import is_kyc_verified
from models.policy import Policy, PolicyDocument, PolicyDocumentSource, PolicyStatus, PremiumPayment, PremiumPaymentStatus
from services.rag_service import rag_service

router = APIRouter(prefix="/api/policies", tags=["Policy Connect"])

POLICY_SCHEDULE = {
    "Motor": [
        ("Policy Schedule", "Section 1.0", "Comprehensive motor policy for private vehicles."),
        ("Coverage Details", "Section 4.2", "Own damage, third-party liability, theft, and natural calamities covered."),
        ("Exclusions", "Section 7.1", "Driving without valid license, commercial use, and intentional damage excluded."),
        ("Settlement", "Section 3.5", "Depreciation and deductible apply. Network garage cashless repairs available."),
    ],
}


@router.get("/providers", response_model=list[schemas.InsuranceProviderResponse])
def list_providers(db: Session = Depends(get_db)):
    providers = (
        db.query(InsuranceProvider)
        .filter(InsuranceProvider.is_active.is_(True))
        .order_by(InsuranceProvider.name)
        .all()
    )
    return [
        schemas.InsuranceProviderResponse(id=p.id, name=p.name, slug=p.slug, logo_url=p.logo_url)
        for p in providers
    ]


@router.post("/connect/initiate")
def initiate_connect(
    payload: schemas.PolicyConnectInitiate,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    provider = db.query(InsuranceProvider).filter(InsuranceProvider.slug == payload.provider_slug).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Insurance provider not found")

    profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer.id).first()
    if not is_kyc_verified(profile):
        raise HTTPException(status_code=400, detail="Complete KYC before connecting a policy")

    existing = db.query(Policy).filter(Policy.policy_number == payload.policy_number).first()
    if existing and existing.customer_id != customer.id:
        raise HTTPException(status_code=409, detail="Policy already linked to another account")

    return {
        "message": "OTP sent to registered mobile",
        "provider": provider.name,
        "policy_number": payload.policy_number,
        "otp_hint": "Use 112233 for demo",
    }


@router.post("/connect/verify", response_model=schemas.PolicySummaryResponse)
def verify_connect(
    payload: schemas.PolicyConnectVerify,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    if payload.otp != "112233":
        raise HTTPException(status_code=400, detail="Invalid OTP")

    provider = db.query(InsuranceProvider).filter(InsuranceProvider.slug == payload.provider_slug).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Insurance provider not found")

    profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer.id).first()
    if not is_kyc_verified(profile):
        raise HTTPException(status_code=400, detail="Complete KYC before connecting a policy")

    policy = db.query(Policy).filter(Policy.policy_number == payload.policy_number).first()
    policy_type = payload.policy_type or _infer_policy_type(payload.policy_number)

    if not policy:
        now = datetime.utcnow()
        policy = Policy(
            policy_number=payload.policy_number,
            customer_id=customer.id,
            provider_id=provider.id,
            policy_type=policy_type,
            status=PolicyStatus.ACTIVE,
            coverage_limit=payload.sum_insured or _default_sum_insured(policy_type),
            deductible=_default_deductible(policy_type),
            co_pay_pct=_default_copay(policy_type),
            exclusions=_default_exclusions(policy_type),
            waiting_period_days=30 if policy_type == "Health" else 0,
            effective_date=now.replace(year=now.year - 1),
            expiry_date=now.replace(year=now.year + 1),
            depreciation_rate=5.0 if policy_type in ("Motor", "Auto") else 0.0,
            premium_amount=payload.annual_premium or _default_premium(policy_type),
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
        _seed_policy_documents(db, policy)
        _seed_premium_history(db, policy)
    elif policy.customer_id != customer.id:
        raise HTTPException(status_code=409, detail="Policy belongs to another customer")
    else:
        policy.provider_id = provider.id

    db.commit()
    db.refresh(policy)
    return _policy_summary(db, policy)


def _infer_policy_type(policy_number: str) -> str:
    upper = policy_number.upper()
    if "HLT" in upper or "HEALTH" in upper:
        return "Health"
    if "MTR" in upper or "MOTOR" in upper:
        return "Motor"
    if "HOME" in upper:
        return "Home"
    return "Health"


def _default_sum_insured(policy_type: str) -> float:
    return {"Health": 500000, "Motor": 800000, "Auto": 800000, "Home": 2500000}.get(policy_type, 500000)


def _default_deductible(policy_type: str) -> float:
    return {"Health": 5000, "Motor": 2000, "Auto": 2000, "Home": 10000}.get(policy_type, 5000)


def _default_copay(policy_type: str) -> float:
    return {"Health": 10.0, "Motor": 0.0, "Auto": 0.0, "Home": 0.0}.get(policy_type, 10.0)


def _default_premium(policy_type: str) -> float:
    return {"Health": 18500, "Motor": 12400, "Auto": 12400, "Home": 8200}.get(policy_type, 15000)


def _default_exclusions(policy_type: str) -> list[str]:
    return {
        "Health": ["cosmetic surgery", "experimental treatment"],
        "Motor": ["commercial use", "unlicensed driver"],
        "Auto": ["commercial use", "unlicensed driver"],
        "Home": ["flood", "earthquake"],
    }.get(policy_type, [])


def _seed_policy_documents(db: Session, policy: Policy) -> None:
    schedule = POLICY_SCHEDULE.get(policy.policy_type, POLICY_SCHEDULE["Health"])
    for title, section_ref, content in schedule:
        db.add(
            PolicyDocument(
                policy_id=policy.id,
                title=title,
                section_ref=section_ref,
                content_text=content,
                source=PolicyDocumentSource.SEED,
            )
        )
    db.commit()
    for doc in db.query(PolicyDocument).filter(PolicyDocument.policy_id == policy.id).all():
        if doc.content_text:
            rag_service.index_policy_document(
                db,
                policy.id,
                doc.content_text,
                section_ref=doc.section_ref,
                source="connect",
                filename=doc.title,
                document_id=doc.id,
            )


def _seed_premium_history(db: Session, policy: Policy) -> None:
    now = datetime.utcnow()
    for months_ago in (0, 12):
        db.add(
            PremiumPayment(
                policy_id=policy.id,
                amount=policy.premium_amount or 15000,
                paid_at=now.replace(day=1) - __import__("datetime").timedelta(days=30 * months_ago),
                status=PremiumPaymentStatus.PAID,
            )
        )
    db.commit()


def _policy_summary(db: Session, policy: Policy) -> schemas.PolicySummaryResponse:
    doc_count = db.query(PolicyDocument).filter(PolicyDocument.policy_id == policy.id).count()
    latest_payment = (
        db.query(PremiumPayment)
        .filter(PremiumPayment.policy_id == policy.id)
        .order_by(PremiumPayment.paid_at.desc())
        .first()
    )
    premium_status = latest_payment.status.value if latest_payment else "UNKNOWN"
    provider_name = policy.provider.name if policy.provider else None
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
        document_count=doc_count,
        provider_name=provider_name,
        premium_amount=policy.premium_amount,
        coverage_remaining=max(0, policy.coverage_limit - _claimed_amount(db, policy.id)),
    )


def _claimed_amount(db: Session, policy_id: int) -> float:
    from models.claim import Claim, ClaimStatus

    claims = (
        db.query(Claim)
        .filter(Claim.policy_id == policy_id, Claim.status != ClaimStatus.DRAFT)
        .all()
    )
    return sum(c.claim_amount for c in claims)
