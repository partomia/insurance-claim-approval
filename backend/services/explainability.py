from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.audit import AuditLog, ClaimDecision
from models.claim import Claim, ClaimStatus


@dataclass
class ExplainabilityInput:
    retrieved_clauses: list[dict[str, Any]] = field(default_factory=list)
    evidence_results: list[dict[str, Any]] = field(default_factory=list)
    fraud_score: float = 0.0
    policy_match_score: float = 1.0
    evidence_confidence: float = 1.0
    customer_risk_score: float = 0.0
    clause_clarity_score: float = 1.0


@dataclass
class ExplainabilityResult:
    confidence_score: float
    reasoning: str
    retrieved_clauses: list[str]
    evidence_results: list[dict[str, Any]]
    fraud_score: float


class ExplainabilityService:
    WEIGHTS = {
        "policy_match": 0.30,
        "evidence": 0.30,
        "customer_risk": 0.20,
        "clause_clarity": 0.20,
    }

    def compute_confidence(self, inputs: ExplainabilityInput) -> float:
        customer_component = 1.0 - inputs.customer_risk_score
        score = (
            self.WEIGHTS["policy_match"] * inputs.policy_match_score
            + self.WEIGHTS["evidence"] * inputs.evidence_confidence
            + self.WEIGHTS["customer_risk"] * customer_component
            + self.WEIGHTS["clause_clarity"] * inputs.clause_clarity_score
        )
        return round(min(max(score, 0.0), 1.0), 4)

    def generate_reasoning(
        self,
        status: ClaimStatus,
        inputs: ExplainabilityInput,
        policy_violations: list[str],
        payable_amount: float = 0.0,
    ) -> str:
        parts: list[str] = []
        if policy_violations:
            parts.append(f"Policy issues: {'; '.join(policy_violations)}.")
        if inputs.retrieved_clauses:
            refs = ", ".join(c.get("section_ref", "Unknown") for c in inputs.retrieved_clauses[:3])
            parts.append(f"Relevant policy sections: {refs}.")
        if inputs.evidence_results:
            passed = sum(
                1
                for e in inputs.evidence_results
                if e.get("valid")
                or (not e.get("type_mismatch") and float(e.get("confidence", 0)) >= 0.5)
            )
            parts.append(f"Evidence validation: {passed}/{len(inputs.evidence_results)} documents passed.")
        parts.append(f"Fraud score: {inputs.fraud_score:.2f}.")
        if status == ClaimStatus.APPROVED:
            parts.append(f"Approved payable amount: {payable_amount:,.2f}.")
        elif status == ClaimStatus.REJECTED:
            parts.append("Claim rejected based on policy rules and evidence review.")
        elif status in (ClaimStatus.HUMAN_REVIEW, ClaimStatus.ESCALATE, ClaimStatus.PENDING_REVIEW):
            parts.append("Routed to human review for final determination.")
        elif status == ClaimStatus.REQUEST_MORE_INFO:
            parts.append("Additional documentation requested from customer.")
        return " ".join(parts)

    def build_result(self, inputs: ExplainabilityInput, **kwargs) -> ExplainabilityResult:
        confidence = self.compute_confidence(inputs)
        status = kwargs.get("status", ClaimStatus.PENDING)
        reasoning = self.generate_reasoning(
            status=status,
            inputs=inputs,
            policy_violations=kwargs.get("policy_violations", []),
            payable_amount=kwargs.get("payable_amount", 0.0),
        )
        return ExplainabilityResult(
            confidence_score=confidence,
            reasoning=reasoning,
            retrieved_clauses=[c.get("section_ref", "") for c in inputs.retrieved_clauses],
            evidence_results=inputs.evidence_results,
            fraud_score=inputs.fraud_score,
        )

    def persist_decision(
        self,
        db: Session,
        claim: Claim,
        status: ClaimStatus,
        result: ExplainabilityResult,
        payable_amount: float,
        human_review_required: bool,
        full_clauses: Optional[list[dict]] = None,
        payout_breakdown: Optional[dict] = None,
    ) -> ClaimDecision:
        decision = db.query(ClaimDecision).filter(ClaimDecision.claim_id == claim.id).first()
        if decision is None:
            decision = ClaimDecision(claim_id=claim.id)
            db.add(decision)

        decision.status = status
        decision.payable_amount = payable_amount
        decision.confidence_score = result.confidence_score
        decision.reasoning = result.reasoning
        decision.retrieved_clauses = full_clauses or [
            {"section_ref": ref} for ref in result.retrieved_clauses
        ]
        decision.evidence_results = result.evidence_results
        decision.fraud_score = result.fraud_score
        decision.human_review_required = human_review_required
        if payout_breakdown is not None:
            decision.payout_breakdown = payout_breakdown

        analysis_fields = __import__(
            "services.analysis_service", fromlist=["compute_analysis_fields"]
        ).compute_analysis_fields(claim, decision, payable_amount)
        for key, value in analysis_fields.items():
            setattr(decision, key, value)

        claim.status = status
        db.commit()
        db.refresh(decision)
        return decision

    def log_audit(
        self,
        db: Session,
        claim_id: int,
        event_type: str,
        payload: dict,
        actor: str = "system",
    ) -> AuditLog:
        log = AuditLog(claim_id=claim_id, event_type=event_type, payload=payload, actor=actor)
        db.add(log)
        db.commit()
        return log

    def build_audit_report(self, db: Session, claim: Claim) -> dict:
        decision = claim.decision
        fraud = claim.fraud_assessment
        audit_trail = (
            db.query(AuditLog)
            .filter(AuditLog.claim_id == claim.id)
            .order_by(AuditLog.timestamp.asc())
            .all()
        )
        customer_name = claim.customer.full_name if claim.customer else "Unknown"
        policy = claim.policy
        documents = sorted(claim.documents or [], key=lambda d: d.created_at)
        issues_raw = claim.evidence_issues if isinstance(claim.evidence_issues, list) else []
        flags = claim.escalation_flags if isinstance(claim.escalation_flags, list) else []
        messages = claim.escalation_messages if isinstance(claim.escalation_messages, list) else []
        if flags and not messages:
            from services.escalation_service import EscalationService

            messages = EscalationService().build_messages(flags, {})

        return {
            "claim_id": claim.claim_number,
            "claim_number": claim.claim_number,
            "status": claim.status.value,
            "claim_details": {
                "incident_description": claim.incident_description,
                "incident_datetime": claim.incident_datetime.isoformat(),
                "location": claim.location,
                "claim_amount": claim.claim_amount,
                "customer_name": customer_name,
                "policy_number": policy.policy_number if policy else None,
                "policy_type": policy.policy_type if policy else None,
            },
            "documents": [
                {
                    "id": doc.id,
                    "doc_type": doc.doc_type.value,
                    "filename": doc.original_filename,
                    "uploaded_at": doc.created_at.isoformat(),
                }
                for doc in documents
            ],
            "escalation_flags": flags,
            "escalation_messages": messages,
            "evidence_issues": issues_raw,
            "decision": {
                "status": decision.status.value if decision else None,
                "payable_amount": decision.payable_amount if decision else 0,
                "confidence_score": decision.confidence_score if decision else 0,
                "fraud_score": decision.fraud_score if decision else 0,
                "reasoning": decision.reasoning if decision else "",
                "retrieved_clauses": decision.retrieved_clauses if decision else [],
                "evidence_results": decision.evidence_results if decision else [],
                "human_review_required": decision.human_review_required if decision else False,
            }
            if decision
            else None,
            "fraud_assessment": {
                "fraud_score": fraud.fraud_score,
                "signals": fraud.signals,
                "blacklist_hit": fraud.blacklist_hit,
            }
            if fraud
            else None,
            "evidence_results": decision.evidence_results if decision else [],
            "retrieved_clauses": decision.retrieved_clauses if decision else [],
            "audit_trail": [
                {
                    "event_type": log.event_type,
                    "payload": log.payload,
                    "actor": log.actor,
                    "timestamp": log.timestamp.isoformat(),
                }
                for log in audit_trail
            ],
        }
