import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from sqlalchemy.orm import joinedload

from config import get_settings
from database import SessionLocal
from models.audit import HumanReview, HumanReviewStatus, AuditLog
from models.claim import Claim, ClaimStatus
from services.customer_profile import CustomerProfileService
from services.decision_engine import DecisionEngine, DecisionInput
from services.evidence_analysis import EvidenceAnalysisService
from services.explainability import ExplainabilityInput, ExplainabilityService
from services.fraud_detection import FraudDetectionService
from services.llm_service import llm_service
from services.notification import NotificationService
from services.escalation_service import EscalationService
from services.llm_payout_service import LLMPayoutService
from services.policy_validation import PolicyValidationService
from services.progress_service import progress_service
from services.expert_queue_service import assign_least_loaded_expert
from services.rag_service import rag_service

logger = logging.getLogger(__name__)
settings = get_settings()


def _get_claim(db, claim_id: int) -> Claim | None:
    return (
        db.query(Claim)
        .options(joinedload(Claim.policy), joinedload(Claim.customer))
        .filter(Claim.id == claim_id)
        .first()
    )


def _run_policy_validation(claim_id: int) -> dict[str, Any]:
    progress_service.publish(claim_id, "policy_validation", "running", "Checking that your policy covers this claim...")
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}
        result = PolicyValidationService().validate(db, claim)
        data = {
            "eligible": result.eligible,
            "policy_expired": result.policy_expired,
            "premium_unpaid": result.premium_unpaid,
            "incident_excluded": result.incident_excluded,
            "violations": result.violations,
            "policy_match_score": 1.0 if result.eligible else 0.3,
        }
        progress_service.publish(
            claim_id,
            "policy_validation",
            "completed",
            f"Policy check complete — {'eligible' if result.eligible else 'issues found'}",
            data,
        )
        return data
    finally:
        db.close()


def _run_rag_retrieval(claim_id: int) -> dict[str, Any]:
    progress_service.publish(claim_id, "rag_retrieval", "running", "Finding relevant sections in your policy...")
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}

        query = claim.incident_description
        ctx = claim.policy_context_json or {}
        if ctx.get("coverage_summary"):
            query += f" {ctx['coverage_summary']}"
        if ctx.get("llm_analysis"):
            query += f" {ctx['llm_analysis'][:500]}"

        clauses = rag_service.retrieve(query, top_k=5, policy_id=claim.policy_id)
        clause_dicts = rag_service.to_dict_list(clauses)
        clarity = rag_service.clause_clarity_score(clauses)

        llm_coverage = llm_service.analyze_incident_coverage(
            claim.incident_description,
            claim.claim_amount,
            clause_dicts,
            claim.policy.policy_type if claim.policy else "Auto",
        )
        if ctx.get("key_sections"):
            llm_coverage["policy_context_sections"] = ctx["key_sections"]
        if llm_coverage.get("confidence"):
            clarity = max(clarity, float(llm_coverage["confidence"]))

        data = {
            "retrieved_clauses": clause_dicts,
            "clause_clarity_score": clarity,
            "llm_coverage": llm_coverage,
        }
        refs = [c.get("section_ref", "") for c in clause_dicts[:3]]
        progress_service.publish(
            claim_id,
            "rag_retrieval",
            "completed",
            f"Found {len(clause_dicts)} relevant policy sections: {', '.join(refs) or 'none'}",
            data,
        )
        return data
    finally:
        db.close()


def _run_customer_profile(claim_id: int) -> dict[str, Any]:
    progress_service.publish(claim_id, "customer_profile", "running", "Reviewing your account details...")
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}
        result = CustomerProfileService().analyze(db, claim)
        data = {
            "customer_risk_score": result.customer_risk_score,
            "prior_claims_count": result.prior_claims_count,
            "signals": result.signals,
        }
        progress_service.publish(
            claim_id,
            "customer_profile",
            "completed",
            f"Account review complete — risk score {result.customer_risk_score:.0%}",
            data,
        )
        return data
    finally:
        db.close()


