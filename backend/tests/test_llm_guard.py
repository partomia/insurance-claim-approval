from services import llm_guard


def test_redact_keeps_identifiers_out_of_prompts():
    text = "Mail a.b@x.in, call +91 9876543210, PAN ABCDE1234F, Aadhaar 1234 5678 9012, VIN MA044CKYYHDTGB23C"
    out = llm_guard.redact(text)
    for token in ("[email]", "[phone]", "[pan]", "[aadhaar]", "[vin]"):
        assert token in out
    assert "9876543210" not in out and "a.b@x.in" not in out
    assert llm_guard.redact("Claim amount: 42000.0 IDV 634000") == "Claim amount: 42000.0 IDV 634000"


def test_grounded_drops_contradictions_and_placeholders():
    assert llm_guard.grounded("APPROVED", "The claim is approved under section 2.1.")[0]
    assert not llm_guard.grounded("APPROVED", "The claim was rejected as the policy lapsed.")[0]
    assert not llm_guard.grounded("REJECTED", "Approved: the payout will be paid.")[0]
    assert not llm_guard.grounded("PENDING_REVIEW", "Payable amount is [IDV] minus deductible.")[0]
    assert llm_guard.grounded("PENDING_REVIEW", "Routed to a reviewer; not yet approved or rejected.")[0]
    assert llm_guard.checked_reasoning("APPROVED", "Rejected outright.") == ""
    assert llm_guard.checked_reasoning("APPROVED", "") == ""
