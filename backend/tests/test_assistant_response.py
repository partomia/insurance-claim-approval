from models.audit import ClaimDecision
from models.claim import Claim, ClaimStatus
from services.assistant_response_service import (
    AssistantIntent,
    build_template_reply,
    detect_intent,
    enforce_limits,
    slim_rag_lines,
    uses_template_reply,
)
from services.analysis_service import analysis_to_dict


def _sample_claim(*, with_decision: bool = True) -> Claim:
    claim = Claim(
        claim_number="CLM-TEST-1",
        status=ClaimStatus.ANALYSIS_COMPLETE,
        incident_description="Emergency appendectomy hospital stay",
        location="Mumbai",
        claim_amount=5440.0,
    )
    if not with_decision:
        return claim
    decision = ClaimDecision(
        status=ClaimStatus.ANALYSIS_COMPLETE,
        payable_amount=0,
        confidence_score=0.91,
        fraud_score=0.0,
        reasoning="Technical reasoning not for customer.",
        human_review_required=False,
        approval_probability=0.82,
        coverage_estimate=5440.0,
        expected_settlement=4444.0,
        next_best_action="Review and submit claim",
        recommendations=["Your claim looks strong. Review details and submit to your insurer."],
        missing_documents=[],
    )
    claim.decision = decision
    return claim


def test_detect_intent_next_step():
    assert detect_intent("Help me with this next step: Review and submit claim") == AssistantIntent.NEXT_STEP


def test_detect_intent_status():
    assert detect_intent("What is my approval probability?") == AssistantIntent.STATUS


def test_detect_intent_documents():
    assert detect_intent("What documents do I need to upload?") == AssistantIntent.DOCUMENTS


def test_uses_template_reply_when_claim_has_decision():
    claim = _sample_claim()
    assert uses_template_reply(AssistantIntent.NEXT_STEP, claim) is True
    assert uses_template_reply(AssistantIntent.GENERAL, claim) is False


def test_template_matches_analysis_dict():
    claim = _sample_claim()
    analysis = analysis_to_dict(claim.decision, claim)
    reply = build_template_reply(claim, AssistantIntent.STATUS)

    assert "82%" in reply
    assert "4,444" in reply
    assert analysis["next_best_action"] in reply
    assert "**In short:**" in reply
    assert "**Do this next:**" in reply


def test_enforce_limits_truncates_long_text():
    text = " ".join(["word"] * 200)
    trimmed = enforce_limits(text, max_words=50)
    assert len(trimmed.split()) <= 51


def test_slim_rag_lines_bounds_length():
    lines = ["- " + ("x" * 200), "- short"]
    result = slim_rag_lines(lines, max_clauses=2, max_chars=80)
    assert result.count("\n") <= 1
    assert len(result.split("\n")[0]) <= 81
