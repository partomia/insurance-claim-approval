from datetime import datetime

from models.claim import ClaimDocument, DocumentType
from services.document_request_service import build_requested_document_items, normalize_requested_documents


def test_normalize_requested_documents():
    items = normalize_requested_documents(["MEDICAL", "Lab reports", "MEDICAL"])
    assert len(items) == 2
    assert items[0]["document_type"] == "MEDICAL"
    assert items[1]["label"] == "Lab reports"
    assert items[1]["document_type"] == "OTHER"


def test_fulfilled_when_matching_document_exists():
    docs = [
        ClaimDocument(
            claim_id=1,
            doc_type=DocumentType.MEDICAL,
            file_path="/tmp/a.pdf",
            original_filename="a.pdf",
            checksum="abc",
            created_at=datetime.utcnow(),
        )
    ]
    items = build_requested_document_items(["MEDICAL", "INVOICE"], docs)
    assert items[0]["fulfilled"] is True
    assert items[1]["fulfilled"] is False
