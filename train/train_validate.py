"""
Job mcc-02-train-validate: both heads (MCC_MODEL=all, or one) on the feature table of mcc-01.
Adapted from O-G-Asset-Integrity-Lakehouse train/train_validate.py (MLflow logging and model
events kept; the image candidates replaced by one tabular estimator).

Per head: gradient boosting (config/pipeline.yaml training) with isotonic calibration
(3-fold, on TRAIN); the fraud head's operating threshold is the F1-best point on VALID; KPIs are
measured once on TEST, the most recent claims (time split). Writes the candidate package to
serving.candidate_dir: model.joblib and model_meta.json (metrics, threshold, bands, feature
version and hash, git sha, training medians / modes / type means for serving and top factors,
the OOD reference for guardrails/input_checks.py, permutation importance on VALID).

MLOps: the run is logged to the CAI MLflow experiment (what serve/registry.py registers as an AI
Registry version), and a TRAINED event goes to ref.model_event with the trigger reason
(MCC_TRIGGER, set on mcc-01 by ci/retrain_trigger.py and carried in the table's manifest).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # CAI job kernels run the script without __file__; cwd is the project
        return Path(os.getcwd())


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.calibration import CalibratedClassifierCV  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score  # noqa: E402

from common import finish, git_sha, load_config, load_feature_table, selected_models  # noqa: E402
from features.feature_logic import feature_hash, feature_names, feature_version, matrix, spec  # noqa: E402
from guardrails.input_checks import ood_stats  # noqa: E402
from lakehouse.store import model_version  # noqa: E402


def estimator(cfg: dict):
    t = cfg["training"]
    gb = HistGradientBoostingClassifier(max_iter=int(t["max_iter"]), learning_rate=float(t["learning_rate"]),
                                        max_leaf_nodes=int(t["max_leaf_nodes"]),
                                        l2_regularization=float(t["l2_regularization"]),
                                        class_weight=t.get("class_weight"), random_state=0)
    return CalibratedClassifierCV(gb, method=t.get("calibrate", "isotonic"), cv=3)


def f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec[:-1] * rec[:-1] / np.clip(prec[:-1] + rec[:-1], 1e-9, None)
    return float(thr[int(np.argmax(f1))]) if len(thr) else 0.5


def metrics(y: np.ndarray, p: np.ndarray, thr: float) -> dict:
    pred = p >= thr
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    return {"auroc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
            "base_rate": float(y.mean()), "brier": float(brier_score_loss(y, p)),
            "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1),
            "flag_rate": float(pred.mean()), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": int(len(y))}


def log_to_mlflow(cfg: dict, meta: dict, model, meta_path: Path) -> str | None:
    """The run in the CAI experiment; None (and the candidate kept) where mlflow is unavailable."""
    try:
        import mlflow
        import mlflow.sklearn
    except ImportError:
        print("mlflow not installed (laptop / CI): experiment logging skipped", flush=True)
        return None
    try:
        mlflow.set_experiment(cfg["project"]["mlflow_experiment"])
        with mlflow.start_run(run_name=meta["model_version"]) as run:
            mlflow.log_params({"model": meta["model"], "label": meta["label"], "estimator": meta["estimator"],
                               "feature_version": meta["feature_version"], "feature_hash": meta["feature_hash"],
                               "git_sha": meta["git_sha"][:7], "threshold": round(meta["threshold"], 4),
                               "train_rows": meta["train_rows"], "trigger": meta.get("trigger_reason") or "manual",
                               **{f"training_{k}": v for k, v in cfg["training"].items()}})
            for split in ("valid", "test"):
                mlflow.log_metrics({f"{split}_{k}": float(v) for k, v in meta["metrics"][split].items()
                                    if isinstance(v, (int, float))})
            mlflow.sklearn.log_model(model, "model")
            meta["mlflow_run_id"] = run.info.run_id
            meta_path.write_text(json.dumps(meta, indent=2))
            mlflow.log_artifact(str(meta_path))
            print(f"MLflow run {run.info.run_id} in experiment {cfg['project']['mlflow_experiment']}", flush=True)
            return run.info.run_id
    except Exception as ex:  # noqa: BLE001
        print(f"WARNING mlflow logging failed, candidate kept: {ex}", flush=True)
        return None


def train(cfg: dict) -> dict:
    df, manifest = load_feature_table(cfg)
    if manifest["feature_hash"] != feature_hash():
        raise SystemExit("feature table was built with different feature logic: rerun mcc-01")
    label = cfg["model"]["label"]
    X, y = matrix(df), df[label].astype(int).to_numpy()
    sp = df["split"].to_numpy()
    tr, va, te = sp == "train", sp == "valid", sp == "test"
    model = estimator(cfg).fit(X[tr], y[tr])
    p_va, p_te = model.predict_proba(X[va])[:, 1], model.predict_proba(X[te])[:, 1]
    bands = cfg["evaluation"]["bands"]
    thr = f1_threshold(y[va], p_va) if cfg["model"]["name"] != "approval" else float(bands["low"])
    imp = permutation_importance(model, X[va], y[va], scoring="roc_auc", n_repeats=3, random_state=0)
    names = feature_names()
    importance = sorted(({"feature": n, "auc_drop": round(float(v), 4)} for n, v in zip(names, imp.importances_mean)),
                        key=lambda r: -r["auc_drop"])
    cand = ROOT / cfg["serving"]["candidate_dir"]
    cand.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, cand / "model.joblib")
    train_df = df[tr]
    meta = {"model": cfg["model"]["name"], "label": label, "estimator": "hist_gradient_boosting+isotonic",
            "threshold": thr, "bands": bands, "feature_version": feature_version(), "feature_hash": feature_hash(),
            "feature_names": names, "git_sha": git_sha(),
            "metrics": {"valid": metrics(y[va], p_va, thr), "test": metrics(y[te], p_te, thr)},
            "importance": importance[:15], "medians": manifest["medians"], "type_means": manifest["type_means"],
            "modes": {c: str(train_df[c].mode().iloc[0]) for c in spec()["categorical"]},
            "trained_at": datetime.now(timezone.utc).isoformat(), "train_rows": int(tr.sum()),
            "label_rows": int(len(df)), "snapshot": manifest["snapshot"], "test_from": manifest["splits"]["test"]["fnol_from"],
            "registry_name": cfg["model"].get("registry_name"),
            "trigger_reason": os.environ.get("MCC_TRIGGER") or manifest.get("trigger_reason", "manual"),
            "ood": ood_stats(X[tr])}
    meta["model_version"] = model_version(meta)
    meta_path = cand / "model_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    log_to_mlflow(cfg, meta, model, meta_path)
    from lakehouse.publish import publish_model_event

    t = meta["metrics"]["test"]
    publish_model_event("TRAINED", meta, stage="candidate", trigger_reason=meta["trigger_reason"],
                        detail=f"test auroc {t['auroc']:.3f}, pr_auc {t['pr_auc']:.3f} (base {t['base_rate']:.3f})")
    print(f"{meta['model']}: TEST AUROC {t['auroc']:.3f}, PR-AUC {t['pr_auc']:.3f} (base rate {t['base_rate']:.3f}), "
          f"Brier {t['brier']:.3f}; threshold {thr:.3f} flags {t['flag_rate']:.1%} (precision {t['precision']:.2f}, "
          f"recall {t['recall']:.2f}); top features {[r['feature'] for r in importance[:5]]}", flush=True)
    return meta


def main() -> int:
    for name in selected_models():
        train(load_config(model=name))
    return 0


if __name__ == "__main__":
    finish(main())
