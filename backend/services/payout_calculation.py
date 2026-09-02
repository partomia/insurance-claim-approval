"""Motor payout calculation.

Applies deductible → depreciation (age-based unless zero-dep add-on) → co-pay →
coverage cap. Splits the payable into own-damage and third-party components,
detects total-loss claims (repair > 75% of IDV), and applies GST on the final
amount. Returns a structured breakdown consumed by the settlement service.
"""

from dataclasses import dataclass, field
from datetime import datetime

from models.claim import Claim, IncidentType
from models.policy import Policy

# Depreciation table by vehicle age (in years). Overridden to zero when the
# zero-depreciation add-on is active on the policy.
AGE_BASED_DEPRECIATION_PCT = {
    0: 5.0,
    1: 15.0,
    2: 30.0,
    3: 40.0,
    4: 50.0,
    5: 60.0,
}

# GST applied on the final settlement amount (India default; configurable).
GST_PCT = 18.0

# Repair-cost to IDV ratio at which we mark the claim as a probable total loss.
TOTAL_LOSS_RATIO = 0.75

# Fraction of coverage limit set aside for third-party liability by default.
THIRD_PARTY_LIABILITY_SHARE = 0.30


@dataclass
class PayoutResult:
    gross_amount: float
    deductible_applied: float
    co_pay_applied: float
    depreciation_applied: float
    coverage_cap_applied: float
    own_damage_payable: float
    third_party_payable: float
    gst_amount: float
    salvage_deduction: float
    is_total_loss: bool
    next_cycle_ncb_pct: float
    payable_amount: float
    breakdown: dict = field(default_factory=dict)


def _vehicle_age_years(claim: Claim) -> int:
    if not claim.vehicle_year:
        return 0
    incident_year = (claim.incident_datetime or datetime.utcnow()).year
    return max(0, incident_year - int(claim.vehicle_year))


def _depreciation_pct_for_age(age_years: int, zero_dep: bool) -> float:
    if zero_dep:
        return 0.0
    if age_years >= 5:
        return AGE_BASED_DEPRECIATION_PCT[5]
    return AGE_BASED_DEPRECIATION_PCT.get(age_years, AGE_BASED_DEPRECIATION_PCT[0])


class PayoutCalculationService:
    """Rules-based motor payout. The LLM path lives in llm_payout_service."""

    def calculate(
        self,
        policy: Policy,
        claim_amount: float,
        claim: Claim | None = None,
    ) -> PayoutResult:
        gross = claim_amount
        idv = policy.coverage_limit

        # 1) Detect total loss up front so subsequent steps know whether to
        # short-circuit the depreciation math and pay IDV directly.
        is_total_loss = bool(idv) and (gross / idv) >= TOTAL_LOSS_RATIO

        # 2) Deductible.
        deductible = min(policy.deductible, gross)
        after_deductible = max(gross - deductible, 0.0)

        # 3) Depreciation — vehicle-age based unless zero-dep add-on is active.
        age_years = _vehicle_age_years(claim) if claim else 0
        dep_pct = _depreciation_pct_for_age(
            age_years, zero_dep=bool(policy.zero_depreciation_addon)
        )
        depreciation = after_deductible * (dep_pct / 100.0)
        after_depreciation = after_deductible - depreciation

        # 4) Co-pay.
        co_pay = after_depreciation * (policy.co_pay_pct / 100.0)
        after_co_pay = after_depreciation - co_pay

        # 5) Coverage cap.
        base_payable = min(after_co_pay, idv) if idv else after_co_pay
        coverage_cap = max(after_co_pay - base_payable, 0.0)

        # 6) Total-loss short-circuit: pay IDV minus a salvage deduction rather
        # than the depreciated repair cost.
        salvage_deduction = 0.0
        if is_total_loss:
            salvage_deduction = round(idv * 0.10, 2)  # 10% salvage retention default
            base_payable = max(idv - salvage_deduction, 0.0)

        # 7) Split own-damage vs third-party.
        is_liability_claim = (
            claim is not None
            and claim.incident_type is not None
            and (
                claim.incident_type == IncidentType.THIRD_PARTY_LIABILITY
                or claim.third_party_involved
            )
        )
        if is_liability_claim:
            tp_payable = round(base_payable * THIRD_PARTY_LIABILITY_SHARE, 2)
            od_payable = round(base_payable - tp_payable, 2)
        else:
            tp_payable = 0.0
            od_payable = round(base_payable, 2)

        # 8) GST on the final settlement amount.
        gst_amount = round((od_payable + tp_payable) * GST_PCT / 100.0, 2)
        final_payable = round(od_payable + tp_payable + gst_amount, 2)

        # 9) Next-cycle NCB — customer keeps existing NCB if claim is denied;
        # loses it (starts at 0 next renewal) if approved for own-damage.
        next_ncb = 0.0 if od_payable > 0 else float(policy.no_claim_bonus_pct or 0.0)

        breakdown = {
            "gross_amount": gross,
            "idv": idv,
            "vehicle_age_years": age_years,
            "deductible": deductible,
            "depreciation_rate": dep_pct,
            "depreciation_amount": depreciation,
            "zero_depreciation_addon": bool(policy.zero_depreciation_addon),
            "co_pay_pct": policy.co_pay_pct,
            "co_pay_amount": co_pay,
            "coverage_limit": idv,
            "coverage_cap_applied": coverage_cap,
            "is_total_loss": is_total_loss,
            "total_loss_ratio_threshold": TOTAL_LOSS_RATIO,
            "salvage_deduction": salvage_deduction,
            "is_liability_claim": is_liability_claim,
            "own_damage_payable": od_payable,
            "third_party_payable": tp_payable,
            "gst_pct": GST_PCT,
            "gst_amount": gst_amount,
            "final_payable": final_payable,
            "current_ncb_pct": float(policy.no_claim_bonus_pct or 0.0),
            "next_cycle_ncb_pct": next_ncb,
        }

        return PayoutResult(
            gross_amount=gross,
            deductible_applied=deductible,
            co_pay_applied=co_pay,
            depreciation_applied=depreciation,
            coverage_cap_applied=coverage_cap,
            own_damage_payable=od_payable,
            third_party_payable=tp_payable,
            gst_amount=gst_amount,
            salvage_deduction=salvage_deduction,
            is_total_loss=is_total_loss,
            next_cycle_ncb_pct=next_ncb,
            payable_amount=final_payable,
            breakdown=breakdown,
        )
