import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from models.policy import Policy, PolicyDocument, PolicyDocumentSource, PolicyStatus, PremiumPayment, PremiumPaymentStatus
from rag.chroma_store import extract_section_ref
from services.policy_context_service import PolicyContextService

from services.llm_service import llm_service
from services.rag_service import rag_service

_policy_context = PolicyContextService()

_VALID_POLICY_TYPES = {"Auto", "Health", "Home"}


def _parse_date(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").split("T")[0])
    except ValueError:
        return default


def _unique_policy_number(db: Session, candidate: str | None) -> str:
    if candidate:
        normalized = str(candidate).strip().upper()
        if normalized and not db.query(Policy).filter(Policy.policy_number == normalized).first():
            return normalized
    return f"POL-{uuid.uuid4().hex[:8].upper()}"


def create_policy(
    db: Session,
    customer_id: int,
    policy_type: str,
    coverage_limit: float,
    deductible: float = 500.0,
    co_pay_pct: float = 10.0,
    exclusions: list[str] | None = None,
    policy_number: str | None = None,
    effective_date: datetime | None = None,
    expiry_date: datetime | None = None,
) -> Policy:
    now = datetime.utcnow()
    resolved_number = _unique_policy_number(db, policy_number)
    policy = Policy(
        policy_number=resolved_number,
        customer_id=customer_id,
        policy_type=policy_type if policy_type in _VALID_POLICY_TYPES else "Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=coverage_limit,
        deductible=deductible,
        co_pay_pct=co_pay_pct,
        exclusions=exclusions or [],
        waiting_period_days=0,
        effective_date=effective_date or (now - timedelta(days=365)),
        expiry_date=expiry_date or (now + timedelta(days=365)),
        depreciation_rate=5.0,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)

    payment = PremiumPayment(
        policy_id=policy.id,
        amount=1200.0,
        paid_at=now - timedelta(days=30),
        status=PremiumPaymentStatus.PAID,
    )
    db.add(payment)
    db.commit()
    return policy


def ingest_policy_document(
    db: Session,
    policy: Policy,
    file_path: str,
    filename: str,
) -> tuple[PolicyDocument, int, str]:
    ocr_text = _policy_context._ocr_file(file_path)
    content = ocr_text or f"Uploaded policy schedule: {filename}"
    primary_section = extract_section_ref(content) or "Policy Schedule"
    content_stored = content[:10000]
    existing = (
        db.query(PolicyDocument)
        .filter(PolicyDocument.policy_id == policy.id)
        .order_by(PolicyDocument.id.desc())
        .first()
    )
    content_unchanged = existing is not None and existing.content_text == content_stored
    if existing:
        existing.title = f"Schedule — {filename}"
        existing.section_ref = primary_section
        existing.content_text = content_stored
        existing.file_path = file_path
        doc = existing
    else:
        doc = PolicyDocument(
            policy_id=policy.id,
            title=f"Schedule — {filename}",
            section_ref=primary_section,
            content_text=content_stored,
            file_path=file_path,
            source=PolicyDocumentSource.UPLOAD,
        )
        db.add(doc)
    db.commit()
    db.refresh(doc)
    if content_unchanged:
        return doc, 0, "skipped_duplicate"
    chunks = rag_service.index_policy_document(
        db,
        policy.id,
        content,
        section_ref=primary_section,
        source="upload",
        filename=filename,
        document_id=doc.id,
    )
    return doc, chunks, "indexed"


def create_policy_from_document(
    db: Session,
    customer_id: int,
    file_path: str,
    filename: str,
) -> tuple[Policy, PolicyDocument, dict, int, str]:
    text = _policy_context._extract_text_from_file(file_path)
    extracted = llm_service.extract_policy_profile(text) if text else {}

    policy_type = str(extracted.get("policy_type") or "Auto")
    if policy_type not in _VALID_POLICY_TYPES:
        policy_type = "Auto"

    coverage_limit = float(extracted.get("coverage_limit") or 500_000)
    deductible = float(extracted.get("deductible") or 500)
    co_pay_pct = float(extracted.get("co_pay_pct") or 10)
    exclusions = extracted.get("exclusions") if isinstance(extracted.get("exclusions"), list) else []
    now = datetime.utcnow()

    policy = create_policy(
        db=db,
        customer_id=customer_id,
        policy_type=policy_type,
        coverage_limit=coverage_limit,
        deductible=deductible,
        co_pay_pct=co_pay_pct,
        exclusions=exclusions,
        policy_number=extracted.get("policy_number"),
        effective_date=_parse_date(extracted.get("effective_date"), now - timedelta(days=365)),
        expiry_date=_parse_date(extracted.get("expiry_date"), now + timedelta(days=365)),
    )
    doc, chunks, rag_status = ingest_policy_document(db, policy, file_path, filename)
    return policy, doc, extracted, chunks, rag_status


def document_count(db: Session, policy_id: int) -> int:
    return db.query(PolicyDocument).filter(PolicyDocument.policy_id == policy_id).count()


def delete_policy_if_allowed(db: Session, policy: Policy) -> None:
    from models.claim import Claim, ClaimStatus

    active = (
        db.query(Claim)
        .filter(
            Claim.policy_id == policy.id,
            Claim.status.notin_([ClaimStatus.DRAFT]),
        )
        .first()
    )
    if active:
        raise ValueError("Cannot delete policy with submitted claims")
    rag_service.delete_policy_vectors(policy.id)
    db.query(PolicyDocument).filter(PolicyDocument.policy_id == policy.id).delete()
    db.query(PremiumPayment).filter(PremiumPayment.policy_id == policy.id).delete()
    db.delete(policy)
    db.commit()


async def save_pending_policy_upload(file, customer_id: int) -> tuple[str, str]:
    import hashlib
    import aiofiles
    from config import get_settings

    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / "policies" / "pending" / str(customer_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file.filename or "schedule.pdf"
    dest = upload_dir / safe_name
    content = await file.read()
    async with aiofiles.open(dest, "wb") as out:
        await out.write(content)
    checksum = hashlib.sha256(content).hexdigest()
    return str(dest), checksum


async def save_policy_upload(file, policy_number: str) -> tuple[str, str]:
    import hashlib
    import aiofiles
    from config import get_settings

    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / "policies" / policy_number
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file.filename or "schedule.pdf"
    dest = upload_dir / safe_name
    content = await file.read()
    async with aiofiles.open(dest, "wb") as out:
        await out.write(content)
    checksum = hashlib.sha256(content).hexdigest()
    return str(dest), checksum
