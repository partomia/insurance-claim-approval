from collections import Counter
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.policy import Policy, PremiumPayment, PremiumPaymentStatus
from models.policy_agent import PolicyAgent
from services.dashboard_service import DashboardService, STATUS_LABELS
from services.escalation_service import EscalationService
from services.policy_service import document_count


class AgentService:
    def _assigned_query(self, db: Session, agent_id: int):
        return (
            db.query(Claim)
            .options(
                joinedload(Claim.customer),
                joinedload(Claim.policy),
                joinedload(Claim.decision),
                joinedload(Claim.documents),
            )
            .filter(Claim.assigned_agent_id == agent_id)
            .order_by(Claim.assigned_at.desc().nullslast(), Claim.created_at.desc())
        )

    def claim_to_item(self, claim: Claim) -> dict[str, Any]:
        approval = None
        if claim.decision:
            approval = claim.decision.approval_probability or claim.decision.confidence_score
        issues_raw = claim.evidence_issues if isinstance(claim.evidence_issues, list) else []
        doc_count = len(claim.documents or []) if hasattr(claim, "documents") and claim.documents else 0
        flags = claim.escalation_flags if isinstance(claim.escalation_flags, list) else []
        messages = claim.escalation_messages if isinstance(claim.escalation_messages, list) else []
        if flags and not messages:
            messages = EscalationService().build_messages(flags, {})
        return {
            "id": claim.id,
            "claim_id": claim.claim_number,
            "status": claim.status.value,
            "claim_amount": claim.claim_amount,
            "customer_id": claim.customer_id,
            "customer_name": claim.customer.full_name if claim.customer else "",
            "customer_email": claim.customer.email if claim.customer else "",
            "policy_type": claim.policy.policy_type if claim.policy else None,
            "escalation_flags": flags,
            "escalation_messages": messages,
            "assigned_at": claim.assigned_at,
            "created_at": claim.created_at,
            "approval_probability": approval,
            "fraud_score": claim.decision.fraud_score if claim.decision else None,
            "document_count": doc_count,
            "has_document_issues": len(issues_raw) > 0,
        }

    def get_dashboard_stats(self, db: Session, agent: PolicyAgent) -> dict[str, Any]:
        claims = self._assigned_query(db, agent.id).all()
        status_counts = Counter(c.status for c in claims)
        by_customer: Counter[int] = Counter()
        customer_names: dict[int, str] = {}
        for claim in claims:
            by_customer[claim.customer_id] += 1
            if claim.customer:
                customer_names[claim.customer_id] = claim.customer.full_name

        approval_scores = [
            c.decision.approval_probability or c.decision.confidence_score
            for c in claims
            if c.decision
        ]

        return {
            "assigned_total": len(claims),
            "pending_review": sum(
                1 for c in claims if c.status in (ClaimStatus.PENDING_REVIEW, ClaimStatus.HUMAN_REVIEW)
            ),
            "submission_ready": status_counts.get(ClaimStatus.SUBMISSION_READY, 0),
            "needs_improvement": status_counts.get(ClaimStatus.REQUEST_MORE_INFO, 0),
            "avg_approval_probability": round(sum(approval_scores) / len(approval_scores), 3) if approval_scores else 0.0,
            "claims_by_status": [
                {
                    "status": status.value,
                    "label": STATUS_LABELS.get(status, status.value),
                    "count": count,
                }
                for status, count in sorted(status_counts.items(), key=lambda x: x[0].value)
                if count > 0
            ],
            "claims_by_customer": [
                {"customer_id": cid, "customer_name": customer_names.get(cid, ""), "count": count}
                for cid, count in by_customer.most_common()
            ],
        }

    def list_claims(
        self,
        db: Session,
        agent: PolicyAgent,
        *,
        status: Optional[str] = None,
        customer_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        query = self._assigned_query(db, agent.id)
        if status:
            try:
                query = query.filter(Claim.status == ClaimStatus(status.upper()))
            except ValueError:
                pass
        if customer_id is not None:
            query = query.filter(Claim.customer_id == customer_id)
        return [self.claim_to_item(c) for c in query.all()]

    def list_customers(self, db: Session, agent: PolicyAgent) -> list[dict[str, Any]]:
        claims = self._assigned_query(db, agent.id).all()
        seen: dict[int, dict[str, Any]] = {}
        for claim in claims:
            if not claim.customer:
                continue
            cid = claim.customer_id
            if cid not in seen:
                seen[cid] = {
                    "id": cid,
                    "full_name": claim.customer.full_name,
                    "email": claim.customer.email,
                    "assigned_claims_count": 0,
                }
            seen[cid]["assigned_claims_count"] += 1
        return list(seen.values())

    def get_customer_detail(self, db: Session, agent: PolicyAgent, customer_id: int) -> Optional[dict[str, Any]]:
        claims = (
            self._assigned_query(db, agent.id)
            .filter(Claim.customer_id == customer_id)
            .all()
        )
        if not claims:
            return None
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return None

        policies = db.query(Policy).filter(Policy.customer_id == customer_id).all()
        policy_summaries = []
        for policy in policies:
            latest_payment = (
                db.query(PremiumPayment)
                .filter(PremiumPayment.policy_id == policy.id)
                .order_by(PremiumPayment.paid_at.desc())
                .first()
            )
            premium_status = latest_payment.status.value if latest_payment else PremiumPaymentStatus.PAID.value
            policy_summaries.append(
                {
                    "id": policy.id,
                    "policy_number": policy.policy_number,
                    "policy_type": policy.policy_type,
                    "status": policy.status.value,
                    "coverage_limit": policy.coverage_limit,
                    "deductible": policy.deductible,
                    "co_pay_pct": policy.co_pay_pct,
                    "exclusions": policy.exclusions or [],
                    "premium_status": premium_status,
                    "effective_date": policy.effective_date,
                    "expiry_date": policy.expiry_date,
                    "document_count": document_count(db, policy.id),
                }
            )

        risk = None
        if claims:
            from services.customer_profile import CustomerProfileService

            risk_result = CustomerProfileService().analyze(db, claims[0])
            risk = {
                "customer_risk_score": risk_result.customer_risk_score,
                "prior_claims_count": risk_result.prior_claims_count,
                "policy_tenure_days": risk_result.policy_tenure_days,
                "signals": risk_result.signals,
            }

        return {
            "id": customer.id,
            "full_name": customer.full_name,
            "email": customer.email,
            "policies": policy_summaries,
            "assigned_claims": [self.claim_to_item(c) for c in claims],
            "customer_risk": risk,
        }

    def get_customer_insights(self, db: Session, agent: PolicyAgent, customer_id: int) -> dict[str, Any]:
        if not self._assigned_query(db, agent.id).filter(Claim.customer_id == customer_id).first():
            return {}
        return DashboardService().get_stats(db, customer_id)

    def get_assigned_claim(self, db: Session, agent: PolicyAgent, claim_id: int) -> Optional[Claim]:
        return (
            self._assigned_query(db, agent.id)
            .filter(Claim.id == claim_id)
            .first()
        )

    def build_policy_requirements(self, claim: Claim) -> dict[str, Any]:
        ctx = claim.policy_context_json or {}
        decision = claim.decision
        key_clauses: list[dict[str, Any]] = []
        missing: list[str] = []
        matches: list[dict[str, Any]] = []

        if decision:
            missing = list(decision.missing_documents or [])
            matches = list(decision.policy_clause_matches or [])
            refs = decision.retrieved_clauses if isinstance(decision.retrieved_clauses, list) else []
            for ref in refs[:6]:
                if isinstance(ref, dict):
                    key_clauses.append(
                        {
                            "section_ref": ref.get("section_ref", ""),
                            "summary": str(ref.get("summary", ref.get("text", "")))[:120],
                        }
                    )
                else:
                    key_clauses.append({"section_ref": str(ref), "summary": str(ref)[:120]})

        key_sections = ctx.get("key_sections", [])[:6]
        if not key_clauses and key_sections:
            for section in key_sections:
                if isinstance(section, dict):
                    key_clauses.append(
                        {
                            "section_ref": section.get("ref", section.get("section_ref", "")),
                            "summary": str(section.get("summary", section.get("content", "")))[:120],
                        }
                    )

        return {
            "claim_id": claim.claim_number,
            "policy_number": claim.policy.policy_number if claim.policy else None,
            "policy_type": claim.policy.policy_type if claim.policy else None,
            "coverage_summary": str(ctx.get("coverage_summary", "")),
            "exclusions": list(ctx.get("exclusions", [])),
            "key_sections": key_sections if isinstance(key_sections, list) else [],
            "key_clauses": key_clauses,
            "missing_documents": missing,
            "policy_clause_matches": matches,
        }

    def list_claim_documents(self, claim: Claim) -> list[dict[str, Any]]:
        issues_raw = claim.evidence_issues if isinstance(claim.evidence_issues, list) else []
        issues_by_doc: dict[int, dict] = {}
        for issue in issues_raw:
            if isinstance(issue, dict) and issue.get("document_id"):
                issues_by_doc[int(issue["document_id"])] = issue

        documents = sorted(claim.documents or [], key=lambda d: d.created_at)
        result = []
        for doc in documents:
            issue = issues_by_doc.get(doc.id)
            result.append(
                {
                    "id": doc.id,
                    "doc_type": doc.doc_type.value,
                    "filename": doc.original_filename,
                    "uploaded_at": doc.created_at,
                    "has_issue": issue is not None,
                    "issue_reason": issue.get("reason") if issue else None,
                }
            )
        return result


agent_service = AgentService()
