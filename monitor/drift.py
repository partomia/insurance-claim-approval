"""
Job mcc-05-nightly-drift: is the champion still looking at the claims it was trained on?
Adapted from O-G-Asset-Integrity-Lakehouse monitor/drift.py.

  1. current set: the claims of the last 30 days in the latest gold snapshot (and every open one),
     through the same path as batch scoring (lakehouse/score_claims.py: point-in-time features,
     the guardrails, both champions); each guardrail that fires is a row in ref.guardrail_event
  2. drift against the training feature table (TRAIN split):
       PSI of p_approve, and the max / mean PSI over the numeric features
       abstain rate and out-of-distribution rate
     status OK / WARN / ALERT from config/guardrails.yaml process.drift; TOO_FEW below min_samples
  3. rows in ref.model_drift, outputs/monitoring/drift_report.json (read by mcc-08-retrain-trigger)
     and a DRIFT_ALERT model event when any metric alerts

  python monitor/drift.py            # CDW Impala (MCC_IMPALA_USER)
  python monitor/drift.py --local    # local Spark warehouse
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # CAI job kernels run the script without __file__; cwd is the project
        return Path(os.getcwd())


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from common import finish, load_config, load_feature_table, parse_args  # noqa: E402
from guardrails import events  # noqa: E402
from guardrails.input_checks import config as guard_config  # noqa: E402

REPORT = ROOT / "outputs" / "monitoring" / "drift_report.json"
WINDOW_DAYS = 30


def psi(ref: np.ndarray, cur: np.ndarray, bins: int = 10) -> float:
    """Population stability index with bins on the reference deciles (NaN left out)."""
    ref, cur = np.asarray(ref, float), np.asarray(cur, float)
    ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if not len(ref) or not len(cur):
        return 0.0
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    r = np.histogram(ref, edges)[0] / len(ref)
    c = np.histogram(cur, edges)[0] / max(len(cur), 1)
    r, c = np.clip(r, 1e-4, None), np.clip(c, 1e-4, None)
    return float(((c - r) * np.log(c / r)).sum())


def status(value: float, warn: float, alert: float) -> str:
    return "ALERT" if value >= alert else "WARN" if value >= warn else "OK"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true")
    args = parse_args(ap)
    cfg = load_config(model="approval")
    g = guard_config()["process"]["drift"]
    from features.feature_logic import matrix, spec
    from lakehouse import score_claims as SC
    from lakehouse.publish import publish_model_event
    from lakehouse.store import model_version, publish
    from serve import scoring

    heads, errors = scoring.load_heads(ROOT)
    if "approval" not in heads:
        raise SystemExit(f"no approval champion: {errors or 'run the chain mcc-01..04 first'}")
    meta = heads["approval"].meta
    version = model_version(meta)
    df, _ = load_feature_table(cfg)
    ref = df[df["split"] == "train"]
    ref_X = matrix(ref)
    ref_p = heads["approval"].proba(ref_X)

    src = SC.Source(args.local)
    d = SC.latest_date(src)
    items = SC.claims(src, d, days=WINDOW_DAYS)
    rows, raw = SC.score(items, heads)
    feats = [r for r, res in raw if res.get("p_approve") is not None]
    cur_p = np.array([res["p_approve"] for _, res in raw if res.get("p_approve") is not None])
    n, n_scored = len(raw), len(cur_p)
    guard_rows = [e for (_, res), r in zip(raw, rows)
                  for e in events.rows(res.get("guardrail_events", []), r["claim_id"], version, "mcc-05-nightly-drift")]
    ood = sum(1 for r in guard_rows if r["guardrail"] == "out_of_distribution")
    abstain = sum(1 for r in rows if r["approval_band"] == "ABSTAIN")
    run_id, now = uuid.uuid4().hex[:12], datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    metrics = {"ood_rate": (ood / max(n, 1), g["max_ood_rate"] / 2, g["max_ood_rate"]),
               "abstain_rate": (abstain / max(n, 1), g["max_abstain_rate"] / 2, g["max_abstain_rate"])}
    if n_scored >= g["min_samples"]:
        import pandas as pd

        cur_X = matrix(pd.DataFrame(feats))
        k = len(spec()["numeric"])
        fpsi = {c: psi(ref_X[:, j], cur_X[:, j]) for j, c in enumerate(spec()["numeric"][:k])}
        worst = max(fpsi, key=fpsi.get)
        metrics.update({"psi_score": (psi(ref_p, cur_p), g["psi_warn"], g["psi_alert"]),
                        "psi_feature_max": (fpsi[worst], g["psi_warn"] * 2, g["psi_alert"] * 2),
                        "psi_feature_mean": (float(np.mean(list(fpsi.values()))), g["psi_warn"], g["psi_alert"])})
    else:
        worst = None
    rows_out = [{"run_id": run_id, "recorded_at": now, "model_version": version, "metric": k, "value": round(v, 4),
                 "status": status(v, w, a), "n_reference": int(len(ref_X)), "n_current": n_scored,
                 "detail": f"warn {w:.3f}, alert {a:.3f}; claims of {WINDOW_DAYS} days to {d}"
                           + (f"; worst feature {worst}" if k == "psi_feature_max" and worst else "")}
                for k, (v, w, a) in metrics.items()]
    if n_scored < g["min_samples"]:
        rows_out.append({"run_id": run_id, "recorded_at": now, "model_version": version, "metric": "psi_score",
                         "value": None, "status": "TOO_FEW", "n_reference": int(len(ref_X)), "n_current": n_scored,
                         "detail": f"fewer than {g['min_samples']} scored claims"})
    overall = "ALERT" if any(r["status"] == "ALERT" for r in rows_out) else \
        "WARN" if any(r["status"] == "WARN" for r in rows_out) else "OK"
    report = {"run_id": run_id, "recorded_at": now.isoformat(), "model_version": version, "business_date": str(d),
              "claims": n, "scored": n_scored, "guardrail_events": len(guard_rows), "status": overall,
              "metrics": {r["metric"]: {"value": r["value"], "status": r["status"], "detail": r["detail"]}
                          for r in rows_out}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str), flush=True)
    events.log_local(guard_rows)
    if args.local:
        return 0
    publish("guardrail_event", guard_rows)
    publish("model_drift", rows_out)
    if overall == "ALERT":
        drift_rows = [{"guardrail": "drift_psi", "passed": False, "value": r["value"], "limit": r["detail"],
                       "reason": f"{r['metric']} alert"} for r in rows_out if r["status"] == "ALERT"]
        publish("guardrail_event", events.rows(drift_rows, f"model {version}", version, "mcc-05-nightly-drift"))
        publish_model_event("DRIFT_ALERT", meta, stage="champion",
                            detail=", ".join(f"{r['metric']}={r['value']}" for r in rows_out if r["status"] == "ALERT"))
    return 0


if __name__ == "__main__":
    finish(main())
