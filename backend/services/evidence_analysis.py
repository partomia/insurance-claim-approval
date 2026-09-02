"""Motor-vehicle evidence analysis: validates each uploaded document against its
declared type using OCR + keyword heuristics + LLM validation as a tie-breaker.

Emits a per-document confidence score and surfaces mismatches for the claim
pipeline to feed into the decision engine.
"""

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
    DocumentType.DRIVER_LICENSE: "Driver's licence",
    DocumentType.DAMAGE_PHOTO: "Damage photo",
    DocumentType.REPAIR_ESTIMATE: "Repair estimate",
    DocumentType.POLICE_REPORT: "Police report / FIR",
    DocumentType.VEHICLE_REGISTRATION: "Vehicle registration (RC)",
    DocumentType.TOWING_INVOICE: "Towing invoice",
    DocumentType.THIRD_PARTY_STATEMENT: "Third-party statement",
    DocumentType.POLICY_PAPER: "Policy document",
    DocumentType.OTHER: "Supporting document",
}

# Phrase patterns for technical/architecture diagrams (still a valid mismatch signal).
TECH_DIAGRAM_PHRASES = (
    r"\bdata\s+pipeline\b",
    r"\bagents?\s+pipeline\b",
    r"\bprocessing\s+pipeline\b",
    r"\bml\s+pipeline\b",
    r"\betl\s+pipeline\b",
    r"\bflowchart\b",
    r"\bsequence\s+diagram\b",
    r"\bsystem\s+architecture\b",
    r"\bcomponent\s+diagram\b",
    r"\barchitecture\s+diagram\b",
)

DIAGRAM_FILENAME_HINTS = (
    "flowchart",
    "architecture",
    "pipeline_flow",
    "agent_workflow",
    "system_diagram",
)

# Motor-specific evidence heuristics.
DRIVER_LICENSE_PATTERNS = (
    r"\bdriver['']?s?\s*licen[cs]e\b",
    r"\bdriving\s*licen[cs]e\b",
    r"\bdl\s*(?:no|number|#)\b",
    r"\blicen[cs]e\s*(?:no|number|#|class)\b",
    r"\bendorsement(s)?\b",
    r"\bexpir(?:y|es|ation)\b",
    r"\bissuing\s*authority\b",
    r"\brto\b",
    r"\bmotor\s*vehicles?\s*department\b",
    r"\bdmv\b",
)

DRIVER_LICENSE_FILENAME_HINTS = (
    "dl",
    "driver",
    "driving",
    "licence",
    "license",
)

VEHICLE_REGISTRATION_PATTERNS = (
    r"\bregistration\s*certificate\b",
    r"\brc\s*book\b",
    r"\brc\s*copy\b",
    r"\bchassis\s*(?:no|number|#)\b",
    r"\bengine\s*(?:no|number|#)\b",
    r"\bvin\b",
    r"\bvehicle\s*identification\b",
    r"\bregistration\s*(?:no|number|#|authority)\b",
    r"\bmodel\s*year\b",
)

VEHICLE_REGISTRATION_FILENAME_HINTS = ("rc", "registration", "vehicle_rc", "regcert")

REPAIR_ESTIMATE_PATTERNS = (
    r"\bgarage\b",
    r"\bworkshop\b",
    r"\brepair\s*(?:estimate|invoice|order)\b",
    r"\bbody\s*shop\b",
    r"\bparts?\s*(?:cost|total|charge)\b",
    r"\blabou?r\s*(?:cost|charge|hours?)\b",
    r"\bgst\b",
    r"\bvat\b",
    r"\btax\b",
    r"\bdent(ing)?\b",
    r"\bpanel\b",
    r"\bbumper\b",
    r"\bwindshield\b",
    r"\bpaint(ing)?\b",
    r"\bpolish(ing)?\b",
    r"\bdenting\s*and\s*painting\b",
)

REPAIR_ESTIMATE_FILENAME_HINTS = (
    "estimate",
    "invoice",
    "garage",
    "workshop",
    "repair",
    "quote",
    "quotation",
    "bill",
)

POLICE_REPORT_PATTERNS = (
    r"\bfir\b",
    r"\bfirst\s*information\s*report\b",
    r"\bpolice\s*(?:report|station)\b",
    r"\bcrime\s*number\b",
    r"\bcomplainant\b",
    r"\baccused\b",
    r"\baccident\b",
    r"\bincident\s*(?:report|number)\b",
    r"\bofficer\b",
    r"\binvestigating\s*officer\b",
)

POLICE_REPORT_FILENAME_HINTS = ("fir", "police", "report", "incident")

TOWING_INVOICE_PATTERNS = (
    r"\btowing\b",
    r"\btow(ed)?\b",
    r"\brecovery\s*(?:service|vehicle)\b",
    r"\bpickup\s*(?:location|point)\b",
    r"\bdrop\s*(?:location|point)\b",
    r"\bcrane\s*charge\b",
)

TOWING_INVOICE_FILENAME_HINTS = ("tow", "towing", "recovery")

DAMAGE_PHOTO_HINTS = (
    "damage",
    "photo",
    "img",
    "image",
    "picture",
    "front",
    "rear",
    "side",
    "bumper",
    "dent",
    "scratch",
    "accident",
)

# When a doc claims to be a damage photo we mostly trust the filename/extension
# because OCR on a bare photograph rarely returns useful text.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif")


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