def _run_evidence_analysis(claim_id: int) -> dict[str, Any]:
    progress_service.publish(claim_id, "evidence_analysis", "running", "Reading and checking your uploaded documents...")
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}
        service = EvidenceAnalysisService()
        result = service.analyze(db, claim)
        data = {
            "evidence_confidence_score": result.evidence_confidence_score,
            "evidence_missing": result.evidence_missing,
            "evidence_results": service.to_dict_list(result),
            "duplicate_uploads": result.duplicate_uploads,
            "evidence_mismatch": result.evidence_mismatch,
            "evidence_issues": result.evidence_issues,
        }
        progress_service.publish(
            claim_id,
            "evidence_analysis",
            "completed",
            f"Document review complete — {result.evidence_confidence_score:.0%} confidence",
            data,
        )
        return data
    finally:
        db.close()


def _run_fraud_detection(claim_id: int, evidence_data: dict) -> dict[str, Any]:
    progress_service.publish(claim_id, "fraud_detection", "running", "Running routine safety checks...")
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}

        from services.evidence_analysis import EvidenceAnalysisResult, DocumentValidationResult

        doc_results = [
            DocumentValidationResult(
                document_id=d.get("document_id"),
                doc_type=d.get("doc_type", ""),
                filename=d.get("filename", ""),
                ocr_text=d.get("ocr_text", d.get("ocr_excerpt", "")),
                confidence=float(d.get("confidence", 0.0)),
                issues=d.get("issues", []),
                issue_codes=d.get("issue_codes", []),
                type_mismatch=bool(
                    d.get("type_mismatch", not d.get("valid", True))
                ),
                mismatch_reason=d.get("mismatch_reason", ""),
            )
            for d in evidence_data.get("evidence_results", [])
        ]
        duplicate_uploads = evidence_data.get("duplicate_uploads", [])
        if isinstance(duplicate_uploads, int):
            duplicate_uploads = [""] * duplicate_uploads
        evidence_result = EvidenceAnalysisResult(
            evidence_confidence_score=evidence_data.get("evidence_confidence_score", 0),
            evidence_missing=evidence_data.get("evidence_missing", False),
            document_results=doc_results,
            duplicate_uploads=duplicate_uploads,
            evidence_mismatch=evidence_data.get("evidence_mismatch", False),
            evidence_issues=evidence_data.get("evidence_issues", []),
        )

        rule_result = FraudDetectionService().detect(db, claim, evidence_result)
        evidence_summary = "; ".join(
            f"{d.filename}: {'invalid' if d.type_mismatch or d.issues else 'valid'}"
            for d in doc_results[:3]
        )
        llm_fraud = llm_service.analyze_fraud_risk(
            claim.incident_description,
            claim.claim_amount,
            rule_result.signals,
            evidence_summary,
        )
        fraud_score = rule_result.fraud_score
        if llm_fraud.get("fraud_score") is not None:
            fraud_score = round((fraud_score + float(llm_fraud["fraud_score"])) / 2, 4)

        rule_result.fraud_score = fraud_score
        if llm_fraud.get("rationale"):
            rule_result.signals.append(f"LLM: {llm_fraud['rationale'][:200]}")

        FraudDetectionService().persist(db, claim_id, rule_result)
        data = {
            "fraud_score": fraud_score,
            "signals": rule_result.signals,
            "blacklist_hit": rule_result.blacklist_hit,
            "llm_fraud": llm_fraud,
        }
        progress_service.publish(
            claim_id,
            "fraud_detection",
            "completed",
            f"Safety checks complete — score {fraud_score:.0%}",
            data,
        )
        return data
    finally:
        db.close()


