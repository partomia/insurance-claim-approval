"""
CAI Model mcc-approval: function predict() serves both champion heads (approval and fraud,
installed by job mcc-04) behind the guardrails in guardrails/. Shadow mode: the answer is advice
to the adjuster; it never approves or rejects a claim and is never shown to the customer.
Adapted from O-G-Asset-Integrity-Lakehouse serve/predict.py.

Request (JSON), one of:
  {"claim": {...}, "policy": {...}, "garage": {...}}
        claim   claim_type, amount_requested, incident_ts, fnol_ts, police_report, vehicle_vin,
                crash_event_match (optional)
        policy  its gold.scoring_context_policy row; garage its gold.scoring_context_garage row
  {"features": {...}}   a ready feature row (features.feature_logic.raw_columns)
  optional "rules_decision": the rules engine's decision, for the agrees_with_rules flag
Response: {"p_approve", "p_fraud", "approval_band", "fraud_band", "band_reason", "top_factors",
           "guardrails", "guardrail_events", "allowed_actions", "customer_visible", "action",
           "agrees_with_rules", "model": {...}}
Errors come back as {"error": ...} with the exception, never as an opaque HTTP 400.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# The replica gets 1 vCPU but OpenMP sees every host core: HistGradientBoosting then
# oversubscribes, is throttled and the endpoint answers "model busy". Must precede numpy.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:
        return Path(os.getcwd())


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

try:
    import cml.models_v1 as _cml_models

    cml_model = _cml_models.cml_model
except ImportError:  # outside CAI (tests, app, jobs)
    def cml_model(fn):
        return fn

_HEADS, _LOAD_ERROR = {}, None
# A load failure must not crash the replica (it would never turn ready and hide the cause):
# every call answers with the error instead, and nothing is scored.
try:
    from features.feature_logic import serving_row
    from serve import scoring

    _HEADS, _errors = scoring.load_heads(ROOT)
    if "approval" not in _HEADS:
        raise RuntimeError(f"approval champion not loaded: {_errors or 'models/champion missing'}")
except Exception as e:  # noqa: BLE001
    _LOAD_ERROR = {"error": f"model not loaded: {type(e).__name__}: {e}", "root": str(ROOT),
                   "trace": traceback.format_exc()[-1500:]}


# A PBJ runtime's model server calls only a function wrapped by cml_model: without it every
# request hangs and the endpoint answers "model busy".
@cml_model
def predict(args: dict) -> dict:
    if _LOAD_ERROR:
        return _LOAD_ERROR
    try:
        if isinstance(args, str):
            args = json.loads(args)
        policy = args.get("policy")
        if "features" in args:
            row = args["features"]
        elif "claim" in args:
            row = serving_row(args["claim"], policy, args.get("garage"), _HEADS["approval"].meta["type_means"])
        else:
            return {"error": "send claim (+ policy, garage) or features"}
        res = scoring.score_row(_HEADS, row, policy)
        res["agrees_with_rules"] = scoring.agrees_with_rules(res, args.get("rules_decision"))
        return res
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
