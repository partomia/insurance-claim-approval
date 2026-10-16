"""
Job mcc-01-build-features: the training table of both heads from gold.claim_training_features
(one row per decided claim, point-in-time features, labels approved and fraud_confirmed), the
latest business-date snapshot.

Source: CDW Impala (MCC_IMPALA_USER set), else the local parquet export of the same table
(config/pipeline.yaml data.local_export; laptop and CI), or MCC_FEATURE_SOURCE=local to force it.

Split by time on fnol_ts (train < valid < test, data.split), so TEST is the most recent claims
and nothing from the future leaks into training. Writes
<features.store_dir>/v<version>/features.parquet and manifest.json (feature version and hash,
source, snapshot date, split counts and base rates, mean amount per claim type for serving),
which training, the gate and the endpoint check.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # CAI job kernels run the script without __file__; cwd is the project
        return Path(os.getcwd())


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from common import feature_table_dir, finish, load_config  # noqa: E402
from features.feature_logic import feature_hash, feature_version, raw_columns, spec  # noqa: E402

KEYS = ["claim_id", "policy_number", "golden_customer_id", "fnol_ts", "business_date", "approved", "fraud_confirmed"]


def from_impala(cfg: dict) -> tuple[pd.DataFrame, str]:
    from lakehouse.store import ImpalaStore

    s = ImpalaStore()
    t = s.t(f"gold.{cfg['data']['source_table']}")
    rows = s.query(f"SELECT {', '.join(KEYS + raw_columns())} FROM {t} "
                   f"WHERE business_date = (SELECT MAX(business_date) FROM {t})")
    return pd.DataFrame(rows), f"impala {t}"


def from_local(cfg: dict) -> tuple[pd.DataFrame, str]:
    p = ROOT / cfg["data"]["local_export"]
    if not p.exists():
        raise SystemExit(f"no {p}: export gold.claim_training_features (scripts/run_local.py export) "
                         "or set MCC_IMPALA_USER")
    df = pd.read_parquet(p)
    if "business_date" in df and df["business_date"].nunique() > 1:
        df = df[df["business_date"] == df["business_date"].max()]
    return df[KEYS + raw_columns()], f"parquet {cfg['data']['local_export']}"


def load(cfg: dict) -> tuple[pd.DataFrame, str]:
    if os.environ.get("MCC_FEATURE_SOURCE") != "local" and os.environ.get("MCC_IMPALA_USER"):
        return from_impala(cfg)
    return from_local(cfg)


def time_split(df: pd.DataFrame, split: dict) -> pd.Series:
    order = df["fnol_ts"].rank(method="first") / len(df)
    tr, va = split["train"], split["train"] + split["valid"]
    return pd.Series(["train" if q <= tr else "valid" if q <= va else "test" for q in order], index=df.index)


def build(cfg: dict, df: pd.DataFrame, source: str) -> dict:
    df = df.copy()
    df["fnol_ts"] = pd.to_datetime(df["fnol_ts"])
    for c in spec()["numeric"] + ["approved", "fraud_confirmed"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    unknown = {c: sorted(set(df[c].dropna()) - set(v)) for c, v in spec()["categorical"].items()}
    unknown = {c: v for c, v in unknown.items() if v}
    if unknown:
        raise SystemExit(f"categorical values not in config/pipeline.yaml features: {unknown}")
    if len(df) < int(cfg["data"]["min_rows"]):
        raise SystemExit(f"{len(df)} rows < data.min_rows {cfg['data']['min_rows']}")
    df["split"] = time_split(df, cfg["data"]["split"])
    out = feature_table_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    df.sort_values("fnol_ts").to_parquet(out / "features.parquet", index=False)
    train = df[df["split"] == "train"]
    by = {sp: {"rows": int((df["split"] == sp).sum()),
               "approved_rate": round(float(df.loc[df["split"] == sp, "approved"].mean()), 4),
               "fraud_rate": round(float(df.loc[df["split"] == sp, "fraud_confirmed"].mean()), 4),
               "fnol_from": str(df.loc[df["split"] == sp, "fnol_ts"].min()),
               "fnol_to": str(df.loc[df["split"] == sp, "fnol_ts"].max())} for sp in ("train", "valid", "test")}
    manifest = {"feature_version": feature_version(), "feature_hash": feature_hash(), "source": source,
                "snapshot": str(df["business_date"].max()), "rows": int(len(df)), "splits": by,
                # serving's amount_vs_type_mean: the mean over every claim up to the snapshot, closest to
                # the expanding mean training sees for the most recent claims
                "type_means": {k: round(float(v), 2) for k, v in df.groupby("claim_type")["amount_requested"].mean().items()},
                "medians": {c: (None if pd.isna(v) else float(v)) for c, v in train[spec()["numeric"]].median().items()},
                "trigger_reason": os.environ.get("MCC_TRIGGER", "manual")}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> int:
    t0 = time.time()
    cfg = load_config()
    df, source = load(cfg)
    m = build(cfg, df, source)
    print(json.dumps({**m, "seconds": round(time.time() - t0, 1)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    finish(main())
