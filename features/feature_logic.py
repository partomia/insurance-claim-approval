"""
The one feature definition of both heads (approval, fraud), used by the feature table build
(features/build_feature_table.py), training, the mcc-approval endpoint (serve/predict.py), batch
scoring (lakehouse/score_claims.py) and the Copilot app's approval_model_service.py.

The point-in-time features themselves are computed in the lakehouse: gold.claim_training_features
for decided claims (history strictly before each FNOL) and gold.scoring_context_policy /
scoring_context_garage for a claim being scored now. This module
  - names the feature vector (config/pipeline.yaml features: numeric, then one-hot categoricals),
  - turns rows into the matrix the model sees (matrix),
  - derives the claim-level features of a new claim from its raw fields and the scoring
    context (serving_row), with exactly the formulas build_gold.training_features uses,
  - and locks the pairing: feature_hash() covers this file and the feature section of
    pipeline.yaml; a model refuses to serve against a different hash.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {"holder_name", "holder_dob", "holder_email", "holder_mobile", "city", "pincode", "gender"}


@lru_cache(maxsize=1)
def spec() -> dict:
    import yaml

    f = yaml.safe_load((ROOT / "config" / "pipeline.yaml").read_text())["features"]
    leaked = PROTECTED & (set(f["numeric"]) | set(f["categorical"]))
    if leaked:
        raise ValueError(f"protected attributes in the feature vector: {sorted(leaked)}")
    return {"version": str(f["version"]), "numeric": list(f["numeric"]),
            "categorical": {k: list(v) for k, v in f["categorical"].items()}}


def feature_version() -> str:
    return spec()["version"]


def feature_hash() -> str:
    body = Path(__file__).read_bytes() + json.dumps([spec(), _bands()], sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()[:16]


def feature_names() -> list[str]:
    s = spec()
    return s["numeric"] + [f"{c}={v}" for c, vals in s["categorical"].items() for v in vals]


def raw_columns() -> list[str]:
    s = spec()
    return s["numeric"] + list(s["categorical"])


def _num(v) -> float:
    if v is None:
        return math.nan
    try:
        x = float(v)
    except (TypeError, ValueError):
        return math.nan
    return x


def vector(row: dict) -> list[float]:
    """One feature row (dict of raw_columns) -> the model's input vector (NaN = missing)."""
    s = spec()
    out = [_num(row.get(c)) for c in s["numeric"]]
    for c, vals in s["categorical"].items():
        v = row.get(c)
        out += [1.0 if v == x else 0.0 for x in vals]
    return out


def matrix(df):
    """A DataFrame with raw_columns -> float matrix (rows in the frame's order)."""
    import numpy as np

    return np.array([vector(r) for r in df[raw_columns()].to_dict("records")], dtype=float)


def missing_fraction(row: dict) -> float:
    cols = spec()["numeric"]
    return sum(1 for c in cols if math.isnan(_num(row.get(c)))) / len(cols)


# ---------------------------------------------------------------- serving: a claim being scored now


@lru_cache(maxsize=1)
def _bands() -> dict:
    return json.loads((ROOT / "config" / "lakehouse.json").read_text())["credit_bands"]


def credit_band(score) -> str:
    """build_gold.credit_band: thresholds from config/lakehouse.json credit_bands."""
    x, b = _num(score), _bands()
    if math.isnan(x):
        return "NO_HIT"
    return ("EXCELLENT" if x >= b["excellent_min"] else "GOOD" if x >= b["good_min"]
            else "FAIR" if x >= b["fair_min"] else "POOR")


def _ts(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return datetime.fromisoformat(str(v).replace("Z", "").replace("T", " ")[:19])


def _yn(v) -> int:
    return 1 if v == "Y" or v is True else 0


def serving_row(claim: dict, policy: dict | None, garage: dict | None, type_means: dict[str, float]) -> dict:
    """The raw feature row of a new claim, from
         claim   its own fields: claim_type, amount_requested, incident_ts, fnol_ts, police_report,
                 vehicle_vin, crash_event_match (telematics corroboration, when known)
         policy  its gold.scoring_context_policy row (customer and history features)
         garage  its gold.scoring_context_garage row
         type_means  mean amount_requested per claim type in the training table
    Same formulas as build_gold.training_features; history comes from the scoring context.
    A claim that names no garage (the Copilot app has no garage master) leaves the garage
    features missing; UNKNOWN is for a named garage absent from the master."""
    p, g = policy or {}, garage or {}
    named_garage = bool(garage) or bool(claim.get("garage_id"))
    fnol, inc = _ts(claim.get("fnol_ts")) or datetime.utcnow(), _ts(claim.get("incident_ts"))
    amount = _num(claim.get("amount_requested"))
    idv = _num(p.get("idv"))
    mean = type_means.get(claim.get("claim_type")) or (sum(type_means.values()) / len(type_means) if type_means else None)
    since = _ts(p.get("customer_since"))
    vy = _num(p.get("vehicle_year"))
    stated_vin, policy_vin = claim.get("vehicle_vin"), p.get("policy_vin")
    other = _num(p.get("other_insurer_claims_3y"))
    return {
        "amount_requested": amount,
        "amount_vs_type_mean": round(amount / mean, 4) if mean else math.nan,
        "amount_vs_idv": round(amount / idv, 4) if idv and not math.isnan(idv) else math.nan,
        "report_delay_days": round((fnol - inc).total_seconds() / 86400, 3) if inc else math.nan,
        "incident_hour": inc.hour if inc else math.nan,
        "customer_tenure_days": max((fnol.date() - since.date()).days, 0) if since else math.nan,
        "prior_claims_12m": _num(p.get("prior_claims_12m", 0)),
        "prior_rejected_12m": _num(p.get("prior_rejected_12m", 0)),
        "customer_policies": _num(p.get("customer_policies")),
        "credit_score": _num(p.get("credit_score")),
        "years_licensed": _num(p.get("years_licensed")),
        "traffic_violations": _num(p.get("traffic_violations")),
        "other_insurer_claims_3y": other,
        "vehicle_age_years": fnol.year - vy if not math.isnan(vy) else math.nan,
        "idv": idv,
        "ncb_pct": _num(p.get("ncb_pct")),
        "garage_risk_score": _num(g.get("garage_risk_score")),
        "garage_claims_30d": _num(g.get("garage_claims_30d", 0)) if named_garage else math.nan,
        "crash_event_match": int(bool(claim.get("crash_event_match"))),
        "telematics_enrolled": int(_num(p.get("telematics_enrolled")) == 1),
        "police_report": _yn(claim.get("police_report")),
        "vin_mismatch": int(bool(stated_vin and policy_vin and stated_vin != policy_vin)),
        "cross_claimant": int(not math.isnan(other) and other >= 3),
        "claim_type": claim.get("claim_type"),
        "garage_network_status": (g.get("garage_network_status") or "UNKNOWN") if named_garage else None,
        "credit_band": credit_band(p.get("credit_score")),
    }
