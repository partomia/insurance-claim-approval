import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.claim import Claim, ClaimDocument, DocumentType
from services.llm_service import llm_service
from services.ocr_service import ocr_service

logger = logging.getLogger(__name__)

FIELD_LABELS = {
    DocumentType.GOV_ID: "Government ID",
    DocumentType.PROOF: "Proof document",
    DocumentType.POLICE_REPORT: "Police report",
    DocumentType.MEDICAL: "Medical document",
    DocumentType.INVOICE: "Invoice",
}

# Phrase patterns for technical/architecture diagrams — not plumbing "pipeline"
TECH_DIAGRAM_PHRASES = (
    r"\bdata\s+pipeline\b",
    r"\bagents?\s+pipeline\b",
    r"\bprocessing\s+pipeline\b",
    r"\bml\s+pipeline\b",
    r"\betl\s+pipeline\b",
    r"\bdiscovery\s+pipeline\b",
    r"\bflowchart\b",
    r"\bsequence\s+diagram\b",
    r"\bsystem\s+architecture\b",
    r"\bcomponent\s+diagram\b",
    r"\barchitecture\s+diagram\b",
    r"\brfp\b",
)

DIAGRAM_FILENAME_HINTS = (
    "flowchart",
    "architecture",
    "rfp_discovery",
    "pipeline_flow",
    "agent_workflow",
    "system_diagram",
)

GOV_ID_PATTERNS = (
    r"\bpassport\b",
    r"\bdriver['']?s?\s*licen[cs]e\b",
    r"\bdate\s*of\s*birth\b",
    r"\bd\.?o\.?b\.?\b",
    r"\bnational\s*id\b",
    r"\bidentity\s*card\b",
    r"\b(?:id|license|licence)\s*(?:no|number|#)\b",
    r"\b(?:expir(?:y|es|ation)|issued)\b",
    r"\b(?:sex|gender)\b",
    r"\b(?:address|nationality)\b",
    r"\baadhaar\b",
    r"\baadhar\b",
    r"\buidai\b",
    r"\bpan\b",
    r"\bpermanent\s*account\b",
    r"\bincome\s*tax\b",
    r"\bgovernment\s*of\s*india\b",
    r"\bunique\s*identification\b",
    r"\bvoter\b",
    r"\belection\s*commission\b",
)

ID_FILENAME_HINTS = (
    "pan",
    "aadhar",
    "aadhaar",
    "passport",
    "license",
    "licence",
    "voter",
    "identity",
    "gov_id",
    "gov-id",
    "national_id",
    "id_card",
    "id-card",
)

PROOF_FILENAME_HINTS = (
    "inspection",
    "repair",
    "estimate",
    "invoice",
    "report",
    "proof",
    "evidence",
    "damage",
    "plumber",
    "medical",
    "bill",
    "receipt",
    "police",
    "survey",
)

PROOF_TEXT_KEYWORDS = (
    "inspection",
    "repair",
    "estimate",
    "invoice",
    "damage",
    "plumber",
    "contractor",
    "report",
    "survey",
    "receipt",
    "bill",
    "claim",
    "incident",
    "loss",
    "property",
    "home",
    "roof",
    "water",
    "fire",
    "theft",
    "medical",
    "hospital",
    "treatment",
    "diagnosis",
    "assessment",
    "itemized",
    "leak",
    "plumbing",
    "flood",
    "mold",
)

HOME_PROOF_KEYWORDS = (
    "inspection",
    "repair",
    "estimate",
    "damage",
    "assessment",
    "plumber",
    "plumbing",
    "contractor",
    "property",
    "leak",
    "water",
    "pipe",
    "flood",
    "roof",
    "itemized",
)


@dataclass
class DocumentValidationResult:
    doc_type: str
    document_id: Optional[int] = None
    filename: str = ""
    ocr_text: str = ""
    confidence: float = 0.0
    issues: list[str] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    type_mismatch: bool = False
    mismatch_reason: str = ""


@dataclass
class EvidenceAnalysisResult:
    evidence_confidence_score: float
    evidence_missing: bool
    document_results: list[DocumentValidationResult] = field(default_factory=list)
    duplicate_uploads: list[str] = field(default_factory=list)
    evidence_mismatch: bool = False
    evidence_issues: list[dict[str, Any]] = field(default_factory=list)


