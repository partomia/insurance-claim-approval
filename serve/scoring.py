"""
Scoring core shared by the mcc-approval endpoint (serve/predict.py), batch scoring
(lakehouse/score_claims.py), the drift job (monitor/drift.py) and the Copilot app
(backend/app/services/approval_model_service.py), so a claim gets the same score everywhere.

Champions: models/champion (approval head) and models/fraud/champion (fraud head), each a
model.joblib (calibrated gradient boosting) + model_meta.json (threshold, bands, metrics, feature
hash, training medians and type means, OOD reference). A head whose feature hash differs from
features/feature_logic.py refuses to load (process guardrail: feature hash lock).

Top factors: for each feature, the change in probability when that feature alone is set to its
training median (numeric) or most common value (categorical); the largest moves are the
factors, signed (raises / lowers).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADS = {"approval": "models/champion", "fraud": "models/fraud/champion"}


class Head:
    def __init__(self, name: str, folder: Path):
        import joblib

        from features.feature_logic import feature_hash

        self.name = name
        self.meta = json.loads((folder / "model_meta.json").read_text())
        if self.meta["feature_hash"] != feature_hash():
            raise RuntimeError(f"{name} champion was trained on different feature logic "
                               f"({self.meta['feature_hash']} != {feature_hash()})")
        self.model = joblib.load(folder / "model.joblib")

    def proba(self, X):
        return self.model.predict_proba(X)[:, list(self.model.classes_).index(1)]

    def info(self) -> dict:
        m, t = self.meta, self.meta["metrics"]["test"]
        return {"name": m["model"], "version": m.get("model_version"), "registry_name": m.get("registry_name"),
                "registry_version": m.get("registry_version"), "git_sha": m["git_sha"][:7],
                "feature_version": m["feature_version"], "test_auroc": round(t["auroc"], 3),
                "test_pr_auc": round(t["pr_auc"], 3), "threshold": m.get("threshold")}


def load_heads(root: Path = ROOT, folders: dict | None = None) -> tuple[dict, dict]:
    """{name: Head} for every champion present; {name: error} for those that failed to load."""
    heads, errors = {}, {}
    for name, rel in (folders or HEADS).items():
        d = root / rel
        if not (d / "model_meta.json").exists():
            continue
        try:
            heads[name] = Head(name, d)
        except Exception as e:  # noqa: BLE001
            errors[name] = f"{type(e).__name__}: {e}"
    return heads, errors


def _reference_row(meta: dict) -> dict:
    from features.feature_logic import spec

    ref = {c: meta["medians"].get(c) for c in spec()["numeric"]}
    ref.update(meta.get("modes") or {})
    return ref


def top_factors(head: Head, row: dict, k: int = 5) -> list[dict]:
    import numpy as np

    from features.feature_logic import raw_columns, vector

    ref = _reference_row(head.meta)
    cols = [c for c in raw_columns() if ref.get(c) is not None and row.get(c) != ref.get(c)]
    if not cols:
        return []
    rows = [row] + [{**row, c: ref[c]} for c in cols]
    p = head.proba(np.array([vector(r) for r in rows], dtype=float))
    out = []
    for c, q in zip(cols, p[1:]):
        delta = float(p[0] - q)          # how much this claim's value moves the probability vs typical
        if abs(delta) >= 0.005:
            v = row.get(c)
            out.append({"feature": c, "value": None if isinstance(v, float) and math.isnan(v) else v,
                        "typical": ref[c], "effect": round(delta, 4), "direction": "raises" if delta > 0 else "lowers"})
    return sorted(out, key=lambda f: -abs(f["effect"]))[:k]


def score_row(heads: dict, row: dict, policy: dict | None = None, factors: bool = True) -> dict:
    """One raw feature row (features.feature_logic.raw_columns) -> scores, bands, guardrails."""
    import numpy as np

    from features.feature_logic import vector
    from guardrails import input_checks, output_policy

    a, f = heads.get("approval"), heads.get("fraud")
    if a is None:
        return {"error": "no approval champion loaded"}
    x = np.array([vector(row)], dtype=float)
    checks = input_checks.claim_checks(row, policy) if policy is not None else []
    checks.append(input_checks.ood_check(x[0], a.meta.get("ood")))
    ok = all(c["passed"] for c in checks)
    p_a = float(a.proba(x)[0]) if ok else None
    p_f = float(f.proba(x)[0]) if ok and f else None
    out = output_policy.apply(p_a, p_f, a.meta["bands"], f.meta["threshold"] if f else None, checks)
    res = {"p_approve": None if p_a is None else round(p_a, 4), "p_fraud": None if p_f is None else round(p_f, 4),
           **out, "guardrails": checks,
           "model": {"approval": a.info(), **({"fraud": f.info()} if f else {})}}
    if ok and factors:
        res["top_factors"] = {"approval": top_factors(a, row), **({"fraud": top_factors(f, row)} if f else {})}
    return res


def agrees_with_rules(result: dict, rules_decision: str | None) -> bool | None:
    """Shadow-mode comparison: does the model's approval band point the same way as the rules?"""
    band = result.get("approval_band")
    d = (rules_decision or "").upper()
    if band in (None, "ABSTAIN", "UNCERTAIN", "NEUTRAL") or not d:
        return None
    wants_approve = d in ("APPROVED", "APPROVE", "AUTO_APPROVE", "PARTIAL", "PARTIALLY_APPROVED")
    return (band == "LIKELY_APPROVE") == wants_approve