def finalize_claim(claim_id: int, parallel_results: list[dict]) -> dict[str, Any]:
    progress_service.publish(claim_id, "decision_engine", "running", "Preparing your claim assessment...")
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}

        merged: dict[str, Any] = {}
        for item in parallel_results:
            merged.update(item)

        explainability = ExplainabilityService()
        explainability.log_audit(db, claim_id, "PARALLEL_ANALYSIS_COMPLETE", merged)

        exp_input = ExplainabilityInput(
            retrieved_clauses=merged.get("retrieved_clauses", []),
            evidence_results=merged.get("evidence_results", []),
            fraud_score=merged.get("fraud_score", 0.0),
            policy_match_score=merged.get("policy_match_score", 1.0),
            evidence_confidence=merged.get("evidence_confidence_score", 1.0),
            customer_risk_score=merged.get("customer_risk_score", 0.0),
            clause_clarity_score=merged.get("clause_clarity_score", 1.0),
        )

        confidence = explainability.compute_confidence(exp_input)

        escalation = EscalationService().evaluate(claim, merged)
        claim.escalation_flags = escalation.flags
        claim.escalation_messages = escalation.messages
        claim.evidence_mismatch = bool(merged.get("evidence_mismatch", False))
        claim.evidence_issues = merged.get("evidence_issues", [])
        db.commit()

        decision = DecisionEngine().decide(
            DecisionInput(
                policy_expired=merged.get("policy_expired", False),
                premium_unpaid=merged.get("premium_unpaid", False),
                incident_excluded=merged.get("incident_excluded", False),
                evidence_missing=merged.get("evidence_missing", False),
                fraud_score=merged.get("fraud_score", 0.0),
                claim_amount=claim.claim_amount,
                confidence_score=confidence,
                evidence_confidence_score=merged.get("evidence_confidence_score", 1.0),
                fraud_threshold=settings.fraud_escalate_threshold,
                fraud_review_threshold=settings.fraud_review_threshold,
                evidence_review_threshold=settings.evidence_review_threshold,
                human_review_amount_threshold=settings.human_review_amount_threshold,
                confidence_review_threshold=settings.confidence_review_threshold,
                escalation_flags=escalation.flags,
                escalation_messages=escalation.messages,
            )
        )

        payable_amount = 0.0
        payout_breakdown: dict = {}
        if decision.status == ClaimStatus.APPROVED:
            progress_service.publish(claim_id, "payout_calculation", "running", "Calculating payout amount...")
            llm_payout = LLMPayoutService().calculate(
                claim, claim.policy, merged.get("retrieved_clauses", [])
            )
            payable_amount = llm_payout.payable_amount
            payout_breakdown = llm_payout.breakdown
            progress_service.publish(
                claim_id,
                "payout_calculation",
                "completed",
                f"Payable amount: ${payable_amount:,.2f}",
                {"payable_amount": payable_amount, "breakdown": payout_breakdown},
            )
        elif decision.status == ClaimStatus.PENDING_REVIEW:
            progress_service.publish(
                claim_id,
                "decision_engine",
                "running",
                f"Escalation flags: {', '.join(escalation.flags) or 'none'}",
                {"escalation_flags": escalation.flags, "messages": escalation.messages},
            )

        exp_result = explainability.build_result(
            exp_input,
            status=decision.status,
            policy_violations=merged.get("violations", []),
            payable_amount=payable_amount,
        )

        llm_reasoning = llm_service.generate_decision_reasoning(
            decision.status.value,
            {
                "policy_violations": merged.get("violations", []),
                "retrieved_clauses": merged.get("retrieved_clauses", []),
                "evidence_confidence": exp_input.evidence_confidence,
                "fraud_score": exp_input.fraud_score,
                "confidence_score": confidence,
                "payable_amount": payable_amount,
                "customer_risk_score": exp_input.customer_risk_score,
                "policy_context": claim.policy_context_json or {},
                "escalation_flags": escalation.flags,
            },
        )
        if llm_reasoning:
            exp_result.reasoning = llm_reasoning

        explainability.persist_decision(
            db,
            claim,
            decision.status,
            exp_result,
            payable_amount,
            decision.human_review_required,
            full_clauses=merged.get("retrieved_clauses", []),
            payout_breakdown=payout_breakdown,
        )

        if claim.assigned_agent_id is None and decision.status in (
            ClaimStatus.ANALYSIS_COMPLETE,
            ClaimStatus.PENDING_REVIEW,
        ):
            assign_least_loaded_expert(db, claim)

        if decision.human_review_required:
            reason = decision.reasoning
            if escalation.messages:
                reason = "; ".join(escalation.messages)
            db.add(
                HumanReview(
                    claim_id=claim.id,
                    reason=reason,
                    status=HumanReviewStatus.PENDING,
                )
            )
            db.commit()

        result = {
            "claim_id": claim.claim_number,
            "status": decision.status.value,
            "payable_amount": payable_amount,
            "fraud_score": exp_result.fraud_score,
            "confidence_score": exp_result.confidence_score,
            "retrieved_clauses": exp_result.retrieved_clauses,
            "reasoning": exp_result.reasoning,
            "human_review_required": decision.human_review_required,
            "escalation_flags": escalation.flags,
            "escalation_messages": escalation.messages,
        }

        explainability.log_audit(db, claim_id, "DECISION_GENERATED", result)
        progress_service.publish(
            claim_id,
            "decision_engine",
            "completed",
            f"Decision: {decision.status.value} — {exp_result.reasoning[:120]}",
            result,
        )

        if decision.status in (
            ClaimStatus.APPROVED,
            ClaimStatus.REJECTED,
            ClaimStatus.REQUEST_MORE_INFO,
            ClaimStatus.PENDING_REVIEW,
        ):
            NotificationService().notify_customer(db, claim, claim.status)

        progress_service.publish(
            claim_id,
            "completed",
            "completed",
            f"Claim processing finished — {decision.status.value}",
            result,
        )
        return result
    finally:
        db.close()