class EvidenceAnalysisService:
    def analyze(self, db: Session, claim: Claim) -> EvidenceAnalysisResult:
        documents = list(claim.documents or [])
        if not documents:
            return EvidenceAnalysisResult(
                evidence_confidence_score=0.0,
                evidence_missing=True,
            )

        policy_type = claim.policy.policy_type if claim.policy else "Auto"
        seen_checksums: dict[str, str] = {}
        duplicate_uploads: list[str] = []
        document_results: list[DocumentValidationResult] = []
        evidence_issues: list[dict[str, Any]] = []

        for doc in documents:
            if doc.checksum in seen_checksums:
                duplicate_uploads.append(doc.original_filename)
            else:
                seen_checksums[doc.checksum] = doc.original_filename

            ocr_text = doc.ocr_text or ocr_service.extract_text(doc.file_path)
            if ocr_text and ocr_text != doc.ocr_text:
                doc.ocr_text = ocr_text
                db.add(doc)

            logger.info(
                "Evidence OCR for claim doc id=%s filename=%s doc_type=%s chars=%s preview=%r",
                doc.id,
                doc.original_filename,
                doc.doc_type.value,
                len(ocr_text or ""),
                (ocr_text or "")[:200],
            )

            result = self._validate_document(
                doc,
                ocr_text,
                claim.incident_description,
                policy_type,
            )
            document_results.append(result)

            if result.type_mismatch and not self._is_acknowledged(doc):
                field_label = FIELD_LABELS.get(doc.doc_type, doc.doc_type.value)
                evidence_issues.append(
                    {
                        "field": field_label,
                        "document_id": doc.id,
                        "filename": doc.original_filename,
                        "reason": result.mismatch_reason,
                        "issue_code": "evidence_type_mismatch",
                        "acknowledged": False,
                    }
                )
            elif "extraction_failed" in result.issue_codes and not self._is_acknowledged(doc):
                field_label = FIELD_LABELS.get(doc.doc_type, doc.doc_type.value)
                extraction_msg = next(
                    (i for i in result.issues if "Could not extract" in i),
                    "Could not extract readable content from this document",
                )
                evidence_issues.append(
                    {
                        "field": field_label,
                        "document_id": doc.id,
                        "filename": doc.original_filename,
                        "reason": extraction_msg,
                        "issue_code": "extraction_failed",
                        "acknowledged": False,
                    }
                )

        db.commit()

        avg_confidence = sum(r.confidence for r in document_results) / max(len(document_results), 1)
        if duplicate_uploads:
            avg_confidence = max(0.0, avg_confidence - 0.15 * len(duplicate_uploads))

        evidence_mismatch = any(
            r.type_mismatch and not self._is_acknowledged(
                next(d for d in documents if d.id == r.document_id)
            )
            for r in document_results
            if r.document_id is not None
        )

        return EvidenceAnalysisResult(
            evidence_confidence_score=round(min(1.0, avg_confidence), 4),
            evidence_missing=False,
            document_results=document_results,
            duplicate_uploads=duplicate_uploads,
            evidence_mismatch=evidence_mismatch,
            evidence_issues=evidence_issues,
        )

    def _is_acknowledged(self, doc: ClaimDocument) -> bool:
        meta = doc.metadata_json if isinstance(doc.metadata_json, dict) else {}
        return bool(meta.get("acknowledged"))

    def _validate_document(
        self,
        doc: ClaimDocument,
        ocr_text: str,
        incident_description: str,
        policy_type: str,
    ) -> DocumentValidationResult:
        issues: list[str] = []
        issue_codes: list[str] = []
        type_mismatch = False
        mismatch_reason = ""
        text_lower = (ocr_text or "").lower()
        filename_lower = (doc.original_filename or "").lower()
        is_image = filename_lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
        is_pdf = filename_lower.endswith(".pdf")

        extraction_quality, extraction_message = self._assess_extraction_quality(
            ocr_text, is_image=is_image, is_pdf=is_pdf
        )
        filename_suggests_diagram = any(h in filename_lower for h in DIAGRAM_FILENAME_HINTS)

        if extraction_quality != "good":
            if doc.doc_type == DocumentType.GOV_ID and self._filename_suggests_id(filename_lower):
                # Accept ID uploads identified by filename when image OCR is unavailable
                logger.info(
                    "GOV_ID accepted via filename hint (OCR unavailable or empty) filename=%s",
                    doc.original_filename,
                )
            else:
                issues.append(extraction_message)
                issue_codes.append("extraction_failed")

        # Evaluate document-type match when content is readable, or filename clearly indicates diagram
        if extraction_quality == "good" or filename_suggests_diagram:
            if doc.doc_type == DocumentType.GOV_ID:
                type_mismatch, mismatch_reason = self._check_gov_id(
                    text_lower, filename_lower, is_image, len(ocr_text or "")
                )
            elif doc.doc_type == DocumentType.PROOF:
                type_mismatch, mismatch_reason = self._check_proof(
                    text_lower, filename_lower, incident_description, policy_type, is_image
                )

            if type_mismatch:
                issues.append(mismatch_reason)
                issue_codes.append("evidence_type_mismatch")
                # Diagram/mismatch confirmed from filename or content — not just unreadable file
                if "extraction_failed" in issue_codes and extraction_quality != "good":
                    issue_codes.remove("extraction_failed")
                    issues[:] = [i for i in issues if "Could not extract" not in i]

            if (
                not type_mismatch
                and doc.doc_type in (DocumentType.GOV_ID, DocumentType.PROOF)
                and self._should_run_llm_validation(
                    doc, ocr_text, text_lower, filename_lower, is_image, policy_type
                )
            ):
                llm_result = llm_service.validate_evidence_document(
                    doc.doc_type.value,
                    ocr_text or "",
                    incident_description,
                    policy_type,
                )
                if llm_result and not llm_result.get("matches_type", True):
                    type_mismatch = True
                    mismatch_reason = llm_result.get("reason") or "Document does not match expected type"
                    if mismatch_reason not in issues:
                        issues.append(mismatch_reason)
                    if "evidence_type_mismatch" not in issue_codes:
                        issue_codes.append("evidence_type_mismatch")
        elif doc.doc_type == DocumentType.GOV_ID and self._filename_suggests_id(filename_lower):
            # Allow ID filename hint even when OCR failed — do not assert mismatch
            pass

        confidence = self._score_confidence(
            ocr_text, issue_codes, type_mismatch, filename_lower, doc.doc_type
        )

        return DocumentValidationResult(
            doc_type=doc.doc_type.value,
            document_id=doc.id,
            filename=doc.original_filename,
            ocr_text=ocr_text or "",
            confidence=confidence,
            issues=issues,
            issue_codes=issue_codes,
            type_mismatch=type_mismatch,
            mismatch_reason=mismatch_reason,
        )

    def _filename_suggests_id(self, filename_lower: str) -> bool:
        return any(hint in filename_lower for hint in ID_FILENAME_HINTS)

    def _text_suggests_id(self, text_lower: str) -> bool:
        if len(text_lower) < 8:
            return False
        hits = sum(1 for p in GOV_ID_PATTERNS if re.search(p, text_lower, re.I))
        return hits >= 1

    def _looks_like_valid_id(self, text_lower: str, filename_lower: str) -> bool:
        return self._filename_suggests_id(filename_lower) or self._text_suggests_id(text_lower)

    def _filename_suggests_proof(self, filename_lower: str) -> bool:
        return any(hint in filename_lower for hint in PROOF_FILENAME_HINTS)

    def _text_suggests_proof(self, text_lower: str, policy_type: str = "Auto") -> bool:
        if len(text_lower) < 40:
            return False
        keywords = HOME_PROOF_KEYWORDS if policy_type == "Home" else PROOF_TEXT_KEYWORDS
        hits = sum(1 for kw in keywords if kw in text_lower)
        min_hits = 2 if policy_type != "Home" else 2
        return hits >= min_hits

    def _looks_like_valid_proof(
        self, text_lower: str, filename_lower: str, policy_type: str = "Auto"
    ) -> bool:
        return self._filename_suggests_proof(filename_lower) or self._text_suggests_proof(
            text_lower, policy_type
        )

    def _assess_extraction_quality(
        self, ocr_text: str, *, is_image: bool, is_pdf: bool
    ) -> tuple[str, str]:
        """Return (quality, message) where quality is good | poor | empty."""
        stripped = (ocr_text or "").strip()
        text_len = len(stripped)
        if text_len == 0:
            return "empty", "Could not extract readable content from this document"
        if is_image and text_len < 20:
            return "poor", "Could not extract readable content from this document"
        if is_pdf and text_len < 40:
            return "poor", "Could not extract readable content from this document"
        alnum = sum(1 for c in stripped if c.isalnum() or c.isspace())
        if text_len > 0 and alnum / text_len < 0.45:
            return "poor", "Could not extract readable content from this document"
        return "good", ""

    def _should_run_llm_validation(
        self,
        doc: ClaimDocument,
        ocr_text: str,
        text_lower: str,
        filename_lower: str,
        is_image: bool,
        policy_type: str = "Auto",
    ) -> bool:
        if self._looks_like_diagram(text_lower, filename_lower):
            return True
        if doc.doc_type == DocumentType.GOV_ID:
            if self._looks_like_valid_id(text_lower, filename_lower):
                return False
            return is_image and len(ocr_text or "") < 40
        if doc.doc_type == DocumentType.PROOF:
            if self._looks_like_valid_proof(text_lower, filename_lower, policy_type):
                return False
            return len(ocr_text or "") < 80 and is_image
        return False

    def _check_gov_id(
        self, text_lower: str, filename_lower: str, is_image: bool, text_len: int
    ) -> tuple[bool, str]:
        if self._looks_like_diagram(text_lower, filename_lower):
            return True, "Uploaded Government ID does not appear to be a valid identity document"

        if self._looks_like_valid_id(text_lower, filename_lower):
            return False, ""

        if is_image and text_len == 0 and not self._filename_suggests_id(filename_lower):
            return False, ""

        if is_image and text_len < 12 and not self._filename_suggests_id(filename_lower):
            return True, "Uploaded Government ID does not appear to be a valid identity document"

        if text_len >= 12:
            id_hits = sum(1 for p in GOV_ID_PATTERNS if re.search(p, text_lower, re.I))
            if id_hits >= 1:
                return False, ""

        return False, ""

    def _check_proof(
        self,
        text_lower: str,
        filename_lower: str,
        incident_description: str,
        policy_type: str,
        is_image: bool,
    ) -> tuple[bool, str]:
        if self._looks_like_diagram(text_lower, filename_lower):
            return True, "Uploaded proof document does not match claim type"

        if self._looks_like_valid_proof(text_lower, filename_lower, policy_type):
            return False, ""

        if not is_image and len(text_lower) >= 80:
            return False, ""

        if is_image and len(text_lower) < 12 and not self._filename_suggests_proof(filename_lower):
            return True, "Uploaded proof document does not match claim type"

        return False, ""

    def _looks_like_diagram(self, text_lower: str, filename_lower: str) -> bool:
        if any(hint in filename_lower for hint in DIAGRAM_FILENAME_HINTS):
            return True
        combined = f"{text_lower} {filename_lower}"
        tech_hits = sum(1 for pattern in TECH_DIAGRAM_PHRASES if re.search(pattern, combined, re.I))
        return tech_hits >= 1

    def _score_confidence(
        self,
        ocr_text: str,
        issue_codes: list[str],
        type_mismatch: bool,
        filename_lower: str = "",
        doc_type: DocumentType | None = None,
    ) -> float:
        if type_mismatch:
            return 0.25
        if (
            doc_type == DocumentType.GOV_ID
            and self._filename_suggests_id(filename_lower)
            and "extraction_failed" not in issue_codes
        ):
            return 0.75
        if "extraction_failed" in issue_codes:
            return 0.30
        if not ocr_text:
            return 0.30
        base = min(1.0, len(ocr_text) / 400.0)
        other_issues = [c for c in issue_codes if c != "extraction_failed"]
        penalty = 0.15 * len(other_issues)
        return max(0.1, base - penalty)

    def to_dict_list(self, result: EvidenceAnalysisResult) -> list[dict[str, Any]]:
        return [
            {
                "doc_type": r.doc_type,
                "document_id": r.document_id,
                "filename": r.filename,
                "confidence": r.confidence,
                "issues": r.issues,
                "issue_codes": r.issue_codes,
                "type_mismatch": r.type_mismatch,
                "mismatch_reason": r.mismatch_reason,
                "extraction_failed": "extraction_failed" in r.issue_codes,
                "valid": not r.type_mismatch and not r.issues,
            }
            for r in result.document_results
        ]
