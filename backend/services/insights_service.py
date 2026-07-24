from typing import Any

from sqlalchemy.orm import Session, joinedload

from models.claim import Claim
from services.progress_service import progress_service
from services.analysis_service import analysis_to_dict


class InsightsService:
    def build(self, db: Session, claim_id: int) -> dict[str, Any]:
        claim = (
            db.query(Claim)
            .options(joinedload(Claim.policy), joinedload(Claim.decision))
            .filter(Claim.id == claim_id)
            .first()
        )
        if not claim:
            return {}

        policy = claim.policy
        limit = policy.coverage_limit if policy else 1
        claim_amount = claim.claim_amount
        pct = round((claim_amount / limit) * 100, 2) if limit else 0

        decision = claim.decision
        confidence = decision.confidence_score if decision else 0
        fraud = decision.fraud_score if decision else 0
        payable = decision.payable_amount if decision else 0

        ctx = claim.policy_context_json or {}
        key_sections = ctx.get("key_sections", [])

        retrieved_primary = None
        if decision and decision.retrieved_clauses:
            first = decision.retrieved_clauses[0]
            if isinstance(first, dict):
                retrieved_primary = {
                    "ref": first.get("section_ref", ""),
                    "summary": (first.get("clause_text") or first.get("summary", ""))[:200],
                }

        payout_breakdown: dict[str, Any] = {"gross": claim_amount, "deductible": 0, "payable": payable}
        if decision and decision.payout_breakdown:
            payout_breakdown = decision.payout_breakdown
        elif policy and decision and decision.status.value == "APPROVED":
            payout_breakdown["deductible"] = policy.deductible
            payout_breakdown["co_pay_pct"] = policy.co_pay_pct

        policy_summary = {}
        if policy:
            policy_summary = {
                "policy_type": policy.policy_type,
                "coverage_limit": policy.coverage_limit,
                "deductible": policy.deductible,
                "co_pay_pct": policy.co_pay_pct,
            }

        evidence_confidence = 0.0
        if decision and decision.evidence_results:
            scores: list[float] = []
            for e in decision.evidence_results:
                if e.get("confidence") is not None:
                    scores.append(float(e["confidence"]))
                elif e.get("valid") is not None:
                    scores.append(1.0 if e.get("valid") else 0.0)
                elif e.get("type_mismatch"):
                    scores.append(0.25)
                else:
                    scores.append(0.75)
            evidence_confidence = sum(scores) / len(scores) if scores else 0.0

        flags = claim.escalation_flags if isinstance(claim.escalation_flags, list) else []
        messages = claim.escalation_messages if isinstance(claim.escalation_messages, list) else []

        timeline = progress_service.get_history(claim_id)

        return {
            "claim_id": claim.claim_number,
            "status": claim.status.value,
            "coverage_utilization": {
                "claim_amount": claim_amount,
                "limit": limit,
                "pct": pct,
            },
            "score_gauges": {
                "confidence": confidence,
                "approval_probability": decision.approval_probability if decision and decision.approval_probability else confidence * (1 - fraud * 0.35),
                "evidence": evidence_confidence,
            },
            "ai_analysis": analysis_to_dict(decision, claim) if decision else {},
            "payout_breakdown": payout_breakdown,
            "policy_sections": key_sections,
            "retrieved_primary_clause": retrieved_primary,
            "escalation_flags": flags,
            "escalation_messages": messages,
            "assigned_agent": claim.assigned_agent,
            "policy_context_summary": ctx.get("coverage_summary", ""),
            "policy_summary": policy_summary,
            "timeline": [
                {
                    "step": e.get("step"),
                    "label": e.get("label"),
                    "status": e.get("status"),
                    "message": e.get("message"),
                    "at": e.get("timestamp"),
                }
                for e in timeline
            ],
        }
