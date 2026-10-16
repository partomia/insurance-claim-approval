"""The CAI chain offline (config/ci.yaml overlay): feature table -> train -> gate -> scoring, on a
synthetic training table with a learnable signal; and the feature definition's contracts."""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from features import feature_logic as FL  # noqa: E402


def synthetic(n: int = 900, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    s = FL.spec()
    df = pd.DataFrame({c: rng.normal(1.0, 0.5, n) for c in s["numeric"]})
    for c in ("crash_event_match", "telematics_enrolled", "police_report", "vin_mismatch", "cross_claimant"):
        df[c] = rng.integers(0, 2, n)
    for c, vals in s["categorical"].items():
        df[c] = rng.choice(vals, n)
    z = 1.5 - 2.0 * df["vin_mismatch"] - 1.2 * df["report_delay_days"] + 1.0 * df["crash_event_match"]
    df["approved"] = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int)
    df["fraud_confirmed"] = ((df["vin_mismatch"] == 1) & (rng.random(n) < 0.5)).astype(int)
    df["claim_id"] = [f"CLM-{i}" for i in range(n)]
    df["policy_number"] = "LH-POL-1"
    df["golden_customer_id"] = "GC-1"
    df["fnol_ts"] = pd.Timestamp("2025-01-01") + pd.to_timedelta(np.arange(n) * 3600 * 9, unit="s")
    df["business_date"] = pd.Timestamp("2026-10-16").date()
    return df


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    os.environ["MCC_CONFIG_OVERLAY"] = "config/ci.yaml"
    os.environ["MCC_FEATURE_SOURCE"] = "local"
    from common import load_config

    cfg = load_config(model="approval")
    for d in ("outputs/ci",):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    export = ROOT / cfg["data"]["local_export"]
    export.parent.mkdir(parents=True, exist_ok=True)
    synthetic().to_parquet(export, index=False)
    from features import build_feature_table
    from gate import kpi_gate
    from train import train_validate

    df, src = build_feature_table.load(cfg)
    manifest = build_feature_table.build(cfg, df, src)
    metas = {m: train_validate.train(load_config(model=m)) for m in ("approval", "fraud")}
    passed = {m: kpi_gate.gate_one(load_config(model=m)) for m in ("approval", "fraud")}
    yield cfg, manifest, metas, passed
    os.environ.pop("MCC_CONFIG_OVERLAY", None)
    os.environ.pop("MCC_FEATURE_SOURCE", None)


def test_feature_names_and_hash_are_stable():
    names = FL.feature_names()
    assert len(names) == len(FL.spec()["numeric"]) + sum(len(v) for v in FL.spec()["categorical"].values())
    assert FL.feature_hash() == FL.feature_hash() and len(FL.feature_hash()) == 16
    assert not FL.PROTECTED & set(FL.raw_columns())


def test_categoricals_match_the_lakehouse():
    cfg = json.loads((ROOT / "config" / "lakehouse.json").read_text())
    from generators.universe import CLAIM_TYPES

    assert set(FL.spec()["categorical"]["claim_type"]) == set(CLAIM_TYPES)
    assert set(FL.spec()["categorical"]["credit_band"]) == {"EXCELLENT", "GOOD", "FAIR", "POOR", "NO_HIT"}
    b = cfg["credit_bands"]
    assert FL.credit_band(b["excellent_min"]) == "EXCELLENT" and FL.credit_band(b["fair_min"] - 1) == "POOR"
    assert FL.credit_band(None) == "NO_HIT"


