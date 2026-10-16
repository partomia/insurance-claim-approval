"""
Input guardrails, run before a claim is scored (config/guardrails.yaml: input). Adapted from
O-G-Asset-Integrity-Lakehouse guardrails/input_checks.py (ood_stats / ood_check unchanged).

  claim_checks(row, ctx)        policy and customer resolved by MDM, few missing features,
                                amount inside anything trained on -> the model abstains
  ood_stats(X) / ood_check()    standardised distance to the training features -> abstain (OOD)

Every check returns {"guardrail", "passed", "value", "limit", "reason"}; nothing raises, so the
caller decides what a failure means and logs it (guardrails/events.py).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def config() -> dict:
    import yaml

    return yaml.safe_load((ROOT / "config" / "guardrails.yaml").read_text())


def _check(name, passed, value, limit, reason) -> dict:
    return {"guardrail": name, "passed": bool(passed), "value": None if value is None else round(float(value), 4),
            "limit": limit, "reason": None if passed else reason}


def claim_checks(row: dict, policy: dict | None, cfg: dict | None = None) -> list[dict]:
    from features.feature_logic import missing_fraction

    c = (cfg or config())["input"]
    p = policy or {}
    out = []
    if c.get("require_resolved_policy", True):
        out.append(_check("policy_resolved", bool(p.get("policy_number")), None, "policy in gold scoring context",
                          "policy not in the lakehouse: not scored"))
    if c.get("require_resolved_customer", True):
        out.append(_check("customer_resolved", bool(p.get("golden_customer_id")), None, "MDM golden customer",
                          "customer not resolved by MDM: not scored"))
    miss = missing_fraction(row)
    out.append(_check("missing_features", miss <= c["max_missing_fraction"], miss, f"<= {c['max_missing_fraction']}",
                      "too many features missing"))
    amt = row.get("amount_requested")
    ok = amt is not None and amt == amt and 0 < float(amt) <= c["amount_max"]
    out.append(_check("amount_range", ok, amt if ok or amt == amt else None, f"0 < amount <= {c['amount_max']}",
                      "amount outside the trained range"))
    return out


def ood_stats(X: np.ndarray, quantile: float | None = None) -> dict:
    """Training-set reference for ood_check, stored in model_meta.json by train_validate.py.
    Missing values (NaN) are left out of the mean, the spread and each row's distance."""
    q = quantile or config()["input"]["ood_quantile"]
    mu, sd = np.nanmean(X, axis=0), np.nanstd(X, axis=0)
    mu, sd = np.nan_to_num(mu), np.where(~np.isfinite(sd) | (sd < 1e-6), 1e-6, sd)
    d = np.nanmean(((X - mu) / sd) ** 2, axis=1)
    return {"mean": mu.round(6).tolist(), "std": sd.round(6).tolist(), "limit": float(np.nanquantile(d, q)),
            "quantile": q, "train_median": float(np.nanmedian(d))}


def ood_distance(x: np.ndarray, stats: dict) -> float:
    mu, sd = np.asarray(stats["mean"]), np.asarray(stats["std"])
    z = ((np.asarray(x, dtype=float) - mu) / sd) ** 2
    return float(np.nanmean(z)) if np.isfinite(z).any() else 0.0


def ood_check(x: np.ndarray, stats: dict | None) -> dict:
    if not stats:
        return _check("out_of_distribution", True, None, "no reference", None)
    d = ood_distance(x, stats)
    return _check("out_of_distribution", d <= stats["limit"], d, f"<= {stats['limit']:.2f} "
                  f"(training q{stats['quantile']})", "unlike anything in training (OOD)")
