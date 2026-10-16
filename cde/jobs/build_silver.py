"""
Stage 2 - Silver: the sources' state as of one business date, typed, deduplicated, CDC applied.

Every silver table is a snapshot per business date (partition business_date), rebuilt from all
bronze batches up to and including the date, so a re-run replaces exactly that date and a later
date never changes an earlier one.

  garage             latest register row per garage_id
  policy             day-1 extract + CDC after-images in commit order; the latest version per
                     policy_number (last_change_source EXTRACT / CDC); CDC for a policy the
                     extract never had -> silver.orphan (UNKNOWN_POLICY)
  policy_clause      latest per (policy_number, section_ref)
  bureau_profile     latest per bureau_ref; mobile normalised to its last 10 digits, name to
                     upper-case letters
  claim              latest snapshot per claim_id (a re-sent older snapshot never overrides a
                     newer one), then the latest status event if it is newer; a claim on a policy
                     silver does not hold -> silver.orphan (ORPHAN_POLICY)
  claim_status_event every status event up to the date, deduplicated
  crash_event        batch crash events + the Kafka stream (bronze.stream_telematics), one row per
                     event_id (source BATCH, STREAM or BOTH)

Usage:
  spark-submit build_silver.py --business-date 2026-10-12 [--db-prefix P]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcc_common as C  # noqa: E402
from pyspark.sql import DataFrame, Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

STAGE = "silver"
ORPHAN_SCHEMA = "entity string, record_key string, reason string, detail string, business_date date"
STATUS_RANKS = (("FILED", 0), ("UNDER_REVIEW", 1), ("APPROVED", 2), ("REJECTED", 2))


def status_rank(col):
    # built per call: a Column needs an active SparkContext, which does not exist at import time
    return F.create_map(*[F.lit(x) for kv in STATUS_RANKS for x in kv])[col]


def parser():
    return C.base_parser(__doc__)


def _bronze(spark, names, entity: str, d) -> DataFrame | None:
    t = names.t("bronze", entity)
    if not C.table_exists(spark, t):
        return None
    return spark.table(t).where(F.col("_business_date") <= F.lit(d.isoformat()).cast("date"))


def _typed(df: DataFrame, entity: str, keep=()) -> DataFrame:
    contract = C.contracts()[entity]
    return df.select(*C.typed_columns(contract), *keep)


def _latest(df: DataFrame, keys, *order) -> DataFrame:
    w = Window.partitionBy(*keys).orderBy(*order)
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


def norm_mobile(col):
    digits = F.regexp_replace(col, "[^0-9]", "")
    return F.when(F.length(digits) >= 10, F.substring(digits, -10, 10))


def norm_name(col):
    return F.trim(F.regexp_replace(F.upper(col), "[^A-Z ]", ""))


# ---------------------------------------------------------------- entities


def garage(spark, names, d):
    b = _bronze(spark, names, "gn_garage", d)
    return _latest(_typed(b, "gn_garage", ["_business_date"]), ["garage_id"], F.desc("_business_date")).drop("_business_date")


def policy(spark, names, d) -> tuple[DataFrame, DataFrame]:
    contract = C.contracts()["pa_policy"]
    cols = [c["name"] for c in contract["columns"]]
    ext = _bronze(spark, names, "pa_policy", d)
    ext = ext.select(*cols, F.lit("EXTRACT").alias("last_change_source"), "_business_date")
    cdc = _bronze(spark, names, "pa_policy_cdc", d)
    frames = [ext]
    if cdc is not None:
        schema = ", ".join(f"`{c}` string" for c in cols)
        after = F.from_json("after", schema)
        frames.append(cdc.where(F.col("op").isin("c", "u", "r"))
                      .select(*[after[c].alias(c) for c in cols], F.lit("CDC").alias("last_change_source"),
                              "_business_date"))
    allv = frames[0]
    for f in frames[1:]:
        allv = allv.unionByName(f)
    typed = allv.select(*C.typed_columns(contract), "last_change_source", "_business_date")
    known = ext.select("policy_number").distinct()
    versions = typed.groupBy("policy_number").agg(F.count("*").alias("version_count"))
    cur = (_latest(typed, ["policy_number"], F.desc("updated_at"), F.desc("_business_date"))
           .join(versions, "policy_number"))
    orphans = (cur.join(known, "policy_number", "left_anti")
               .select(F.lit("policy").alias("entity"), F.col("policy_number").alias("record_key"),
                       F.lit("UNKNOWN_POLICY").alias("reason"),
                       F.lit("CDC event for a policy the policy-admin extract never contained").alias("detail")))
    cur = (cur.join(known, "policy_number")
           .withColumnRenamed("updated_at", "last_change_ts")
           .withColumn("holder_mobile_norm", norm_mobile("holder_mobile"))
           .withColumn("holder_name_norm", norm_name("holder_name"))
           .withColumn("holder_email", F.lower(F.trim("holder_email")))
           .drop("_business_date"))
    return cur, orphans


def clause(spark, names, d):
    b = _bronze(spark, names, "pa_clause", d)
    return _latest(_typed(b, "pa_clause", ["_business_date"]), ["policy_number", "section_ref"],
                   F.desc("_business_date")).drop("_business_date")


def bureau(spark, names, d):
    b = _bronze(spark, names, "bu_profile", d)
    t = _typed(b, "bu_profile", ["_business_date"])
    return (_latest(t, ["bureau_ref"], F.desc("as_of_date"), F.desc("_business_date")).drop("_business_date")
            .withColumn("mobile_norm", norm_mobile("mobile")).withColumn("name_norm", norm_name("full_name")))


def status_events(spark, names, d):
    b = _bronze(spark, names, "cl_claim_status", d)
    if b is None:
        return None
    return _typed(b, "cl_claim_status").dropDuplicates(["claim_id", "event_ts", "to_status"])


def claim(spark, names, d, policies: DataFrame, events: DataFrame | None) -> tuple[DataFrame, DataFrame, int]:
    b = _bronze(spark, names, "cl_claim", d)
    t = _typed(b, "cl_claim", ["_business_date"]).withColumn("_rank", status_rank(F.col("status")))
    n_snapshots = t.count()
    cur = _latest(t, ["claim_id"], F.desc("_rank"), F.desc_nulls_last("decided_ts"), F.desc("_business_date"))
    resent = n_snapshots - t.select("claim_id").distinct().count()
    if events is not None:
        last = _latest(events.withColumn("_er", status_rank(F.col("to_status"))), ["claim_id"],
                       F.desc("_er"), F.desc("event_ts")).select(
            "claim_id", F.col("event_ts").alias("_ev_ts"), F.col("to_status").alias("_ev_status"),
            F.col("amount_approved").alias("_ev_amount"), F.col("reason_code").alias("_ev_reason"),
            F.col("decided_by").alias("_ev_decided_by"))
        cur = cur.join(last, "claim_id", "left")
        newer = (F.col("_ev_ts").isNotNull() & (status_rank(F.col("_ev_status")) >= F.col("_rank")))
        decided = F.col("_ev_status").isin("APPROVED", "REJECTED")
        cur = (cur.withColumn("status", F.when(newer, F.col("_ev_status")).otherwise(F.col("status")))
               .withColumn("amount_approved", F.when(newer & decided, F.col("_ev_amount")).otherwise(F.col("amount_approved")))
               .withColumn("decided_ts", F.when(newer & decided, F.col("_ev_ts")).otherwise(F.col("decided_ts")))
               .withColumn("decided_by", F.when(newer & decided, F.col("_ev_decided_by")).otherwise(F.col("decided_by")))
               .withColumn("reason_code", F.when(newer & decided, F.col("_ev_reason")).otherwise(F.col("reason_code")))
               .withColumn("status_source", F.when(newer, F.lit("STATUS_EVENT")).otherwise(F.lit("SNAPSHOT")))
               .drop("_ev_ts", "_ev_status", "_ev_amount", "_ev_reason", "_ev_decided_by"))
    else:
        cur = cur.withColumn("status_source", F.lit("SNAPSHOT"))
    cur = cur.drop("_rank", "_business_date")
    known = policies.select("policy_number")
    orphans = (cur.join(known, "policy_number", "left_anti")
               .select(F.lit("claim").alias("entity"), F.col("claim_id").alias("record_key"),
                       F.lit("ORPHAN_POLICY").alias("reason"),
                       F.concat(F.lit("policy "), F.col("policy_number"), F.lit(" not in silver.policy")).alias("detail")))
    cur = (cur.join(known, "policy_number")
           .withColumn("claimant_mobile_norm", norm_mobile("claimant_mobile"))
           .withColumn("claimant_name_norm", norm_name("claimant_name")))
    return cur, orphans, resent


def crash(spark, names, d):
    b = _bronze(spark, names, "tm_crash", d)
    batch = _typed(b, "tm_crash").withColumn("_src", F.lit("BATCH")) if b is not None else None
    st = names.t("bronze", "stream_telematics")
    stream = None
    if C.table_exists(spark, st):
        stream = (spark.table(st).where(F.col("event_date") <= F.lit(d.isoformat()).cast("date"))
                  .select("event_id", "vin", "event_ts", "g_force", "speed_kmph", "lat", "lon", "device_id")
                  .withColumn("_src", F.lit("STREAM")))
    frames = [f for f in (batch, stream) if f is not None]
    if not frames:
        return None
    df = frames[0] if len(frames) == 1 else frames[0].unionByName(frames[1])
    srcs = df.groupBy("event_id").agg(F.array_sort(F.collect_set("_src")).alias("_srcs"))
    return (_latest(df, ["event_id"], F.asc("_src")).join(srcs, "event_id")
            .withColumn("source", F.when(F.size("_srcs") > 1, F.lit("BOTH")).otherwise(F.col("_srcs")[0]))
            .drop("_src", "_srcs"))


# ---------------------------------------------------------------- run


def _write(spark, names, audit, name: str, df: DataFrame, d, sources: str, ttype: str, rows_in=None, details=""):
    target = names.t("silver", name)
    before = C.snapshot_id(spark, target)
    out = df.withColumn("business_date", F.lit(d.isoformat()).cast("date"))
    C.write_partitions(out, target, ["business_date"])
    n = out.count()
    audit.load(STAGE, name, "COMMITTED", rows_in=rows_in, rows_out=n, snapshot_before=before,
               snapshot_after=C.snapshot_id(spark, target), message=details)
    audit.transform(f"build {name}", ttype, sources, target, rows_in, n, details)
    print(f"silver.{name}: {n} rows" + (f" ({details})" if details else ""), flush=True)
    return n


def run(spark, argv=None) -> dict:
    args = C.parse(parser(), argv)
    names = C.Names(args.db_prefix)
    C.ensure_databases(spark, names)
    d = args.business_date
    C.require_completed(spark, names, "bronze", d)
    audit = C.Audit(spark, names, "build_silver", d, args.pipeline_run)
    audit.load(STAGE, "*", "STARTED")
    out = {}
    try:
        out["garage"] = _write(spark, names, audit, "garage", garage(spark, names, d), d, "bronze.gn_garage", "deduplicate")
        pol, pol_orphans = policy(spark, names, d)
        pol = pol.cache()
        out["policy"] = _write(spark, names, audit, "policy", pol, d, "bronze.pa_policy,bronze.pa_policy_cdc",
                               "standardise", details="extract + CDC after-images, latest version per policy")
        out["policy_clause"] = _write(spark, names, audit, "policy_clause", clause(spark, names, d), d,
                                      "bronze.pa_clause", "deduplicate")
        out["bureau_profile"] = _write(spark, names, audit, "bureau_profile", bureau(spark, names, d), d,
                                       "bronze.bu_profile", "standardise", details="latest per bureau_ref")
        ev = status_events(spark, names, d)
        if ev is not None:
            out["claim_status_event"] = _write(spark, names, audit, "claim_status_event", ev, d,
                                               "bronze.cl_claim_status", "deduplicate")
        cl, cl_orphans, resent = claim(spark, names, d, pol, ev)
        out["claim"] = _write(spark, names, audit, "claim", cl, d, "bronze.cl_claim,bronze.cl_claim_status",
                              "survive", details=f"latest snapshot + newer status event; {resent} re-sent snapshot(s)")
        cr = crash(spark, names, d)
        if cr is not None:
            out["crash_event"] = _write(spark, names, audit, "crash_event", cr, d,
                                        "bronze.tm_crash,bronze.stream_telematics", "deduplicate",
                                        details="batch + stream, one row per event_id")
        orphans = pol_orphans.unionByName(cl_orphans)
        out["orphan"] = _write(spark, names, audit, "orphan", orphans, d, "silver.policy,silver.claim", "validate",
                               details="parked, not dropped")
        pol.unpersist()
        audit.load(STAGE, "*", "COMPLETED", rows_out=sum(out.values()))
    except Exception as e:
        audit.load(STAGE, "*", "FAILED", message=C.error_summary(e))
        raise
    finally:
        audit.flush()
    return out


def main() -> int:
    spark = C.get_spark("mcc-build-silver")
    run(spark, sys.argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
