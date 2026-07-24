import io
from datetime import datetime, timedelta
from unittest.mock import patch

from models.claim import Claim, ClaimDocument, ClaimStatus, DocumentType
from models.customer import Customer
from models.policy import Policy, PolicyStatus
from dependencies import get_password_hash


def _setup_claim(db_session, status=ClaimStatus.PENDING_REVIEW):
    customer = Customer(
        email="evidence@test.com",
        full_name="Evidence User",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    policy = Policy(
        policy_number="POL-EVID",
        customer_id=customer.id,
        policy_type="Auto",
        status=PolicyStatus.ACTIVE,
        coverage_limit=50000,
        deductible=500,
        co_pay_pct=10,
        exclusions=[],
        waiting_period_days=0,
        effective_date=datetime.utcnow() - timedelta(days=30),
        expiry_date=datetime.utcnow() + timedelta(days=335),
    )
    db_session.add(policy)
    db_session.commit()

    claim = Claim(
        claim_number="CLM-EVID",
        customer_id=customer.id,
        policy_id=policy.id,
        incident_description="Collision damage",
        incident_datetime=datetime.utcnow(),
        location="Austin",
        claim_amount=8000,
        status=status,
        evidence_mismatch=True,
        evidence_issues=[
            {
                "field": "Government ID",
                "document_id": 1,
                "filename": "bad_id.png",
                "reason": "Not a valid ID",
                "issue_code": "evidence_type_mismatch",
                "acknowledged": False,
            }
        ],
    )
    db_session.add(claim)
    db_session.commit()

    doc = ClaimDocument(
        id=1,
        claim_id=claim.id,
        doc_type=DocumentType.GOV_ID,
        file_path="/tmp/bad_id.png",
        original_filename="bad_id.png",
        checksum="oldchecksum",
    )
    db_session.add(doc)
    db_session.commit()
    return customer, claim, doc


@patch("services.evidence_service.ClaimOrchestrator.dispatch_from_step")
@patch("services.evidence_service.ocr_service.extract_text", return_value="valid license text")
def test_replace_evidence_triggers_partial_pipeline(mock_ocr, mock_dispatch, client, db_session):
    customer, claim, doc = _setup_claim(db_session)

    login = client.post("/auth/verify-otp", json={"email": "evidence@test.com", "otp": "112233"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    files = {"file": ("real_id.jpg", io.BytesIO(b"fake-image"), "image/jpeg")}
    data = {"document_id": str(doc.id)}

    response = client.post(
        f"/api/claims/{claim.id}/evidence/replace",
        headers=headers,
        files=files,
        data=data,
    )
    assert response.status_code == 202
    body = response.json()
    assert "document_id" in body
    mock_dispatch.assert_called_once_with(claim.id, "evidence_analysis")

    db_session.refresh(claim)
    assert claim.status == ClaimStatus.PROCESSING


@patch("services.evidence_service.ClaimOrchestrator.dispatch_from_step")
def test_acknowledge_clears_mismatch_and_reprocesses(mock_dispatch, client, db_session):
    customer, claim, doc = _setup_claim(db_session)
    doc.metadata_json = {}
    db_session.commit()

    with patch("services.evidence_service.EvidenceAnalysisService.analyze") as mock_analyze:
        mock_analyze.return_value = type(
            "R",
            (),
            {"evidence_mismatch": False, "evidence_issues": []},
        )()

        login = client.post("/auth/verify-otp", json={"email": "evidence@test.com", "otp": "112233"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            f"/api/claims/{claim.id}/evidence/{doc.id}/acknowledge",
            headers=headers,
            json={"note": "Customer confirmed"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["evidence_mismatch"] is False
        mock_dispatch.assert_called_once_with(claim.id, "evidence_analysis")
