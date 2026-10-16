"""
Job mcc-06-score-claims: the champions' shadow scores for one business date into
gold.fact_model_score, through the same path as the endpoint (features.feature_logic.serving_row,
serve/scoring.py, the guardrails). Started by the lakehouse DAG after gold, or by hand.

Scored: the claims filed on the date and every claim still open in that date's snapshot of
gold.fact_claim, with the policy and garage scoring context (gold.scoring_context_*); their
history features (prior claims and rejections, garage volume and rejection score) are computed
point in time, strictly before each FNOL, as training does.

agrees_with_rules compares the model's approval band with the claim's decision so far (decided
claims) - the evidence mcc-07-promote-champion asks for. Every guardrail that fired goes to
ref.guardrail_event.

  MCC_BUSINESS_DATE=2026-10-16 python lakehouse/score_claims.py      # CDW Impala (MCC_IMPALA_USER)
  python lakehouse/score_claims.py --local --business-date 2026-10-16 # local Spark warehouse
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # CAI job kernels run the script without __file__; cwd is the project
        return Path(os.getcwd())


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

from common import finish, parse_args  # noqa: E402

PREFIX = os.environ.get("MCC_DB_PREFIX", "rsingh_mcc")
SCORE_COLUMNS = [
    ("claim_id", "STRING"), ("policy_number", "STRING"), ("golden_customer_id", "STRING"), ("claim_type", "STRING"),
    ("fnol_date", "DATE"), ("status", "STRING"), ("decided_by", "STRING"), ("amount_requested", "DOUBLE"),
    ("p_approve", "DOUBLE"), ("p_fraud", "DOUBLE"), ("approval_band", "STRING"), ("fraud_band", "STRING"),
    ("agrees_with_rules", "BOOLEAN"), ("top_factor", "STRING"), ("abstain_reason", "STRING"),
    ("approval_version", "STRING"), ("fraud_version", "STRING"), ("scored_at", "TIMESTAMP")]


class Source:
    """SELECTs on CDW Impala, or the local Spark warehouse (same SQL)."""

    def __init__(self, local: bool):
        self.local = local
        if local:
            import time

            os.environ["TZ"] = "UTC"     # collected timestamps as stored, like Impala returns them
            time.tzset()
            sys.path.insert(0, str(ROOT / "scripts"))
            from run_local import local_spark

            self.spark = local_spark(ROOT / "data" / "warehouse")
        else:
            from lakehouse.store import ImpalaStore

            self.store = ImpalaStore()

    def query(self, sql: str) -> list[dict]:
        if self.local:
            return [r.asDict() for r in self.spark.sql(sql).collect()]
        return self.store.query(sql)


def t(name: str) -> str:
    layer, table = name.split(".")
    return f"{PREFIX}_{layer}.{table}"


def latest_date(src: Source) -> date:
    v = src.query(f"SELECT MAX(business_date) AS d FROM {t('gold.fact_claim')}")[0]["d"]
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def claims(src: Source, d: date, days: int = 1) -> list[dict]:
    """Claims filed in the `days` up to d, and every claim open on d, with their scoring context.
    Their history features are recomputed point in time (strictly before each FNOL, the
    build_gold.training_features rules): the end-of-day context would count the claim itself and
    the claims filed after it."""
    since = (d - timedelta(days=days - 1)).isoformat()
    fc, on = t("gold.fact_claim"), f"business_date = DATE '{d.isoformat()}'"
    scope = f"{on} AND (fnol_date >= DATE '{since}' OR status NOT IN ('APPROVED', 'REJECTED'))"
    rows = src.query(f"""
        SELECT claim_id, policy_number, golden_customer_id, garage_id, claim_type, amount_requested,
               incident_ts, fnol_ts, fnol_date, police_report, vehicle_vin, crash_event_match, status, decided_by
        FROM {fc} WHERE {scope}""")
    hist = {r["claim_id"]: r for r in src.query(f"""
        SELECT s.claim_id,
               SUM(CASE WHEN h.golden_customer_id = s.golden_customer_id
                         AND h.fnol_ts >= s.fnol_ts - INTERVAL 365 DAYS THEN 1 ELSE 0 END) AS prior_claims_12m,
               SUM(CASE WHEN h.golden_customer_id = s.golden_customer_id
                         AND h.fnol_ts >= s.fnol_ts - INTERVAL 365 DAYS
                         AND h.status = 'REJECTED' AND h.decided_ts < s.fnol_ts THEN 1 ELSE 0 END) AS prior_rejected_12m,
               SUM(CASE WHEN h.garage_id = s.garage_id AND h.fnol_ts >= s.fnol_ts - INTERVAL 30 DAYS
                        THEN 1 ELSE 0 END) AS garage_claims_30d,
               SUM(CASE WHEN h.garage_id = s.garage_id AND h.decided_ts < s.fnol_ts THEN 1 ELSE 0 END) AS g_decided,
               SUM(CASE WHEN h.garage_id = s.garage_id AND h.decided_ts < s.fnol_ts AND h.status = 'REJECTED'
                        THEN 1 ELSE 0 END) AS g_rejected
        FROM (SELECT claim_id, golden_customer_id, garage_id, fnol_ts FROM {fc} WHERE {scope}) s
        JOIN (SELECT golden_customer_id, garage_id, fnol_ts, decided_ts, status FROM {fc} WHERE {on}) h
          ON (h.golden_customer_id = s.golden_customer_id OR h.garage_id = s.garage_id) AND h.fnol_ts < s.fnol_ts
        GROUP BY s.claim_id""")}
    pol = {r["policy_number"]: r for r in src.query(f"SELECT * FROM {t('gold.scoring_context_policy')}")}
    gar = {r["garage_id"]: r for r in src.query(f"SELECT * FROM {t('gold.scoring_context_garage')}")}
    out = []
    for r in rows:
        h = hist.get(r["claim_id"]) or {}
        p = dict(pol.get(r["policy_number"]) or {})
        g = dict(gar.get(r["garage_id"]) or {})
        if p:
            p["prior_claims_12m"] = int(h.get("prior_claims_12m") or 0)
            p["prior_rejected_12m"] = int(h.get("prior_rejected_12m") or 0)
        if g:
            g["garage_claims_30d"] = int(h.get("garage_claims_30d") or 0)
            g["garage_risk_score"] = round((int(h.get("g_rejected") or 0) + 1) / (int(h.get("g_decided") or 0) + 5), 4)
        out.append({"claim": r, "policy": p or None, "garage": g or None})
    return out


def score(items: list[dict], heads: dict) -> tuple[list[dict], list[tuple[dict, dict]]]:
    from features.feature_logic import serving_row
    from serve import scoring

    means = heads["approval"].meta["type_means"]
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    out, raw = [], []
    for it in items:
        c = it["claim"]
        row = serving_row(c, it["policy"], it["garage"], means)
        res = scoring.score_row(heads, row, it["policy"] or {}, factors=True)
        decided = c["status"] if c["status"] in ("APPROVED", "REJECTED") else None
        fac = (res.get("top_factors") or {}).get("approval") or []
        raw.append((row, res))
        out.append({"claim_id": c["claim_id"], "policy_number": c["policy_number"],
                    "golden_customer_id": c["golden_customer_id"], "claim_type": c["claim_type"],
                    "fnol_date": c["fnol_date"], "status": c["status"], "decided_by": c["decided_by"],
                    "amount_requested": float(c["amount_requested"]) if c["amount_requested"] is not None else None,
                    "p_approve": res.get("p_approve"), "p_fraud": res.get("p_fraud"),
                    "approval_band": res.get("approval_band"), "fraud_band": res.get("fraud_band"),
                    "agrees_with_rules": scoring.agrees_with_rules(res, decided),
                    "top_factor": f"{fac[0]['feature']} {fac[0]['direction']}" if fac else None,
                    "abstain_reason": res.get("band_reason") if res.get("approval_band") == "ABSTAIN" else None,
                    "approval_version": heads["approval"].meta.get("model_version"),
                    "fraud_version": heads["fraud"].meta.get("model_version") if "fraud" in heads else None,
                    "scored_at": now})
    return out, raw


def write(src: Source, d: date, rows: list[dict]) -> str:
    if src.local:
        import pandas as pd

        p = ROOT / "outputs" / "scores" / f"fact_model_score_{d.isoformat()}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(p, index=False)
        return str(p.relative_to(ROOT))
    from lakehouse.store import lit

    s, table = src.store, t("gold.fact_model_score")
    cols = ", ".join(f"{c} {ty}" for c, ty in SCORE_COLUMNS)
    s.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols}, business_date DATE) PARTITIONED BY SPEC (business_date) "
              f"STORED AS ICEBERG TBLPROPERTIES ('format-version'='2')")
    s.execute(f"DELETE FROM {table} WHERE business_date = DATE '{d.isoformat()}'")
    names = [c for c, _ in SCORE_COLUMNS] + ["business_date"]
    for i in range(0, len(rows), 200):
        values = ", ".join("(" + ", ".join(lit(r.get(c) if c != "business_date" else d) for c in names) + ")"
                           for r in rows[i:i + 200])
        s.execute(f"INSERT INTO {table} ({', '.join(names)}) VALUES {values}")
    return table


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    bands = {}
    for r in rows:
        bands[r["approval_band"]] = bands.get(r["approval_band"], 0) + 1
    judged = [r["agrees_with_rules"] for r in rows if r["agrees_with_rules"] is not None]
    return {"scored": n, "approval_bands": bands,
            "fraud_review": sum(1 for r in rows if r["fraud_band"] == "FRAUD_REVIEW"),
            "agreement": round(sum(judged) / len(judged), 4) if judged else None, "compared": len(judged)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--business-date", default=os.environ.get("MCC_BUSINESS_DATE"))
    ap.add_argument("--local", action="store_true")
    args = parse_args(ap)
    from guardrails import events
    from lakehouse.store import publish
    from serve import scoring

    heads, errors = scoring.load_heads(ROOT)
    if "approval" not in heads:
        raise SystemExit(f"no approval champion: {errors or 'run the chain mcc-01..04 first'}")
    src = Source(args.local)
    d = date.fromisoformat(args.business_date) if args.business_date else latest_date(src)
    rows, raw = score(claims(src, d), heads)
    where = write(src, d, rows)
    version = heads["approval"].meta.get("model_version", "")
    g = [e for (_, res), r in zip(raw, rows) for e in events.rows(res.get("guardrail_events", []), r["claim_id"],
                                                                   version, "mcc-06-score-claims")]
    events.log_local(g)
    if not args.local:
        publish("guardrail_event", g)
    print(json.dumps({"business_date": d.isoformat(), "table": where, **summary(rows),
                      "guardrail_events": len(g)}, default=str), flush=True)
    return 0


if __name__ == "__main__":
    finish(main())
