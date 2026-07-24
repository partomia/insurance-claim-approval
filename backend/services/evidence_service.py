import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from models.claim import Claim, ClaimDocument, ClaimStatus, DocumentType
from services.claim_service import save_upload
from services.evidence_analysis import EvidenceAnalysisService
from services.explainability import ExplainabilityService
from services.ocr_service import ocr_service
from services.orchestrator import ClaimOrchestrator


ALLOWED_STATUSES = {
    ClaimStatus.PENDING_REVIEW,
    ClaimStatus.REQUEST_MORE_INFO,
    ClaimStatus.PROCESSING,
}


class EvidenceService:
    def __init__(self) -> None:
        self.orchestrator = ClaimOrchestrator()
        self.explainability = ExplainabilityService()

    def _get_claim(self, db: Session, claim_id: int, customer_id: int) -> Claim:
        claim = (
            db.query(Claim)
            .options(joinedload(Claim.documents), joinedload(Claim.policy))
            .filter(Claim.id == claim_id, Claim.customer_id == customer_id)
            .first()
        )
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")
        return claim

    def _ensure_editable(self, claim: Claim) -> None:
        if claim.status not in ALLOWED_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot modify evidence while claim status is {claim.status.value}",
            )

    def _get_document(
        self, db: Session, claim: Claim, document_id: Optional[int], doc_type: Optional[str]
    ) -> ClaimDocument:
        if document_id:
            doc = next((d for d in claim.documents if d.id == document_id), None)
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
            return doc

        if doc_type:
            try:
                dtype = DocumentType(doc_type)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid doc_type: {doc_type}") from exc
            matches = [d for d in claim.documents if d.doc_type == dtype]
            if not matches:
                raise HTTPException(status_code=404, detail=f"No document of type {doc_type}")
            return sorted(matches, key=lambda d: d.created_at)[-1]

        raise HTTPException(status_code=400, detail="document_id or doc_type required")

    async def replace_document(
        self,
        db: Session,
        claim_id: int,
        customer_id: int,
        file: UploadFile,
        document_id: Optional[int] = None,
        doc_type: Optional[str] = None,
    ) -> dict:
        claim = self._get_claim(db, claim_id, customer_id)
        self._ensure_editable(claim)
        old_doc = self._get_document(db, claim, document_id, doc_type)

        if old_doc.file_path and os.path.isfile(old_doc.file_path):
            try:
                os.remove(old_doc.file_path)
            except OSError:
                pass

        file_path, checksum = await save_upload(file, claim_id)
        ocr_text = ocr_service.extract_text(file_path)

        db.delete(old_doc)
        db.flush()

        new_doc = ClaimDocument(
            claim_id=claim.id,
            doc_type=old_doc.doc_type,
            file_path=file_path,
            original_filename=file.filename or "upload",
            checksum=checksum,
            ocr_text=ocr_text,
            metadata_json={},
        )
        db.add(new_doc)
        claim.status = ClaimStatus.PROCESSING
        db.commit()
        db.refresh(new_doc)

        self.explainability.log_audit(
            db,
            claim.id,
            "EVIDENCE_REPLACED",
            {
                "old_document_id": old_doc.id,
                "new_document_id": new_doc.id,
                "doc_type": new_doc.doc_type.value,
                "filename": new_doc.original_filename,
            },
            actor=f"customer:{customer_id}",
        )

        self.orchestrator.dispatch_from_step(claim.id, "evidence_analysis")
        return {
            "message": "Document replaced — re-analyzing from Evidence Analysis",
            "document_id": new_doc.id,
            "pipeline_run_id": claim.pipeline_run_id,
        }
    def acknowledge_document(
        self,
        db: Session,
        claim_id: int,
        customer_id: int,
        document_id: int,
        note: Optional[str] = None,
    ) -> dict:
        claim = self._get_claim(db, claim_id, customer_id)
        self._ensure_editable(claim)
        doc = self._get_document(db, claim, document_id, None)

        meta = dict(doc.metadata_json or {})
        meta["acknowledged"] = True
        meta["acknowledged_note"] = note or ""
        meta["acknowledged_at"] = datetime.utcnow().isoformat()
        doc.metadata_json = meta

        issues = list(claim.evidence_issues or [])
        for issue in issues:
            if issue.get("document_id") == document_id:
                issue["acknowledged"] = True
        claim.evidence_issues = issues

        result = EvidenceAnalysisService().analyze(db, claim)
        claim.evidence_mismatch = result.evidence_mismatch
        claim.evidence_issues = result.evidence_issues

        pipeline_run_id = claim.pipeline_run_id
        if not result.evidence_mismatch:
            claim.status = ClaimStatus.PROCESSING
            claim.pipeline_run_id = (claim.pipeline_run_id or 0) + 1
            pipeline_run_id = claim.pipeline_run_id

        db.commit()

        self.explainability.log_audit(
            db,
            claim.id,
            "EVIDENCE_ACKNOWLEDGED",
            {"document_id": document_id, "note": note},
            actor=f"customer:{customer_id}",
        )

        if not result.evidence_mismatch:
            self.orchestrator.dispatch_from_step(claim.id, "evidence_analysis")

        return {
            "message": "Document acknowledged",
            "evidence_mismatch": result.evidence_mismatch,
            "pipeline_run_id": pipeline_run_id,
        }
