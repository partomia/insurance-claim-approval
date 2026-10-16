"""Guardrails around the LLM's decision explanation (PLAN.md, Guardrails / LLM).

- redact(): customer identifiers (email, phone, PAN, Aadhaar, VIN) never reach the prompt.
- grounded(): the explanation must point the same way as the rules decision and carry no
  template placeholders; otherwise the caller keeps the deterministic template reasoning.
"""
import logging
import re

logger = logging.getLogger(__name__)

_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[pan]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[aadhaar]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[phone]"),
    (re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"), "[vin]"),
]

_APPROVE = re.compile(r"\b(approved|approve|payable in full|will be paid)\b", re.I)
_REJECT = re.compile(r"\b(rejected|reject|denied|declined|not covered)\b", re.I)
_PLACEHOLDER = re.compile(r"\[(?:[A-Z_ ]{2,}|amount|idv|deductible)\]", re.I)


def redact(text: str) -> str:
    for pattern, token in _PII:
        text = pattern.sub(token, text)
    return text


def grounded(status: str, text: str) -> tuple[bool, str]:
    """(ok, reason) for an explanation of a decision with this status."""
    if not text or not text.strip():
        return False, "empty"
    if _PLACEHOLDER.search(text):
        return False, "placeholder left in the text"
    s = (status or "").upper()
    if s == "APPROVED" and _REJECT.search(text) and not _APPROVE.search(text):
        return False, "explains a rejection for an approved claim"
    if s == "REJECTED" and _APPROVE.search(text) and not _REJECT.search(text):
        return False, "explains an approval for a rejected claim"
    return True, ""


def checked_reasoning(status: str, text: str) -> str:
    """The LLM text if it passes, else "" (the pipeline then keeps the template reasoning)."""
    if not text:
        return ""
    ok, reason = grounded(status, text)
    if not ok:
        logger.warning("LLM decision reasoning dropped (%s): template reasoning kept", reason)
        return ""
    return text
