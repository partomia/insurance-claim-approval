import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_SECTION_NUM_PATTERN = re.compile(r"(\d+(?:\.\d+)*)")


def normalize_section_ref(ref: str) -> str:
    cleaned = (ref or "").split(" (part")[0].strip()
    match = _SECTION_NUM_PATTERN.search(cleaned)
    return match.group(1) if match else cleaned


def sections_related(retrieved_ref: str, expected_ref: str, schedule_refs: list[str]) -> bool:
    retrieved_num = normalize_section_ref(retrieved_ref)
    expected_num = normalize_section_ref(expected_ref)
    if not retrieved_num or not expected_num:
        return True
    if retrieved_num == expected_num:
        return True
    if retrieved_num.split(".")[0] == expected_num.split(".")[0]:
        return True
    schedule_nums = {normalize_section_ref(r) for r in schedule_refs if r}
    return retrieved_num in schedule_nums


class LLMService:
    def __init__(self) -> None:
        self._llm: Optional[ChatGroq] = None

    def _has_valid_key(self) -> bool:
        key = settings.groq_api_key or ""
        return bool(key) and not key.startswith("your_")

    @property
    def llm(self) -> Optional[ChatGroq]:
        if not self._has_valid_key():
            return None
        if self._llm is None:
            self._llm = ChatGroq(
                model=settings.groq_model,
                api_key=settings.groq_api_key,
                temperature=0,
                max_retries=2,
            )
        return self._llm

    def invoke(self, system: str, user: str) -> str:
        if not self.llm:
            return ""
        try:
            response = self.llm.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
            return str(response.content).strip()
        except Exception as exc:
            logger.warning("Groq LLM call failed: %s", exc)
            return ""

    def invoke_assistant(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 280,
        temperature: float = 0,
    ) -> str:
        if not self._has_valid_key():
            return ""
        try:
            llm = ChatGroq(
                model=settings.groq_model,
                api_key=settings.groq_api_key,
                temperature=temperature,
                max_retries=2,
                max_tokens=max_tokens,
            )
            response = llm.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
            content = str(response.content or "").strip()
            if content:
                return content

            finish = (response.response_metadata or {}).get("finish_reason")
            reasoning = (response.additional_kwargs or {}).get("reasoning_content", "")
            if reasoning and max_tokens < 900:
                logger.info("Groq assistant empty content — retrying with higher token budget")
                return self.invoke_assistant(
                    system,
                    user,
                    max_tokens=min(max_tokens * 2, 900),
                    temperature=temperature,
                )

            logger.warning(
                "Groq assistant returned empty content (finish_reason=%s, max_tokens=%s)",
                finish,
                max_tokens,
            )
            return ""
        except Exception as exc:
            logger.warning("Groq assistant call failed: %s", exc)
            return ""

    def invoke_summarize(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0,
    ) -> str:
        return self.invoke_assistant(system, user, max_tokens=max_tokens, temperature=temperature)

    def invoke_json(self, system: str, user: str) -> dict[str, Any]:
        text = self.invoke(
            system + " Return ONLY valid JSON, no markdown fences.",
            user,
        )
        if not text:
            return {}
        cleaned = text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return {}

    def analyze_incident_coverage(
        self,
        incident: str,
        claim_amount: float,
        policy_clauses: list[dict],
        policy_type: str,
    ) -> dict[str, Any]:
        clauses_text = "\n".join(
            f"- {c.get('section_ref', 'Section')}: {c.get('clause_text', '')[:300]}"
            for c in policy_clauses[:5]
        )
        return self.invoke_json(
            "You are an insurance policy analyst. Assess whether the incident is covered.",
            f"""Policy type: {policy_type}
Claim amount: ${claim_amount:,.2f}
Incident: {incident}

Relevant policy clauses:
{clauses_text or 'No clauses retrieved.'}

Return JSON: {{"is_covered": boolean, "confidence": float 0-1, "summary": string}}""",
        )

    def analyze_fraud_risk(
        self,
        incident: str,
        claim_amount: float,
        signals: list[str],
        evidence_summary: str,
    ) -> dict[str, Any]:
        return self.invoke_json(
            "You are an insurance fraud analyst. Assess fraud risk from signals.",
            f"""Incident: {incident}
Claim amount: ${claim_amount:,.2f}
Rule-based signals: {signals or ['none']}
Evidence summary: {evidence_summary}

Return JSON: {{"fraud_score": float 0-1, "risk_level": "Low|Medium|High", "rationale": string}}""",
        )

    def generate_decision_reasoning(
        self,
        status: str,
        context: dict[str, Any],
    ) -> str:
        result = self.invoke(
            "You are an insurance claims explainability agent. Write a clear, regulator-ready "
            "explanation of why this claim decision was made. Be concise (3-5 sentences).",
            f"""Decision status: {status}
Policy validation: {context.get('policy_violations', [])}
Retrieved clauses: {[c.get('section_ref') for c in context.get('retrieved_clauses', [])]}
Evidence confidence: {context.get('evidence_confidence', 'N/A')}
Fraud score: {context.get('fraud_score', 'N/A')}
Confidence score: {context.get('confidence_score', 'N/A')}
Payable amount: {context.get('payable_amount', 0)}
Customer risk: {context.get('customer_risk_score', 'N/A')}""",
        )
        return result

    def analyze_policy_documents(self, policy_type: str, policy_number: str, document_text: str) -> dict[str, Any]:
        return self.invoke_json(
            "You are an insurance policy analyst. Extract structured policy information from documents.",
            f"""Policy type: {policy_type}
Policy number: {policy_number}

Documents:
{document_text[:8000]}

Return JSON:
{{
  "coverage_summary": "string",
  "exclusions": ["list"],
  "coverage_limits": {{}},
  "deductibles": {{}},
  "endorsements": ["list"],
  "key_sections": [{{"ref": "string", "category": "string", "summary": "string"}}],
  "waiting_periods": ["list"],
  "llm_analysis": "string"
}}""",
        )

    def extract_policy_profile(self, document_text: str) -> dict[str, Any]:
        return self.invoke_json(
            "You are an insurance policy analyst. Extract policy metadata from a policy schedule document. "
            "Return ONLY valid JSON, no markdown fences.",
            f"""Read this insurance policy schedule and extract structured fields.

Document text:
{document_text[:12000]}

Return JSON:
{{
  "policy_type": "Auto|Health|Home",
  "policy_number": "string or null if not found in document",
  "coverage_limit": number,
  "deductible": number,
  "co_pay_pct": number,
  "exclusions": ["list of exclusion strings"],
  "effective_date": "YYYY-MM-DD or null",
  "expiry_date": "YYYY-MM-DD or null",
  "summary": "one sentence summary of the policy"
}}

Use reasonable numeric defaults only when values cannot be determined: coverage_limit 500000, deductible 500, co_pay_pct 10.
policy_type must be one of Auto, Health, or Home.""",
        )

    def check_clause_alignment(
        self,
        incident: str,
        retrieved_clauses: list[dict],
        policy_context: dict[str, Any],
    ) -> dict[str, Any]:
        if not retrieved_clauses:
            return {"aligned": True, "expected_ref": "", "retrieved_ref": "", "reason": "No clauses retrieved"}

        retrieved_ref = retrieved_clauses[0].get("section_ref", "")
        key_sections = policy_context.get("key_sections", [])
        schedule_refs = [
            s.get("ref") or s.get("section_ref", "")
            for s in key_sections
            if isinstance(s, dict)
        ]

        if not schedule_refs:
            return self._fallback_clause_alignment(incident, retrieved_clauses, policy_context)

        result = self.invoke_json(
            "You are an insurance policy analyst. Determine if the RAG-retrieved clause "
            "correctly matches the policy schedule for this incident type.",
            f"""Incident: {incident}

Retrieved clause (used for decision): {retrieved_ref}
Retrieved text: {retrieved_clauses[0].get('clause_text', '')[:500]}

Policy schedule key sections: {json.dumps(key_sections[:5])}

Return JSON:
{{
  "aligned": boolean,
  "expected_ref": "section ref from schedule that should apply",
  "retrieved_ref": "{retrieved_ref}",
  "reason": "brief explanation"
}}

Set aligned=false if the retrieved clause is wrong for this incident type or contradicts the schedule.""",
        ) or self._fallback_clause_alignment(incident, retrieved_clauses, policy_context)

        if result and not result.get("aligned", True):
            retrieved = str(result.get("retrieved_ref", retrieved_ref))
            expected = str(result.get("expected_ref", ""))
            if sections_related(retrieved, expected, schedule_refs):
                result = {**result, "aligned": True, "reason": "Retrieved section is related to schedule coverage"}
            elif normalize_section_ref(retrieved) in {
                normalize_section_ref(r) for r in schedule_refs if r
            }:
                result = {**result, "aligned": True, "reason": "Retrieved section appears in policy schedule"}
        return result

    def validate_evidence_document(
        self,
        doc_type: str,
        ocr_text: str,
        incident_description: str,
        policy_type: str,
    ) -> dict[str, Any] | None:
        if not self._has_valid_key():
            return None
        return self.invoke_json(
            "You validate insurance claim evidence documents. Return ONLY valid JSON.",
            f"""Document type expected: {doc_type}
Policy type: {policy_type}
Incident: {incident_description[:500]}
OCR text (may be empty): {ocr_text[:1500]}

Return JSON:
{{
  "matches_type": boolean,
  "reason": "brief explanation if mismatch",
  "detected_content": "e.g. technical diagram, driver's license, repair invoice"
}}

For GOV_ID: matches_type=true for government-issued ID (passport, driver's license, national ID, Aadhaar, PAN card, voter ID, or similar).
For PROOF: matches_type=true if content relates to the incident/claim (damage photos, repair invoices, inspection reports, medical bills, police reports).
Set matches_type=false ONLY for clearly unrelated content: diagrams, flowcharts, software screenshots, or documents with no connection to an insurance claim.""",
        )

    def _fallback_clause_alignment(
        self,
        incident: str,
        retrieved_clauses: list[dict],
        policy_context: dict[str, Any],
    ) -> dict[str, Any]:
        retrieved_ref = retrieved_clauses[0].get("section_ref", "") if retrieved_clauses else ""
        key_sections = policy_context.get("key_sections", [])
        schedule_refs = [
            s.get("ref") or s.get("section_ref", "")
            for s in key_sections
            if isinstance(s, dict)
        ]
        expected_ref = schedule_refs[0] if schedule_refs else ""

        aligned = (
            not expected_ref
            or sections_related(retrieved_ref, expected_ref, schedule_refs)
            or retrieved_ref in str(key_sections)
        )
        return {
            "aligned": aligned,
            "expected_ref": expected_ref or "unknown",
            "retrieved_ref": retrieved_ref,
            "reason": "Schedule comparison" if expected_ref else "No schedule sections available",
        }

    def extract_payout_parameters(
        self,
        incident: str,
        claim_amount: float,
        policy_context: dict[str, Any],
        retrieved_clauses: list[dict],
        policy_type: str,
        coverage_limit: float,
    ) -> dict[str, Any]:
        clauses_text = "\n".join(
            f"- {c.get('section_ref', 'Section')}: {c.get('clause_text', '')[:300]}"
            for c in retrieved_clauses[:5]
        )
        return self.invoke_json(
            "You are an insurance payout analyst. Extract payout calculation parameters from "
            "policy documents and claim context. Return ONLY valid JSON.",
            f"""Policy type: {policy_type}
Claim amount: ${claim_amount:,.2f}
Coverage limit: ${coverage_limit:,.2f}
Incident: {incident}

Policy context summary: {policy_context.get('coverage_summary', '')}
Key sections: {json.dumps(policy_context.get('key_sections', [])[:5])}
Retrieved clauses:
{clauses_text or 'None'}

Return JSON:
{{
  "apply_deductible": boolean,
  "deductible_amount": number,
  "co_pay_pct": number,
  "co_pay_basis": "gross|after_deductible|net",
  "apply_depreciation": boolean,
  "depreciation_pct": number,
  "coverage_cap": number,
  "formula_steps": ["human-readable step descriptions"],
  "rationale": "why these parameters apply to this claim"
}}

Derive all values from the policy documents and incident — do not use generic defaults unless the policy is silent.""",
        )


llm_service = LLMService()