# Map each motor DocumentType to (patterns, filename_hints, expected_min_text).
_TYPE_MATCHERS = {
    DocumentType.DRIVER_LICENSE: (
        DRIVER_LICENSE_PATTERNS,
        DRIVER_LICENSE_FILENAME_HINTS,
        12,
    ),
    DocumentType.VEHICLE_REGISTRATION: (
        VEHICLE_REGISTRATION_PATTERNS,
        VEHICLE_REGISTRATION_FILENAME_HINTS,
        20,
    ),
    DocumentType.REPAIR_ESTIMATE: (
        REPAIR_ESTIMATE_PATTERNS,
        REPAIR_ESTIMATE_FILENAME_HINTS,
        40,
    ),
    DocumentType.POLICE_REPORT: (
        POLICE_REPORT_PATTERNS,
        POLICE_REPORT_FILENAME_HINTS,
        40,
    ),
    DocumentType.TOWING_INVOICE: (
        TOWING_INVOICE_PATTERNS,
        TOWING_INVOICE_FILENAME_HINTS,
        20,
    ),
}


class EvidenceAnalysisService:
    def analyze(self, db: Session, claim: Claim) -> EvidenceAnalysisResult:
        documents = list(claim.documents or [])
        if not documents:
            return EvidenceAnalysisResult(
                evidence_confidence_score=0.0,
                evidence_missing=True,
            )

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
                "Evidence OCR for claim doc id=%s filename=%s doc_type=%s chars=%s",
                doc.id,
                doc.original_filename,
                doc.doc_type.value,
                len(ocr_text or ""),
            )

            result = self._validate_document(doc, ocr_text, claim.incident_description)
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
    ) -> DocumentValidationResult:
        issues: list[str] = []
        issue_codes: list[str] = []
        type_mismatch = False
        mismatch_reason = ""
        text_lower = (ocr_text or "").lower()
        filename_lower = (doc.original_filename or "").lower()
        is_image = filename_lower.endswith(IMAGE_EXTENSIONS)
        is_pdf = filename_lower.endswith(".pdf")

        extraction_quality, extraction_message = self._assess_extraction_quality(
            ocr_text, is_image=is_image, is_pdf=is_pdf
        )

        # Damage photos are trusted heavily on filename since OCR on a photo is thin.
        if doc.doc_type == DocumentType.DAMAGE_PHOTO:
            if is_image or self._filename_suggests_damage(filename_lower):
                confidence = 0.75 if is_image else 0.55
                return DocumentValidationResult(
                    doc_type=doc.doc_type.value,
                    document_id=doc.id,
                    filename=doc.original_filename,
                    ocr_text=ocr_text or "",
                    confidence=confidence,
                    issues=issues,
                    issue_codes=issue_codes,
                    type_mismatch=False,
                    mismatch_reason="",
                )
            # Non-image damage photo file — flag as suspicious.
            type_mismatch = True
            mismatch_reason = "Damage photo slot expects an image file (jpg/png)"
            issues.append(mismatch_reason)
            issue_codes.append("evidence_type_mismatch")

        elif doc.doc_type in _TYPE_MATCHERS:
            patterns, filename_hints, min_text = _TYPE_MATCHERS[doc.doc_type]
            filename_hit = any(h in filename_lower for h in filename_hints)
            filename_diagram = any(h in filename_lower for h in DIAGRAM_FILENAME_HINTS)

            if filename_diagram:
                type_mismatch = True
                mismatch_reason = (
                    f"{FIELD_LABELS.get(doc.doc_type, doc.doc_type.value)} slot "
                    "does not accept technical diagrams"
                )
                issues.append(mismatch_reason)
                issue_codes.append("evidence_type_mismatch")

            elif extraction_quality != "good":
                if filename_hit:
                    # Trust the filename when OCR is thin.
                    pass
                else:
                    issues.append(extraction_message)
                    issue_codes.append("extraction_failed")
            else:
                # We have readable text — pattern-match against expected type.
                hits = sum(1 for p in patterns if re.search(p, text_lower, re.I))
                if hits == 0 and not filename_hit:
                    # Escalate to LLM for a tie-break.
                    llm_result = llm_service.validate_evidence_document(
                        doc.doc_type.value,
                        ocr_text or "",
                        incident_description,
                        "Motor",
                    )
                    if llm_result and not llm_result.get("matches_type", True):
                        type_mismatch = True
                        mismatch_reason = (
                            llm_result.get("reason")
                            or f"Document does not match expected type: {doc.doc_type.value}"
                        )
                        issues.append(mismatch_reason)
                        issue_codes.append("evidence_type_mismatch")

        else:
            # POLICY_PAPER, THIRD_PARTY_STATEMENT, OTHER — accept if extractable.
            if extraction_quality != "good":
                issues.append(extraction_message)
                issue_codes.append("extraction_failed")

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

    def _filename_suggests_damage(self, filename_lower: str) -> bool:
        return any(hint in filename_lower for hint in DAMAGE_PHOTO_HINTS)

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
        if doc_type == DocumentType.DAMAGE_PHOTO:
            return 0.75  # Handled above; keep as safety default.
        if doc_type and doc_type in _TYPE_MATCHERS:
            _, filename_hints, _ = _TYPE_MATCHERS[doc_type]
            if any(h in filename_lower for h in filename_hints) and "extraction_failed" not in issue_codes:
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
