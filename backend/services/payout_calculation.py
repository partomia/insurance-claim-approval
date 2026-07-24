from dataclasses import dataclass

from models.policy import Policy


@dataclass
class PayoutResult:
    gross_amount: float
    deductible_applied: float
    co_pay_applied: float
    depreciation_applied: float
    coverage_cap_applied: float
    payable_amount: float
    breakdown: dict


class PayoutCalculationService:
    def calculate(self, policy: Policy, claim_amount: float) -> PayoutResult:
        gross = claim_amount
        deductible = min(policy.deductible, gross)
        after_deductible = max(gross - deductible, 0.0)

        co_pay = after_deductible * (policy.co_pay_pct / 100.0)
        after_co_pay = after_deductible - co_pay

        depreciation = after_co_pay * (policy.depreciation_rate / 100.0)
        after_depreciation = after_co_pay - depreciation

        payable = min(after_depreciation, policy.coverage_limit)
        coverage_cap = max(after_depreciation - payable, 0.0)

        return PayoutResult(
            gross_amount=gross,
            deductible_applied=deductible,
            co_pay_applied=co_pay,
            depreciation_applied=depreciation,
            coverage_cap_applied=coverage_cap,
            payable_amount=round(payable, 2),
            breakdown={
                "gross_amount": gross,
                "deductible": deductible,
                "co_pay_pct": policy.co_pay_pct,
                "co_pay_amount": co_pay,
                "depreciation_rate": policy.depreciation_rate,
                "depreciation_amount": depreciation,
                "coverage_limit": policy.coverage_limit,
            },
        )
