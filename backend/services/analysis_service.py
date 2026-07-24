"""Build customer-facing AI analysis payload from claim decision data."""

from typing import Any, Optional

from models.audit import ClaimDecision
from models.claim import Claim, ClaimStatus


def _problems_from_decision(claim: Claim, decision: ClaimDecision) -> list[str]:
    if decision.potential_problems:
        return list(decision.potential_problems)

    problems: list[str] = []
    flags = claim.escalation_flags if isinstance(claim.escalation_flags, list) else []
    flag_messages = {
        "missing_documents": "Supporting documents may be incomplete",
        "high_fraud_risk": "Unusual claim patterns detected",
        "evidence_mismatch": "Document details do not match incident description",
        "low_evidence_confidence": "Evidence quality needs improvement",
        "clause_mismatch": "Incident may not match policy coverage clauses",
        "early_high_amount": "Claim amount is high for policy tenure",
    }
    for flag in flags:
        problems.append(flag_messages.get(flag, flag.replace("_", " ").title()))

    if decision.missing_documents:
        for doc in decision.missing_documents:
            if isinstance(doc, str):
                problems.append(f"Missing {doc}")
            elif isinstance(doc, dict):
                problems.append(doc.get("label") or doc.get("name") or "Missing document")

    issues = claim.evidence_issues if isinstance(claim.evidence_issues, list) else []
    for issue in issues[:3]:
        if isinstance(issue, dict) and issue.get("reason"):
            problems.append(str(issue["reason"]))

    return problems[:8]


def _recommendations_from_decision(decision: ClaimDecision) -> list[str]:
    if decision.recommendations:
        return list(decision.recommendations)
    recs: list[str] = []
    if decision.missing_documents:
        for doc in decision.missing_documents:
            label = doc if isinstance(doc, str) else doc.get("label", "document")
            recs.append(f"Upload {label} to strengthen your claim.")
    if decision.human_review_required:
        recs.append("Connect with a Claim Expert for personalized guidance.")
    if not recs and decision.approval_probability and decision.approval_probability >= 0.85:
        recs.append("Your claim looks strong. Review details and submit to your insurer.")
    return recs[:6]


def compute_analysis_fields(
    claim: Claim,
    decision: ClaimDecision,
    payable_amount: float,
) -> dict[str, Any]:
    """Populate AI analysis columns on a ClaimDecision."""
    confidence = float(decision.confidence_score or 0)
    fraud = float(decision.fraud_score or 0)
    approval_prob = round(max(0.0, min(1.0, confidence * (1.0 - fraud * 0.35))), 4)

    limit = claim.policy.coverage_limit if claim.policy else claim.claim_amount
    coverage_estimate = round(min(claim.claim_amount, limit), 2)
    expected_settlement = round(payable_amount if payable_amount > 0 else coverage_estimate * approval_prob, 2)

    missing_docs: list[str] = []
    if decision.evidence_results:
        for ev in decision.evidence_results:
            if not ev.get("valid") and ev.get("doc_type"):
                missing_docs.append(str(ev.get("doc_type")).replace("_", " ").title())

    problems = _problems_from_decision(claim, decision)
    recommendations = _recommendations_from_decision(decision)

    clause_matches = decision.policy_clause_matches or []
    if not clause_matches and decision.retrieved_clauses:
        for clause in decision.retrieved_clauses[:5]:
            if isinstance(clause, dict):
                clause_matches.append(
                    {
                        "section_ref": clause.get("section_ref", ""),
                        "summary": (clause.get("clause_text") or clause.get("summary", ""))[:200],
                        "match_score": round(confidence, 2),
                    }
                )
            else:
                clause_matches.append({"section_ref": str(clause), "summary": "", "match_score": round(confidence, 2)})

    fraud_signals = decision.fraud_signals or []
    if not fraud_signals and fraud > 0.2:
        fraud_signals = [{"signal": "elevated_risk", "severity": "medium", "score": fraud}]

    if claim.status in (ClaimStatus.SUBMISSION_READY, ClaimStatus.ANALYSIS_COMPLETE):
        next_action = "Submit to insurance company"
    elif decision.human_review_required or claim.status == ClaimStatus.PENDING_REVIEW:
        next_action = "Chat with Claim Expert"
    elif problems:
        next_action = "Upload missing documents"
    else:
        next_action = "Review and submit claim"

    return {
        "approval_probability": approval_prob,
        "coverage_estimate": coverage_estimate,
        "expected_settlement": expected_settlement,
        "potential_problems": problems,
        "recommendations": recommendations,
        "missing_documents": missing_docs or list(decision.missing_documents or []),
        "policy_clause_matches": clause_matches,
        "fraud_signals": fraud_signals,
        "next_best_action": next_action,
        "ai_explanation": decision.reasoning,
    }


def format_analysis_context_for_assistant(claim: Claim) -> str:
    """Metrics-only context for LLM — matches Track page without verbose explanation dumps."""
    if not claim.decision:
        return "No AI analysis available yet — claim may still be processing."

    analysis = analysis_to_dict(claim.decision, claim)
    d = claim.decision
    confidence = analysis.get("confidence", d.confidence_score)
    recs = (analysis.get("recommendations") or [])[:2]

    lines = [
        "CUSTOMER-FACING AI ANALYSIS (authoritative — must match Track Claim page):",
        f"- Claim: {claim.claim_number} | Status: {claim.status.value}",
        f"- Approval probability: {round(float(analysis['approval_probability']) * 100)}%",
        f"- Coverage estimate: ${float(analysis['coverage_estimate']):,.2f}",
        f"- Expected settlement: ${float(analysis['expected_settlement']):,.2f}",
        f"- Confidence: {round(float(confidence or 0) * 100)}% | Fraud risk: {round(float(d.fraud_score or 0) * 100)}%",
        f"- Next best action: {analysis.get('next_best_action') or 'Review claim details'}",
    ]
    if recs:
        lines.append(f"- Top recommendations: {'; '.join(str(r) for r in recs)}")
    missing = analysis.get("missing_documents") or []
    if missing:
        lines.append(f"- Missing documents: {', '.join(str(m) for m in missing[:4])}")

    lines.extend(
        [
            "Use these figures when answering. Do not contradict them.",
        ]
    )
    return "\n".join(lines)


def analysis_to_dict(decision: ClaimDecision, claim: Optional[Claim] = None) -> dict[str, Any]:
    approval = decision.approval_probability
    if approval is None:
        approval = round(float(decision.confidence_score or 0) * (1.0 - float(decision.fraud_score or 0) * 0.35), 4)

    return {
        "approval_probability": approval,
        "coverage_estimate": decision.coverage_estimate or (claim.claim_amount if claim else 0),
        "expected_settlement": decision.expected_settlement or decision.payable_amount,
        "confidence": decision.confidence_score,
        "potential_problems": _problems_from_decision(claim, decision) if claim else list(decision.potential_problems or []),
        "recommendations": _recommendations_from_decision(decision),
        "missing_documents": list(decision.missing_documents or []),
        "policy_clause_matches": list(decision.policy_clause_matches or []),
        "fraud_signals": list(decision.fraud_signals or []),
        "next_best_action": decision.next_best_action or "Review claim details",
        "ai_explanation": decision.ai_explanation or decision.reasoning,
        "retrieved_clauses": decision.retrieved_clauses if isinstance(decision.retrieved_clauses, list) else [],
    }
