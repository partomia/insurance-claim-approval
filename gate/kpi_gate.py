"""
Job mcc-03-kpi-gate: each head's TEST metrics against config/pipeline.yaml gate (with the head's
overrides). Exit code 1 if any head misses, so the CAI dependency stops the chain before deploy.
Copied from O-G-Asset-Integrity-Lakehouse gate/kpi_gate.py; the checks are the claim KPIs:

  auroc >= min_auroc                     both heads (approval 0.75)
  pr_auc >= min_pr_auc_lift x base_rate  fraud (2x: the model must rank fraud well above chance)
  brier <= max_brier                     calibration
  feature_hash_match                     the candidate was built on today's feature logic
  auroc_vs_champion                      a retrained candidate may lose at most max_auroc_regression

Writes gate_result.json next to the candidate; deploy refuses a candidate without a passing
result for the same git sha. GATE_PASSED / GATE_FAILED goes to ref.model_event.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # CAI job kernels run the script without __file__; cwd is the project
        return Path(os.getcwd())


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

from common import finish, load_config, selected_models  # noqa: E402
from features.feature_logic import feature_hash  # noqa: E402


def evaluate(meta: dict, gate: dict, champion: dict | None) -> list[tuple[str, float, str, float, bool]]:
    t = meta["metrics"]["test"]
    checks = [("auroc", t["auroc"], ">=", gate["min_auroc"], t["auroc"] >= gate["min_auroc"]),
              ("brier", t["brier"], "<=", gate["max_brier"], t["brier"] <= gate["max_brier"])]
    if gate.get("min_pr_auc_lift"):
        floor = gate["min_pr_auc_lift"] * t["base_rate"]
        checks.append(("pr_auc_vs_base_rate", t["pr_auc"], ">=", floor, t["pr_auc"] >= floor))
    if gate.get("require_feature_hash_match", True):
        ok = meta["feature_hash"] == feature_hash()
        checks.append(("feature_hash_match", float(ok), "==", 1.0, ok))
    if champion and champion.get("feature_hash") == meta["feature_hash"]:
        floor = champion["metrics"]["test"]["auroc"] - gate["max_auroc_regression"]
        checks.append(("auroc_vs_champion", t["auroc"], ">=", floor, t["auroc"] >= floor))
    return checks


def gate_one(cfg: dict) -> bool:
    cand = ROOT / cfg["serving"]["candidate_dir"]
    meta = json.loads((cand / "model_meta.json").read_text())
    champ_path = ROOT / cfg["serving"]["champion_dir"] / "model_meta.json"
    champion = json.loads(champ_path.read_text()) if champ_path.exists() else None
    checks = evaluate(meta, cfg["gate"], champion)
    for name, val, op, lim, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {meta['model']} {name}: {val:.3f} {op} {lim:.3f}", flush=True)
    passed = all(c[4] for c in checks)
    gate = {"passed": passed, "candidate_git_sha": meta["git_sha"], "model_version": meta["model_version"],
            "checks": [{"name": n, "value": v, "op": o, "limit": lim, "ok": ok} for n, v, o, lim, ok in checks]}
    (cand / "gate_result.json").write_text(json.dumps(gate, indent=2))
    print(f"gate {'PASSED' if passed else 'FAILED'} for {meta['model']} ({meta['model_version']})", flush=True)
    if meta.get("mlflow_run_id"):
        try:
            import mlflow

            mlflow.set_experiment(cfg["project"]["mlflow_experiment"])   # the CAI plugin needs it to reopen a run
            with mlflow.start_run(run_id=meta["mlflow_run_id"]):
                mlflow.log_metric("kpi_gate_passed", 1.0 if passed else 0.0)
                mlflow.set_tag("kpi_gate", "PASSED" if passed else "FAILED")
        except Exception as e:  # noqa: BLE001
            print(f"(mlflow tag skipped: {e})")
    from lakehouse.publish import publish_model_event

    champ = f"champion {champion.get('model_version')} AUROC {champion['metrics']['test']['auroc']:.3f}" \
        if champion else "no champion yet"
    publish_model_event("GATE_PASSED" if passed else "GATE_FAILED", meta, gate, stage="candidate",
                        trigger_reason=meta.get("trigger_reason"), detail=f"vs {champ}")
    return passed


def main() -> int:
    results = {name: gate_one(load_config(model=name)) for name in selected_models()}
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    finish(main())
