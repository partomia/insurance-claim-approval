"""Expert-requested document types and fulfillment helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from models.claim import ClaimDocument, DocumentType

DOCUMENT_TYPE_LABELS: dict[str, str] = {
    DocumentType.DRIVER_LICENSE.value: "Driver's licence",
    DocumentType.DAMAGE_PHOTO.value: "Damage photo",
    DocumentType.REPAIR_ESTIMATE.value: "Repair estimate / garage invoice",
    DocumentType.POLICE_REPORT.value: "Police / FIR report",
    DocumentType.VEHICLE_REGISTRATION.value: "Vehicle registration (RC)",
    DocumentType.TOWING_INVOICE.value: "Towing invoice",
    DocumentType.THIRD_PARTY_STATEMENT.value: "Third-party statement",
    DocumentType.POLICY_PAPER.value: "Policy document",
    DocumentType.OTHER.value: "Other document",
}

STANDARD_DOCUMENT_TYPES: list[dict[str, str]] = [
    {"value": key, "label": label} for key, label in DOCUMENT_TYPE_LABELS.items()
]


def document_type_label(doc_type: str) -> str:
    return DOCUMENT_TYPE_LABELS.get(doc_type.upper(), doc_type.replace("_", " ").title())


def normalize_requested_documents(raw: Iterable[str]) -> list[dict[str, str]]:
    """Turn expert selections into structured upload targets."""
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    for entry in raw:
        text = (entry or "").strip()
        if not text:
            continue

        upper = text.upper()
        if upper in DocumentType.__members__:
            item_id = upper
            label = document_type_label(upper)
            doc_type = upper
        elif text.lower().startswith("custom:"):
            item_id = text
            label = text[7:].replace("_", " ").strip() or "Additional document"
            doc_type = DocumentType.OTHER.value
        else:
            slug = text.lower().replace(" ", "_")[:48]
            item_id = f"custom:{slug}"
            label = text
            doc_type = DocumentType.OTHER.value

        if item_id in seen:
            continue
        seen.add(item_id)
        items.append({"id": item_id, "label": label, "document_type": doc_type})

    return items


def build_requested_document_items(
    raw: Iterable[str],
    claim_documents: Iterable[ClaimDocument],
    requested_after: Optional[datetime] = None,
) -> list[dict]:
    """Attach fulfillment flags based on uploaded claim documents."""
    docs = list(claim_documents)
    if requested_after is not None:
        docs = [d for d in docs if d.created_at >= requested_after]

    docs_by_type: dict[str, list[ClaimDocument]] = {}
    for doc in docs:
        key = doc.doc_type.value if hasattr(doc.doc_type, "value") else str(doc.doc_type)
        docs_by_type.setdefault(key, []).append(doc)

    used_other_ids: set[int] = set()
    items: list[dict] = []

    for spec in normalize_requested_documents(raw):
        doc_type = spec["document_type"]
        fulfilled = False

        if doc_type == DocumentType.OTHER.value and spec["id"].startswith("custom:"):
            for doc in docs_by_type.get(DocumentType.OTHER.value, []):
                if doc.id not in used_other_ids:
                    fulfilled = True
                    used_other_ids.add(doc.id)
                    break
        else:
            fulfilled = bool(docs_by_type.get(doc_type))

        items.append({**spec, "fulfilled": fulfilled})

    return items