def test_serving_row_formulas():
    claim = {"claim_type": "Collision", "amount_requested": 50000, "incident_ts": "2026-10-16 08:30:00",
             "fnol_ts": "2026-10-17 08:30:00", "police_report": "Y", "vehicle_vin": "VIN-B", "crash_event_match": True}
    policy = {"policy_number": "P", "golden_customer_id": "GC", "idv": 500000, "customer_since": "2026-10-07",
              "vehicle_year": 2020, "policy_vin": "VIN-A", "other_insurer_claims_3y": 3, "credit_score": 710,
              "telematics_enrolled": 1, "prior_claims_12m": 2}
    garage = {"garage_risk_score": 0.2, "garage_claims_30d": 4, "garage_network_status": "WATCHLIST"}
    r = FL.serving_row(claim, policy, garage, {"Collision": 25000})
    assert r["amount_vs_type_mean"] == 2.0 and r["amount_vs_idv"] == 0.1 and r["report_delay_days"] == 1.0
    assert r["incident_hour"] == 8 and r["customer_tenure_days"] == 10 and r["vehicle_age_years"] == 6
    assert r["vin_mismatch"] == 1 and r["cross_claimant"] == 1 and r["police_report"] == 1
    assert r["credit_band"] == "GOOD" and r["garage_network_status"] == "WATCHLIST"
    assert len(FL.vector(r)) == len(FL.feature_names())
    empty = FL.serving_row({"claim_type": "Glass", "amount_requested": 1000}, None, None, {})
    assert math.isnan(empty["idv"]) and FL.missing_fraction(empty) > 0.3
    # no garage named (the app): missing, not the never-trained UNKNOWN; a named garage absent from the master: UNKNOWN
    assert empty["garage_network_status"] is None and math.isnan(empty["garage_claims_30d"])
    garage_cols = [i for i, n in enumerate(FL.feature_names()) if n.startswith("garage_network_status")]
    assert garage_cols and all(FL.vector(empty)[i] == 0.0 for i in garage_cols)
    named = FL.serving_row({"claim_type": "Glass", "amount_requested": 1000, "garage_id": "G9"}, None, None, {})
    assert named["garage_network_status"] == "UNKNOWN" and named["garage_claims_30d"] == 0


def test_chain_trains_and_gates(chain):
    cfg, manifest, metas, passed = chain
    assert manifest["splits"]["test"]["rows"] > 0 and manifest["feature_hash"] == FL.feature_hash()
    assert metas["approval"]["metrics"]["test"]["auroc"] > 0.6
    assert passed["approval"]
    gate = json.loads((ROOT / cfg["serving"]["candidate_dir"] / "gate_result.json").read_text())
    assert gate["passed"] and any(c["name"] == "feature_hash_match" for c in gate["checks"])


def test_scoring_guardrails_and_factors(chain, tmp_path):
    cfg, _, metas, _ = chain
    from common import load_config
    from serve import scoring

    folders = {m: load_config(model=m)["serving"]["candidate_dir"] for m in ("approval", "fraud")}
    heads, errors = scoring.load_heads(ROOT, folders)
    assert set(heads) == {"approval", "fraud"}, errors
    row = synthetic(1, seed=3).iloc[0][FL.raw_columns()].to_dict()
    res = scoring.score_row(heads, row, {"policy_number": "P", "golden_customer_id": "GC"})
    assert res["approval_band"] in ("LIKELY_APPROVE", "NEUTRAL", "REVIEW", "UNCERTAIN")
    assert res["customer_visible"] is False and "reject" not in " ".join(res["allowed_actions"])
    assert 0 <= res["p_approve"] <= 1 and isinstance(res["top_factors"]["approval"], list)
    unresolved = scoring.score_row(heads, row, {})
    assert unresolved["approval_band"] == "ABSTAIN" and unresolved["p_approve"] is None


def test_endpoint_refuses_other_feature_logic(chain, tmp_path):
    cfg, _, _, _ = chain
    from serve import scoring

    src = ROOT / cfg["serving"]["candidate_dir"]
    dst = tmp_path / "champion"
    shutil.copytree(src, dst)
    meta = json.loads((dst / "model_meta.json").read_text())
    meta["feature_hash"] = "0" * 16
    (dst / "model_meta.json").write_text(json.dumps(meta))
    heads, errors = scoring.load_heads(tmp_path, {"approval": "champion"})
    assert not heads and "different feature logic" in errors["approval"]
