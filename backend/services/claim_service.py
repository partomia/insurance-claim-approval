import hashlib
import uuid
from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import UploadFile
from sqlalchemy.orm import Session

from config import get_settings
from models.claim import Claim, ClaimDocument, ClaimStatus, DocumentType
from models.platform import CustomerProfile
from services.kyc_service import is_kyc_verified
from services.kyc_service import is_kyc_verified
from services.explainability import ExplainabilityService
from services.orchestrator import ClaimOrchestrator
from services.policy_context_service import PolicyContextService

settings = get_settings()


def generate_claim_number() -> str:
    return f"CLM{uuid.uuid4().hex[:8].upper()}"


async def save_upload(file: UploadFile, claim_id: int) -> tuple[str, str]:
    upload_dir = Path(settings.upload_dir) / str(claim_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file.filename or "upload"
    dest = upload_dir / safe_name
    content = await file.read()
    async with aiofiles.open(dest, "wb") as out:
        await out.write(content)
    checksum = hashlib.sha256(content).hexdigest()
    return str(dest), checksum


class ClaimService:
    def __init__(self) -> None:
        self.orchestrator = ClaimOrchestrator()
        self.explainability = ExplainabilityService()
        self.policy_context = PolicyContextService()

    def create_draft(
        self,
        db: Session,
        customer_id: int,
        incident_description: str,
        incident_datetime: datetime,
        location: str,
        claim_amount: float,
        policy_id: int | None = None,
        motor_fields: dict | None = None,
    ) -> Claim:
        motor_fields = motor_fields or {}
        claim = Claim(
            claim_number=generate_claim_number(),
            customer_id=customer_id,
            policy_id=policy_id,
            incident_description=incident_description,
            incident_datetime=incident_datetime,
            location=location,
            claim_amount=claim_amount,
            status=ClaimStatus.DRAFT,
            submission_step=1,
            policy_context_json={},
            **{k: v for k, v in motor_fields.items() if v is not None},
        )
        db.add(claim)
        db.commit()
        db.refresh(claim)
        self.explainability.log_audit(
            db, claim.id, "DRAFT_CREATED", {"claim_number": claim.claim_number}, actor=f"customer:{customer_id}"
        )
        return claim

    def update_draft(
        self,
        db: Session,
        claim: Claim,
        incident_description: str | None = None,
        incident_datetime: datetime | None = None,
        location: str | None = None,
        claim_amount: float | None = None,
        policy_id: int | None = None,
        motor_fields: dict | None = None,
    ) -> Claim:
        if incident_description is not None:
            claim.incident_description = incident_description
        if incident_datetime is not None:
            claim.incident_datetime = incident_datetime
        if location is not None:
            claim.location = location
        if claim_amount is not None:
            claim.claim_amount = claim_amount
        if policy_id is not None:
            claim.policy_id = policy_id
        for key, value in (motor_fields or {}).items():
            if value is not None:
                setattr(claim, key, value)
        claim.submission_step = max(claim.submission_step, 1)
        db.commit()
        db.refresh(claim)
        return claim

    def create_claim(
        self,
        db: Session,
        customer_id: int,
        policy_id: int,
        incident_description: str,
        incident_datetime: datetime,
        location: str,
        claim_amount: float,
    ) -> Claim:
        return self.create_draft(
            db,
            customer_id,
            incident_description,
            incident_datetime,
            location,
            claim_amount,
            policy_id=policy_id,
        )

    def add_document(
        self,
        db: Session,
        claim: Claim,
        doc_type: DocumentType,
        file_path: str,
        original_filename: str,
        checksum: str,
        ocr_text: str | None = None,
    ) -> ClaimDocument:
        doc = ClaimDocument(
            claim_id=claim.id,
            doc_type=doc_type,
            file_path=file_path,
            original_filename=original_filename,
            checksum=checksum,
            ocr_text=ocr_text,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    def validate_submit_gates(self, db: Session, claim: Claim) -> list[str]:
        errors: list[str] = []
        if not claim.policy_id:
            errors.append("A policy must be selected or uploaded (Step 2).")
        if not self.policy_context.has_policy_context(claim):
            errors.append("Policy papers must be loaded and analyzed (Step 2).")
        docs = db.query(ClaimDocument).filter(ClaimDocument.claim_id == claim.id).all()
        types = {d.doc_type for d in docs}
        profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == claim.customer_id).first()
        kyc_verified = is_kyc_verified(profile)
        if not kyc_verified and DocumentType.GOV_ID not in types:
            errors.append("Government ID is required (Step 3).")
        if DocumentType.PROOF not in types:
            errors.append("At least one proof document is required (Step 3).")
        return errors

    def finalize_submit(self, db: Session, claim: Claim) -> Claim:
        claim.status = ClaimStatus.PENDING
        claim.submission_step = 4
        db.commit()
        db.refresh(claim)
        self.explainability.log_audit(
            db, claim.id, "CLAIM_SUBMITTED", {"claim_number": claim.claim_number}, actor=f"customer:{claim.customer_id}"
        )
        return claim

    def trigger_processing(self, claim_id: int) -> None:
        self.orchestrator.dispatch(claim_id)
