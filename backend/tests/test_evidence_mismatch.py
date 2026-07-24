from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from models.claim import Claim, ClaimDocument, ClaimStatus, DocumentType
from models.policy import Policy, PolicyStatus
from services.evidence_analysis import EvidenceAnalysisService


def _make_claim_with_doc(
    db_session,
    filename: str,
    doc_type: DocumentType,
    ocr_text: str = "",
    policy_type: str = "Auto",
) -> Claim:
    policy = Policy(
        policy_number="POL-EV",
        customer_id=1,
        policy_type=policy_type,
        status=PolicyStatus.ACTIVE,
        coverage_limit=50000,
        deductible=500,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=100),
        expiry_date=datetime.utcnow() + timedelta(days=265),
    )
    db_session.add(policy)
    db_session.commit()

    claim = Claim(
        claim_number="CLM-EV",
        customer_id=1,
        policy_id=policy.id,
        incident_description="Rear-end collision on I-35",
        incident_datetime=datetime.utcnow(),
        location="Austin, TX",
        claim_amount=5000,
        status=ClaimStatus.PROCESSING,
    )
    db_session.add(claim)
    db_session.commit()

    doc = ClaimDocument(
        claim_id=claim.id,
        doc_type=doc_type,
        file_path=f"/tmp/{filename}",
        original_filename=filename,
        checksum="abc123",
        ocr_text=ocr_text,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(claim)
    return claim


@patch("services.evidence_analysis.ocr_service.extract_text", return_value="")
def test_gov_id_diagram_flagged(mock_ocr, db_session):
    claim = _make_claim_with_doc(
        db_session,
        "rfp_discovery_pipeline_flow.png",
        DocumentType.GOV_ID,
    )
    with patch.object(
        EvidenceAnalysisService,
        "_looks_like_diagram",
        return_value=True,
    ):
        result = EvidenceAnalysisService().analyze(db_session, claim)

    assert result.evidence_mismatch is True
    assert len(result.evidence_issues) == 1
    assert result.evidence_issues[0]["issue_code"] == "evidence_type_mismatch"
    assert "Government ID" in result.evidence_issues[0]["field"]


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
@patch("services.evidence_analysis.ocr_service.extract_text", return_value="")
def test_gov_id_valid_passes(mock_ocr, mock_llm, db_session):
    ocr = (
        "STATE OF TEXAS\nDriver License\nName: John Doe\nDOB: 01/15/1990\n"
        "License No: 12345678\nExpires: 01/15/2028\nAddress: 123 Main St"
    )
    claim = _make_claim_with_doc(
        db_session,
        "drivers_license.jpg",
        DocumentType.GOV_ID,
        ocr_text=ocr,
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
def test_proof_diagram_flagged(mock_llm, db_session):
    claim = _make_claim_with_doc(
        db_session,
        "rfp_discovery_pipeline_flow.png",
        DocumentType.PROOF,
        ocr_text="agent pipeline flowchart discovery architecture",
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is True
    assert result.evidence_issues[0]["field"] == "Proof document"


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
def test_pan_card_image_passes_with_minimal_ocr(mock_llm, db_session):
    claim = _make_claim_with_doc(
        db_session,
        "pan_card_front.jpg",
        DocumentType.GOV_ID,
        ocr_text="",
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
def test_aadhar_text_passes(mock_llm, db_session):
    ocr = "Government of India\nAadhaar\nName: Raj Kumar\nDOB: 15/08/1990\nUID: 1234 5678 9012"
    claim = _make_claim_with_doc(
        db_session,
        "aadhar.jpg",
        DocumentType.GOV_ID,
        ocr_text=ocr,
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
def test_inspection_report_pdf_passes(mock_llm, db_session):
    ocr = (
        "Plumber Inspection Report\nRepair Estimate\nWater damage assessment\n"
        "Property inspection completed\nTotal repair estimate $7800\nInvoice details"
    )
    claim = _make_claim_with_doc(
        db_session,
        "Evidence_PlumberInspection_RepairEstimate.pdf",
        DocumentType.PROOF,
        ocr_text=ocr,
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False


def test_escalation_evidence_mismatch_flag():
    from services.escalation_service import EscalationService

    claim = MagicMock()
    claim.policy = None
    claim.incident_datetime = datetime.utcnow()
    claim.claim_amount = 1000

    result = EscalationService().evaluate(
        claim,
        {
            "evidence_mismatch": True,
            "evidence_issues": [
                {
                    "field": "Government ID",
                    "reason": "Uploaded Government ID does not appear to be a valid identity document",
                    "acknowledged": False,
                }
            ],
            "evidence_confidence_score": 0.25,
        },
    )
    assert "evidence_mismatch" in result.flags
    assert "low_evidence_confidence" in result.flags


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
def test_plumbing_pipeline_mention_not_flagged(mock_llm, db_session):
    """Water/plumbing 'pipeline' language must not trigger tech-diagram mismatch."""
    ocr = (
        "Plumber Inspection Report\n"
        "Water pipeline burst in basement causing flood damage\n"
        "Repair estimate — itemized contractor assessment\n"
        "Property address: 123 Oak Street\n"
        "Damage assessment completed 03/15/2026\n"
        "Total repair estimate: $7,800.00"
    )
    claim = _make_claim_with_doc(
        db_session,
        "Evidence_PlumberInspection_RepairEstimate.pdf",
        DocumentType.PROOF,
        ocr_text=ocr,
        policy_type="Home",
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False
    assert result.evidence_confidence_score > 0.5
    assert not any(i.get("issue_code") == "evidence_type_mismatch" for i in result.evidence_issues)


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
def test_home_inspection_text_pdf_high_confidence(mock_llm, db_session):
    ocr = (
        "HOME DAMAGE INSPECTION REPORT\n"
        "Section: Water intrusion / plumbing failure\n"
        "Inspector: Licensed plumber\n"
        "Findings: Burst pipe, drywall damage, flooring loss\n"
        "Itemized repair estimate attached\n"
        "Recommended repairs: pipe replacement, mold remediation\n"
        "Estimated cost: $12,450.00\n"
        "Property: 456 Maple Ave, Austin TX 78701\n"
    )
    claim = _make_claim_with_doc(
        db_session,
        "home_inspection_report.pdf",
        DocumentType.PROOF,
        ocr_text=ocr,
        policy_type="Home",
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False
    assert result.evidence_confidence_score >= 0.7
    assert result.evidence_issues == []


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
@patch("services.evidence_analysis.ocr_service.extract_text", return_value="")
def test_pan_card_filename_accepted_without_tesseract(mock_ocr, mock_llm, db_session):
    """PAN/Aadhaar image uploads should not block the claim when OCR is unavailable."""
    claim = _make_claim_with_doc(
        db_session,
        "pan_card.jpeg",
        DocumentType.GOV_ID,
        ocr_text="",
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False
    assert result.evidence_issues == []
    assert result.evidence_confidence_score >= 0.75


@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
def test_plumber_pdf_and_pan_combined_confidence(mock_llm, db_session):
    """PDF proof reads fine; PAN filename hint should not drag confidence down."""
    policy = Policy(
        policy_number="POL-HOME",
        customer_id=1,
        policy_type="Home",
        status=PolicyStatus.ACTIVE,
        coverage_limit=350000,
        deductible=1000,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=100),
        expiry_date=datetime.utcnow() + timedelta(days=265),
    )
    db_session.add(policy)
    db_session.commit()
    claim = Claim(
        claim_number="CLM-MIX",
        customer_id=1,
        policy_id=policy.id,
        incident_description="Basement pipe burst",
        incident_datetime=datetime.utcnow(),
        location="Millbrook",
        claim_amount=7800,
        status=ClaimStatus.PROCESSING,
    )
    db_session.add(claim)
    db_session.commit()
    pdf_ocr = (
        "Plumber Inspection Report\nRepair estimate $7800\nDamage assessment\n"
        "Property address 88 Cedarbrook Lane\n" * 5
    )
    for fname, dtype, ocr in [
        ("pan_card.jpeg", DocumentType.GOV_ID, ""),
        ("Evidence_PlumberInspection.pdf", DocumentType.PROOF, pdf_ocr),
    ]:
        db_session.add(
            ClaimDocument(
                claim_id=claim.id,
                doc_type=dtype,
                file_path=f"/tmp/{fname}",
                original_filename=fname,
                checksum=fname,
                ocr_text=ocr,
            )
        )
    db_session.commit()
    db_session.refresh(claim)
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False
    assert result.evidence_issues == []
    assert result.evidence_confidence_score >= 0.85
    proof = next(r for r in result.document_results if r.filename.endswith(".pdf"))
    assert proof.confidence >= 0.9
    assert len(proof.ocr_text) > 100


@patch("services.evidence_analysis.ocr_service.extract_text", return_value="")
@patch("services.evidence_analysis.llm_service.validate_evidence_document", return_value=None)
def test_empty_pdf_proof_flags_extraction_not_mismatch(mock_llm, mock_ocr, db_session):
    claim = _make_claim_with_doc(
        db_session,
        "scanned_proof.pdf",
        DocumentType.PROOF,
        ocr_text="",
        policy_type="Home",
    )
    result = EvidenceAnalysisService().analyze(db_session, claim)
    assert result.evidence_mismatch is False
    assert len(result.evidence_issues) == 1
    assert result.evidence_issues[0]["issue_code"] == "extraction_failed"
    assert "Could not extract readable content" in result.evidence_issues[0]["reason"]
    assert result.evidence_confidence_score == 0.30


def test_escalation_extraction_failed_separate_from_mismatch():
    from services.escalation_service import EscalationService

    claim = MagicMock()
    claim.policy = None
    claim.incident_datetime = datetime.utcnow()
    claim.claim_amount = 1000

    result = EscalationService().evaluate(
        claim,
        {
            "evidence_mismatch": False,
            "evidence_issues": [
                {
                    "field": "Proof document",
                    "reason": "Could not extract readable content from this document",
                    "issue_code": "extraction_failed",
                    "acknowledged": False,
                }
            ],
            "evidence_confidence_score": 0.30,
        },
    )
    assert "extraction_failed" in result.flags
    assert "evidence_mismatch" not in result.flags
    assert "low_evidence_confidence" in result.flags