def _load_cached_early_steps(claim_id: int) -> dict[str, dict[str, Any]]:
    """Load policy/rag/customer results from last audit or re-run silently."""
    db = SessionLocal()
    try:
        log = (
            db.query(AuditLog)
            .filter(AuditLog.claim_id == claim_id, AuditLog.event_type == "PARALLEL_ANALYSIS_COMPLETE")
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        if log and isinstance(log.payload, dict):
            p = log.payload
            policy_keys = {
                "eligible", "policy_expired", "premium_unpaid", "incident_excluded",
                "violations", "policy_match_score",
            }
            rag_keys = {"retrieved_clauses", "clause_clarity_score", "llm_coverage"}
            customer_keys = {"customer_risk_score", "prior_claims_count", "signals"}
            policy = {k: p[k] for k in policy_keys if k in p}
            rag = {k: p[k] for k in rag_keys if k in p}
            customer = {k: p[k] for k in customer_keys if k in p}
            if policy and rag and customer:
                return {"policy": policy, "rag": rag, "customer": customer}
    finally:
        db.close()

    return {
        "policy": _run_policy_validation_silent(claim_id),
        "rag": _run_rag_retrieval_silent(claim_id),
        "customer": _run_customer_profile_silent(claim_id),
    }


def _run_policy_validation_silent(claim_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}
        result = PolicyValidationService().validate(db, claim)
        return {
            "eligible": result.eligible,
            "policy_expired": result.policy_expired,
            "premium_unpaid": result.premium_unpaid,
            "incident_excluded": result.incident_excluded,
            "violations": result.violations,
            "policy_match_score": 1.0 if result.eligible else 0.3,
        }
    finally:
        db.close()


def _run_rag_retrieval_silent(claim_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}
        query = claim.incident_description
        ctx = claim.policy_context_json or {}
        if ctx.get("coverage_summary"):
            query += f" {ctx['coverage_summary']}"
        if ctx.get("llm_analysis"):
            query += f" {ctx['llm_analysis'][:500]}"
        clauses = rag_service.retrieve(query, top_k=5, policy_id=claim.policy_id)
        clause_dicts = rag_service.to_dict_list(clauses)
        clarity = rag_service.clause_clarity_score(clauses)
        llm_coverage = llm_service.analyze_incident_coverage(
            claim.incident_description,
            claim.claim_amount,
            clause_dicts,
            claim.policy.policy_type if claim.policy else "Auto",
        )
        if llm_coverage.get("confidence"):
            clarity = max(clarity, float(llm_coverage["confidence"]))
        return {
            "retrieved_clauses": clause_dicts,
            "clause_clarity_score": clarity,
            "llm_coverage": llm_coverage,
        }
    finally:
        db.close()


def _run_customer_profile_silent(claim_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if not claim:
            return {"error": "claim not found"}
        result = CustomerProfileService().analyze(db, claim)
        return {
            "customer_risk_score": result.customer_risk_score,
            "prior_claims_count": result.prior_claims_count,
            "signals": result.signals,
        }
    finally:
        db.close()


def _handle_pipeline_failure(claim_id: int, exc: Exception, step: str = "decision_engine") -> dict[str, Any]:
    logger.exception("Pipeline failed for claim %s", claim_id)
    progress_service.publish(
        claim_id,
        step,
        "failed",
        f"Processing error: {str(exc)[:180]}",
        {"error": str(exc)},
    )
    db = SessionLocal()
    try:
        claim = _get_claim(db, claim_id)
        if claim and claim.decision is None:
            claim.status = ClaimStatus.PENDING
            db.commit()
    finally:
        db.close()
    return {"error": str(exc), "claim_id": claim_id}


def run_claim_pipeline_from(claim_id: int, from_step: str = "claim_submitted") -> dict[str, Any]:
    try:
        if from_step == "claim_submitted":
            return run_claim_pipeline(claim_id)

        db = SessionLocal()
        run_id = 0
        try:
            claim = _get_claim(db, claim_id)
            if claim:
                claim.status = ClaimStatus.PROCESSING
                run_id = (claim.pipeline_run_id or 0) + 1
                claim.pipeline_run_id = run_id
                db.commit()
        finally:
            db.close()

        progress_service.publish(
            claim_id,
            "pipeline_reset",
            "running",
            "Re-analyzing from Evidence Analysis...",
            {"from_step": from_step},
            run_id=run_id,
        )

        cached = _load_cached_early_steps(claim_id)
        evidence_result = _run_evidence_analysis(claim_id)
        fraud_result = _run_fraud_detection(claim_id, evidence_result)
        rag_result = _run_rag_retrieval(claim_id)
        merged = [
            cached.get("policy", {}),
            rag_result,
            cached.get("customer", {}),
            evidence_result,
            fraud_result,
        ]
        return finalize_claim(claim_id, merged)
    except Exception as exc:
        return _handle_pipeline_failure(claim_id, exc, step="evidence_analysis")


def run_claim_pipeline(claim_id: int) -> dict[str, Any]:
    try:
        db = SessionLocal()
        try:
            claim = _get_claim(db, claim_id)
            if claim:
                claim.status = ClaimStatus.PROCESSING
                db.commit()
        finally:
            db.close()

        progress_service.publish(claim_id, "claim_submitted", "completed", "Claim received — starting review")

        parallel_tasks = {
            "policy": _run_policy_validation,
            "rag": _run_rag_retrieval,
            "customer": _run_customer_profile,
            "evidence": _run_evidence_analysis,
        }

        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fn, claim_id): name for name, fn in parallel_tasks.items()}
            for future in as_completed(futures):
                name = futures[future]
                results[name] = future.result()

        fraud_result = _run_fraud_detection(claim_id, results.get("evidence", {}))
        merged = [
            results.get("policy", {}),
            results.get("rag", {}),
            results.get("customer", {}),
            results.get("evidence", {}),
            fraud_result,
        ]
        return finalize_claim(claim_id, merged)
    except Exception as exc:
        return _handle_pipeline_failure(claim_id, exc)
