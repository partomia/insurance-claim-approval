"""
Output guardrails (config/guardrails.yaml: output), applied to every score before anyone sees it,
by the endpoint (serve/predict.py), batch scoring and the Copilot app alike. Adapted from
O-G-Asset-Integrity-Lakehouse guardrails/output_policy.py.

  1. failed input guardrail -> band ABSTAIN: the adjuster decides as without the model
  2. abstain band           -> UNCERTAIN when a probability is within uncertain_margin of a band edge
  3. shadow mode            -> no action: the response carries only allowed_actions; the model
                               never approves or rejects a claim, and customer_visible is false

Approval head bands (evaluation.bands): p_approve >= high LIKELY_APPROVE, <= low REVIEW, else NEUTRAL.
Fraud head: p_fraud >= its operating threshold (set on VALID) FRAUD_REVIEW, else CLEAR.
"""
from __future__ import annotations

from guardrails.input_checks import config


def approval_band(p: float, bands: dict) -> str:
    return "LIKELY_APPROVE" if p >= bands["high"] else "REVIEW" if p <= bands["low"] else "NEUTRAL"


def fraud_band(p: float, threshold: float) -> str:
    return "FRAUD_REVIEW" if p >= threshold else "CLEAR"


def apply(p_approve: float | None, p_fraud: float | None, bands: dict, fraud_threshold: float | None,
          input_results: list[dict], cfg: dict | None = None) -> dict:
    c = (cfg or config())["output"]
    m = float(c["uncertain_margin"])
    fired = [r for r in input_results if not r["passed"]]
    events = list(fired)
    if fired or p_approve is None:
        reason = "; ".join(r["reason"] for r in fired) or "no score"
        return {"approval_band": "ABSTAIN", "fraud_band": "ABSTAIN", "band_reason": reason,
                "allowed_actions": list(c["allowed_actions"]), "customer_visible": bool(c["customer_visible"]),
                "action": "adjuster decides (model abstained)", "guardrail_events": events}
    a_band = approval_band(p_approve, bands)
    near = [e for e in (bands["high"], bands["low"]) if abs(p_approve - e) < m]
    reason = None
    if near:
        events.append({"guardrail": "abstain_band", "passed": False, "value": round(p_approve, 4),
                       "limit": f"|p - {near[0]}| >= {m}", "reason": "approval score near a band edge"})
        a_band, reason = "UNCERTAIN", "approval score near a band edge"
    f_band = None
    if p_fraud is not None and fraud_threshold is not None:
        f_band = fraud_band(p_fraud, fraud_threshold)
        if abs(p_fraud - fraud_threshold) < m / 2:
            events.append({"guardrail": "abstain_band", "passed": False, "value": round(p_fraud, 4),
                           "limit": f"|p - {fraud_threshold:.3f}| >= {m / 2}", "reason": "fraud score near the threshold"})
            f_band = "UNCERTAIN"
    return {"approval_band": a_band, "fraud_band": f_band, "band_reason": reason,
            "allowed_actions": list(c["allowed_actions"]), "customer_visible": bool(c["customer_visible"]),
            "action": "shadow mode: advisory to the adjuster", "guardrail_events": events}
