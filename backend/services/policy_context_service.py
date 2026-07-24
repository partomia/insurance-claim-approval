from typing import Any

import logging

from sqlalchemy.orm import Session

from models.claim import Claim, ClaimDocument, ClaimStatus, DocumentType
from models.embeddings import PolicyClauseEmbedding
from models.policy import Policy, PolicyDocument
from rag.chroma_store import extract_section_ref
from services.llm_service import llm_service
from services.rag_service import rag_service

logger = logging.getLogger(__name__)


class PolicyContextService:
    def list_policy_documents(self, db: Session, policy_id: int) -> list[dict]:
        docs = db.query(PolicyDocument).filter(PolicyDocument.policy_id == policy_id).all()
        clauses = (
            db.query(PolicyClauseEmbedding)
            .filter(PolicyClauseEmbedding.policy_id == policy_id)
            .all()
        )
        result = [
            {
                "id": d.id,
                "title": d.title,
                "section_ref": d.section_ref,
                "content_preview": d.content_text[:200],
                "source": d.source.value,
            }
            for d in docs
        ]
        for c in clauses:
            result.append(
                {
                    "id": f"clause-{c.id}",
                    "title": f"Clause {c.section_ref}",
                    "section_ref": c.section_ref,
                    "content_preview": c.clause_text[:200],
                    "source": "CLAUSE",
                }
            )
        return result

    def fetch_from_db(self, db: Session, claim: Claim) -> list[dict]:
        docs = db.query(PolicyDocument).filter(PolicyDocument.policy_id == claim.policy_id).all()
        clauses = (
            db.query(PolicyClauseEmbedding)
            .filter(PolicyClauseEmbedding.policy_id == claim.policy_id)
            .all()
        )
        combined: list[dict] = []
        for d in docs:
            combined.append(
                {
                    "section_ref": d.section_ref,
                    "title": d.title,
                    "text": d.content_text,
                    "source": "db",
                }
            )
        for c in clauses:
            combined.append(
                {
                    "section_ref": c.section_ref,
                    "title": f"Clause {c.section_ref}",
                    "text": c.clause_text,
                    "source": "db_clause",
                }
            )
        return combined

    @staticmethod
    def tesseract_available() -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def _extract_text_from_file(self, file_path: str) -> str:
        path_lower = file_path.lower()
        try:
            if path_lower.endswith(".pdf"):
                from pypdf import PdfReader

                reader = PdfReader(file_path)
                pages = [page.extract_text() or "" for page in reader.pages[:20]]
                text = "\n".join(pages).strip()
                if text:
                    logger.info(
                        "PDF text extraction ok path=%s chars=%s preview=%r",
                        file_path,
                        len(text),
                        text[:120],
                    )
                    return text[:12000]
                logger.warning(
                    "PDF text extraction returned empty (likely scanned PDF) path=%s tesseract=%s",
                    file_path,
                    self.tesseract_available(),
                )
        except Exception as exc:
            logger.warning("PDF text extraction failed path=%s error=%s", file_path, exc)

        try:
            import pytesseract
            from PIL import Image

            if path_lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
                text = pytesseract.image_to_string(Image.open(file_path)).strip()
                if text:
                    logger.info(
                        "Image OCR ok path=%s chars=%s preview=%r",
                        file_path,
                        len(text),
                        text[:120],
                    )
                    return text[:12000]
                logger.warning("Image OCR returned empty path=%s", file_path)
        except Exception as exc:
            logger.warning(
                "Image OCR failed path=%s error=%s (install tesseract for photo ID OCR)",
                file_path,
                exc,
            )
        return ""

    def _ocr_file(self, file_path: str) -> str:
        return self._extract_text_from_file(file_path)

    def ingest_upload(
        self,
        db: Session,
        claim: Claim,
        file_path: str,
        filename: str,
        checksum: str,
    ) -> ClaimDocument:
        ocr_text = self._ocr_file(file_path)
        doc = ClaimDocument(
            claim_id=claim.id,
            doc_type=DocumentType.POLICY_PAPER,
            file_path=file_path,
            original_filename=filename,
            checksum=checksum,
            ocr_text=ocr_text or None,
            metadata_json={"source": "upload"},
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        if claim.policy_id and ocr_text:
            from models.policy import PolicyDocument as PolicyScheduleDocument

            existing_schedule = (
                db.query(PolicyScheduleDocument)
                .filter(PolicyScheduleDocument.policy_id == claim.policy_id)
                .first()
            )
            if existing_schedule and existing_schedule.content_text:
                logger.info(
                    "Skipping duplicate RAG index for claim %s — policy %s already indexed (doc id=%s)",
                    claim.id,
                    claim.policy_id,
                    existing_schedule.id,
                )
            else:
                primary_section = extract_section_ref(ocr_text) or "Policy Schedule"
                rag_service.index_policy_document(
                    db,
                    claim.policy_id,
                    ocr_text,
                    section_ref=primary_section,
                    source="claim_upload",
                    filename=filename,
                    document_id=existing_schedule.id if existing_schedule else doc.id,
                )
        return doc

    def analyze_with_groq(
        self,
        db: Session,
        claim: Claim,
        documents: list[dict],
        source: str,
    ) -> dict[str, Any]:
        policy = db.query(Policy).filter(Policy.id == claim.policy_id).first()
        full_text = "\n\n".join(
            f"[{d.get('section_ref', 'Section')}] {d.get('text', d.get('content_text', ''))}"
            for d in documents
        )

        llm_result = llm_service.invoke_json(
            "You are an insurance policy analyst. Extract structured policy information.",
            f"""Analyze this policy schedule for a {policy.policy_type if policy else 'Insurance'} policy.

Policy number: {policy.policy_number if policy else 'N/A'}
Coverage limit: ${policy.coverage_limit if policy else 0:,.0f}
Deductible: ${policy.deductible if policy else 0:,.0f}

Policy document text:
{full_text[:8000]}

Return JSON:
{{
  "coverage_summary": "string",
  "exclusions": ["list"],
  "coverage_limits": {{"type": amount}},
  "deductibles": {{"type": amount}},
  "endorsements": ["list"],
  "key_sections": [{{"ref": "string", "category": "coverage|exclusion|settlement", "summary": "string"}}],
  "waiting_periods": ["list"],
  "llm_analysis": "detailed paragraph"
}}""",
        )

        if not llm_result:
            llm_result = {
                "coverage_summary": full_text[:500] or "Policy documents loaded.",
                "exclusions": policy.exclusions if policy else [],
                "coverage_limits": {"general": policy.coverage_limit if policy else 0},
                "deductibles": {"standard": policy.deductible if policy else 0},
                "endorsements": [],
                "key_sections": [
                    {"ref": d.get("section_ref", ""), "category": "coverage", "summary": d.get("text", "")[:100]}
                    for d in documents[:5]
                ],
                "waiting_periods": [],
                "llm_analysis": "Policy documents analyzed from stored schedule.",
            }

        context = {
            **llm_result,
            "source": source,
            "document_count": len(documents),
            "sections_loaded": [d.get("section_ref") for d in documents],
        }

        existing_source = claim.policy_docs_source or ""
        if existing_source and existing_source != source:
            claim.policy_docs_source = "both"
        else:
            claim.policy_docs_source = source

        claim.policy_context_json = context
        claim.submission_step = max(claim.submission_step, 2)
        db.commit()
        db.refresh(claim)
        return context

    def has_policy_context(self, claim: Claim) -> bool:
        ctx = claim.policy_context_json or {}
        return bool(ctx.get("coverage_summary") or ctx.get("llm_analysis") or ctx.get("key_sections"))
