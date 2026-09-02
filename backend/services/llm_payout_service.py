from dataclasses import dataclass
from typing import Any

from models.claim import Claim
from models.policy import Policy
from services.llm_service import llm_service
from services.payout_calculation import PayoutResult


@dataclass
class LLMPayoutResult:
    payable_amount: float
    breakdown: dict[str, Any]
    formula_steps: list[str]
    rationale: str


class LLMPayoutService:
    def calculate(
        self,
        claim: Claim,
        policy: Policy,
        retrieved_clauses: list[dict],
    ) -> LLMPayoutResult:
        ctx = claim.policy_context_json or {}
        params = llm_service.extract_payout_parameters(
            incident=claim.incident_description,
            claim_amount=claim.claim_amount,
            policy_context=ctx,
            retrieved_clauses=retrieved_clauses,
            policy_type=policy.policy_type,
            coverage_limit=policy.coverage_limit,
        )

        if not params:
            params = self._fallback_params(policy)

        gross = claim.claim_amount
        apply_deductible = bool(params.get("apply_deductible", True))
        deductible = float(params.get("deductible_amount", policy.deductible)) if apply_deductible else 0.0
        deductible = min(max(deductible, 0.0), gross)

        after_deductible = max(gross - deductible, 0.0)
        co_pay_pct = float(params.get("co_pay_pct", policy.co_pay_pct))
        co_pay_basis = str(params.get("co_pay_basis", "after_deductible")).lower()

        if co_pay_basis == "gross":
            co_pay_base = gross
        elif co_pay_basis == "net":
            co_pay_base = after_deductible
        else:
            co_pay_base = after_deductible

        co_pay = co_pay_base * (co_pay_pct / 100.0)
        after_co_pay = after_deductible - co_pay if co_pay_basis != "gross" else gross - co_pay

        apply_depreciation = bool(params.get("apply_depreciation", False))
        depreciation_pct = float(params.get("depreciation_pct", 0.0)) if apply_depreciation else 0.0
        depreciation = after_co_pay * (depreciation_pct / 100.0)
        after_depreciation = after_co_pay - depreciation

        coverage_cap = float(params.get("coverage_cap", policy.coverage_limit))
        payable = min(max(after_depreciation, 0.0), coverage_cap)

        breakdown = {
            "gross": gross,
            "deductible": deductible,
            "co_pay_pct": co_pay_pct,
            "co_pay_amount": round(co_pay, 2),
            "co_pay_basis": co_pay_basis,
            "depreciation_pct": depreciation_pct,
            "depreciation_amount": round(depreciation, 2),
            "coverage_cap": coverage_cap,
            "payable": round(payable, 2),
            "steps": [
                {"name": "Claimed", "value": gross},
                {"name": "Deductible", "value": -deductible},
                {"name": "Co-pay", "value": -round(co_pay, 2)},
                *(
                    [{"name": "Depreciation", "value": -round(depreciation, 2)}]
                    if depreciation > 0
                    else []
                ),
                {"name": "Payable", "value": round(payable, 2)},
            ],
        }

        return LLMPayoutResult(
            payable_amount=round(payable, 2),
            breakdown=breakdown,
            formula_steps=params.get("formula_steps") or [],
            rationale=params.get("rationale") or "LLM-derived payout parameters applied.",
        )

    def _fallback_params(self, policy: Policy) -> dict[str, Any]:
        return {
            "apply_deductible": True,
            "deductible_amount": policy.deductible,
            "co_pay_pct": policy.co_pay_pct,
            "co_pay_basis": "after_deductible",
            "apply_depreciation": policy.depreciation_rate > 0,
            "depreciation_pct": policy.depreciation_rate,
            "coverage_cap": policy.coverage_limit,
            "formula_steps": ["Fallback: policy table defaults applied"],
            "rationale": "LLM unavailable; using policy record defaults.",
        }

    def to_payout_result(self, result: LLMPayoutResult) -> PayoutResult:
        b = result.breakdown
        return PayoutResult(
            gross_amount=b.get("gross", 0),
            deductible_applied=b.get("deductible", 0),
            co_pay_applied=b.get("co_pay_amount", 0),
            depreciation_applied=b.get("depreciation_amount", 0),
            coverage_cap_applied=max(b.get("gross", 0) - b.get("payable", 0), 0),
            own_damage_payable=b.get("payable", result.payable_amount),
            third_party_payable=0.0,
            gst_amount=0.0,
            salvage_deduction=0.0,
            is_total_loss=False,
            next_cycle_ncb_pct=0.0,
            payable_amount=result.payable_amount,
            breakdown=result.breakdown,
        )
