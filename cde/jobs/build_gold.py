"""
Stage 4 - Gold: dimensions, facts, the training feature table and the Copilot app's tables.

  dim_customer      SCD2 over the MDM golden record (mobile, city, credit band, policies held)
  dim_policy        SCD2 over silver.policy (status, premium, NCB, term, holder mobile)
  dim_garage        current garage register
  fact_claim        one row per claim as of the date (partition business_date): golden customer,
                    the policy and customer versions valid at FNOL, garage, VIN check, telematics
                    crash match (same VIN, within 2 h of the incident, g >= 2), delay, cycle time
  claim_training_features  one row per decided claim, every feature point-in-time (only what was
                    known before the claim's FNOL), labels approved and fraud_confirmed
  scoring_context   the same history features as of now, per policy and per garage: what the app
                    sends the model endpoint for a new claim (one definition, no train/serve skew)
  app tables        policy_master, policy_clauses, policy_risk_signals, garage_risk_signals,
                    customer_profile_signals: the columns the Copilot app has always read
                    (backend/scripts/ingest_lakehouse.py), from the governed pipeline
  ref               kpi_definition, kpi_parameter from config/kpi.json

Usage:
  spark-submit build_gold.py --business-date 2026-10-12 [--db-prefix P]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcc_common as C  # noqa: E402
from pyspark.sql import DataFrame, Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

STAGE = "gold"
OPEN_END = "9999-12-31"
CUSTOMER_TRACKED = ["mobile", "city", "credit_band", "policies_held", "full_name"]
POLICY_TRACKED = ["status", "premium_amount", "ncb_pct", "effective_date", "expiry_date", "holder_mobile",
                  "coverage_limit"]
CRASH_WINDOW_S = 2 * 3600
CRASH_MIN_G = 2.0


def parser():
    return C.base_parser(__doc__)


def credit_band(col):
    b = C.CFG["credit_bands"]
    return (F.when(col.isNull(), "NO_HIT").when(col >= b["excellent_min"], "EXCELLENT")
            .when(col >= b["good_min"], "GOOD").when(col >= b["fair_min"], "FAIR").otherwise("POOR"))


def yn(col):
    return F.coalesce(col == "Y", F.lit(False))


# ---------------------------------------------------------------- SCD2


def scd2(snapshots: DataFrame, key: str, tracked: list[str], sk: str) -> DataFrame:
    """Versions from per-date snapshots: a new version whenever a tracked attribute changes."""
    h = F.sha2(F.concat_ws("\u0001", *[F.coalesce(F.col(c).cast("string"), F.lit("\u0000")) for c in tracked]), 256)
    w = Window.partitionBy(key).orderBy("business_date")
    v = (snapshots.withColumn("_h", h).withColumn("_prev", F.lag("_h").over(w))
         .where(F.col("_prev").isNull() | (F.col("_h") != F.col("_prev")))
         .withColumn("valid_from", F.col("business_date")))
    w2 = Window.partitionBy(key).orderBy("valid_from")
    last_seen = snapshots.groupBy(key).agg(F.max("business_date").alias("_last"))
    latest = snapshots.agg(F.max("business_date")).collect()[0][0]
    v = (v.join(last_seen, key)
         .withColumn("_next", F.lead("valid_from").over(w2))
         .withColumn("valid_to", F.coalesce(F.date_sub("_next", 1),
                                            F.when(F.col("_last") < F.lit(latest), F.col("_last"))
                                            .otherwise(F.lit(OPEN_END).cast("date"))))
         .withColumn("is_current", F.col("valid_to") == F.lit(OPEN_END).cast("date"))
         .withColumn("version", F.row_number().over(w2))
         .withColumn(sk, F.substring(F.sha2(F.concat_ws("|", F.col(key), F.col("valid_from").cast("string")), 256), 1, 16)))
    return v.drop("_h", "_prev", "_next", "_last", "business_date")


def version_at(fact: DataFrame, dim: DataFrame, key: str, sk: str, at_col: str) -> DataFrame:
    """The dimension version valid on at_col's date; before the first version, the first version."""
    d = dim.select(key, sk, "valid_from", "valid_to", "version")
    j = fact.join(d, key, "left").withColumn(
        "_ok", (F.to_date(at_col) >= F.col("valid_from")) & (F.to_date(at_col) <= F.col("valid_to")))
    w = Window.partitionBy("claim_id").orderBy(F.desc("_ok"), F.asc("version"))
    return (j.withColumn("_rn", F.row_number().over(w)).where("_rn = 1")
            .drop("_rn", "_ok", "valid_from", "valid_to", "version"))


# ---------------------------------------------------------------- facts and features


def fact_claim(claims, vehicles, garages, crashes, dim_policy, dim_customer) -> DataFrame:
    veh = vehicles.select("policy_number", F.col("vin").alias("policy_vin"), "golden_customer_id")
    g = garages.select("garage_id", "garage_name", F.col("network_status").alias("garage_network_status"))
    f = (claims.join(veh, "policy_number", "left").join(g, "garage_id", "left")
         .withColumn("vin_mismatch", F.col("vehicle_vin") != F.col("policy_vin"))
         .withColumn("report_delay_days", F.round((F.unix_timestamp("fnol_ts") - F.unix_timestamp("incident_ts")) / 86400, 3))
         .withColumn("cycle_days", F.round((F.unix_timestamp("decided_ts") - F.unix_timestamp("fnol_ts")) / 86400, 3))
         .withColumn("decision_date", F.to_date("decided_ts"))
         .withColumn("fnol_date", F.to_date("fnol_ts")))
    if crashes is not None:
        c = crashes.where(F.col("g_force") >= CRASH_MIN_G).select(F.col("vin").alias("_cvin"), F.col("event_ts").alias("_cts"),
                                                                  F.col("event_id").alias("_cid"))
        m = (f.select("claim_id", "policy_vin", "incident_ts")
             .join(c, (F.col("_cvin") == F.col("policy_vin"))
                   & (F.abs(F.unix_timestamp("_cts") - F.unix_timestamp("incident_ts")) <= CRASH_WINDOW_S))
             .groupBy("claim_id").agg(F.min("_cid").alias("crash_event_id")))
        f = f.join(m, "claim_id", "left")
        enrolled = crashes.select(F.col("vin").alias("policy_vin")).distinct().withColumn("telematics_enrolled", F.lit(True))
        f = f.join(enrolled, "policy_vin", "left").fillna({"telematics_enrolled": False})
    else:
        f = f.withColumn("crash_event_id", F.lit(None).cast("string")).withColumn("telematics_enrolled", F.lit(False))
    f = f.withColumn("crash_event_match", F.col("crash_event_id").isNotNull())
    f = version_at(f, dim_policy, "policy_number", "policy_sk", "fnol_ts")
    f = version_at(f, dim_customer, "golden_customer_id", "customer_sk", "fnol_ts")
    return f.drop("claimant_mobile_norm", "claimant_name_norm")


def training_features(fact: DataFrame, policy_cur: DataFrame, golden: DataFrame) -> DataFrame:
    """Point-in-time features of every claim (history strictly before its FNOL) and both labels."""
    base = (fact.join(policy_cur.select("policy_number", "coverage_limit", "ncb_pct", "vehicle_year", "customer_since"),
                      "policy_number", "left")
            .join(golden.select("golden_customer_id", "policies_held", "credit_score", "years_licensed",
                                "traffic_violations_3y", "other_insurer_claims_3y"), "golden_customer_id", "left"))
    t = F.unix_timestamp
    type_w = Window.partitionBy("claim_type").orderBy(t("fnol_ts")).rowsBetween(Window.unboundedPreceding, -1)
    type_all = Window.partitionBy("claim_type")
    base = base.withColumn("_type_mean", F.coalesce(F.avg("amount_requested").over(type_w),
                                                    F.avg("amount_requested").over(type_all)))
    # customer history: claims filed in the 365 days before, and those already rejected by then
    h = fact.select(F.col("golden_customer_id").alias("_g"), F.col("fnol_ts").alias("_f"),
                    F.col("decided_ts").alias("_d"), F.col("status").alias("_s"))
    hist = (base.select("claim_id", "golden_customer_id", "fnol_ts")
            .join(h, (F.col("_g") == F.col("golden_customer_id")) & (F.col("_f") < F.col("fnol_ts"))
                  & (F.col("_f") >= F.col("fnol_ts") - F.expr("INTERVAL 365 DAYS")))
            .groupBy("claim_id").agg(F.count("*").alias("prior_claims_12m"),
                                     F.sum(F.when((F.col("_s") == "REJECTED") & (F.col("_d") < F.col("fnol_ts")), 1)
                                           .otherwise(0)).alias("prior_rejected_12m")))
    # garage history: rejections among its decided claims, claims in the last 30 days
    gh = fact.select(F.col("garage_id").alias("_gid"), F.col("fnol_ts").alias("_f"), F.col("decided_ts").alias("_d"),
                     F.col("status").alias("_s"))
    garage = (base.select("claim_id", "garage_id", "fnol_ts")
              .join(gh, (F.col("_gid") == F.col("garage_id")) & (F.col("_f") < F.col("fnol_ts")))
              .groupBy("claim_id").agg(
                  F.sum(F.when(F.col("_d") < F.col("fnol_ts"), 1).otherwise(0)).alias("_g_decided"),
                  F.sum(F.when((F.col("_d") < F.col("fnol_ts")) & (F.col("_s") == "REJECTED"), 1).otherwise(0)).alias("_g_rej"),
                  F.sum(F.when(F.col("_f") >= F.col("fnol_ts") - F.expr("INTERVAL 30 DAYS"), 1).otherwise(0))
                  .alias("garage_claims_30d")))
    out = (base.join(hist, "claim_id", "left").join(garage, "claim_id", "left")
           .fillna({"prior_claims_12m": 0, "prior_rejected_12m": 0, "garage_claims_30d": 0, "_g_decided": 0, "_g_rej": 0}))
    return out.select(
        "claim_id", "policy_number", "golden_customer_id", "fnol_ts", "decided_ts", "business_date",
        F.col("amount_requested").cast("double").alias("amount_requested"),
        F.round(F.col("amount_requested") / F.col("_type_mean"), 4).cast("double").alias("amount_vs_type_mean"),
        F.round(F.col("amount_requested") / F.col("coverage_limit"), 4).cast("double").alias("amount_vs_idv"),
        F.col("report_delay_days").cast("double").alias("report_delay_days"),
        F.hour("incident_ts").alias("incident_hour"),
        F.greatest(F.datediff(F.to_date("fnol_ts"), F.col("customer_since")), F.lit(0)).alias("customer_tenure_days"),
        "prior_claims_12m", "prior_rejected_12m",
        F.col("policies_held").alias("customer_policies"), "credit_score", "years_licensed",
        F.col("traffic_violations_3y").alias("traffic_violations"), "other_insurer_claims_3y",
        (F.year("fnol_ts") - F.col("vehicle_year")).alias("vehicle_age_years"),
        F.col("coverage_limit").cast("double").alias("idv"), F.col("ncb_pct").cast("double").alias("ncb_pct"),
        F.round((F.col("_g_rej") + 1) / (F.col("_g_decided") + 5), 4).alias("garage_risk_score"),
        "garage_claims_30d",
        F.col("crash_event_match").cast("int").alias("crash_event_match"),
        F.col("telematics_enrolled").cast("int").alias("telematics_enrolled"),
        yn(F.col("police_report")).cast("int").alias("police_report"),
        F.coalesce(F.col("vin_mismatch"), F.lit(False)).cast("int").alias("vin_mismatch"),
        (F.coalesce(F.col("other_insurer_claims_3y"), F.lit(0)) >= 3).cast("int").alias("cross_claimant"),
        "claim_type", F.coalesce("garage_network_status", F.lit("UNKNOWN")).alias("garage_network_status"),
        credit_band(F.col("credit_score")).alias("credit_band"),
        "status", "reason_code", "decided_by",
        (F.col("status") == "APPROVED").cast("int").alias("approved"),
        F.coalesce(F.col("reason_code") == "FRAUD_CONFIRMED", F.lit(False)).cast("int").alias("fraud_confirmed"))


def scoring_context(fact: DataFrame, policy_cur: DataFrame, golden: DataFrame, vehicles: DataFrame,
                    garages: DataFrame, d) -> tuple[DataFrame, DataFrame]:
    """History features as of the end of business date d, per policy and per garage."""
    end = F.lit(f"{d.isoformat()} 23:59:59").cast("timestamp")
    by_cust = (fact.where(F.col("fnol_ts") >= end - F.expr("INTERVAL 365 DAYS"))
               .groupBy("golden_customer_id").agg(
                   F.count("*").alias("prior_claims_12m"),
                   F.sum(F.when(F.col("status") == "REJECTED", 1).otherwise(0)).alias("prior_rejected_12m")))
    enrolled = fact.select("policy_number", "telematics_enrolled").groupBy("policy_number").agg(
        F.max(F.col("telematics_enrolled").cast("int")).alias("telematics_enrolled"))
    pol = (policy_cur.select("policy_number", "customer_since", F.col("coverage_limit").cast("double").alias("idv"),
                             F.col("ncb_pct").cast("double").alias("ncb_pct"), "vehicle_year",
                             F.col("vehicle_vin").alias("policy_vin"))
           .join(vehicles.select("policy_number", "golden_customer_id").distinct(), "policy_number", "left")
           .join(golden.select("golden_customer_id", F.col("policies_held").alias("customer_policies"), "credit_score",
                               "years_licensed", F.col("traffic_violations_3y").alias("traffic_violations"),
                               "other_insurer_claims_3y"), "golden_customer_id", "left")
           .join(by_cust, "golden_customer_id", "left").join(enrolled, "policy_number", "left")
           .fillna({"prior_claims_12m": 0, "prior_rejected_12m": 0, "telematics_enrolled": 0})
           .withColumn("credit_band", credit_band(F.col("credit_score")))
           .withColumn("cross_claimant", (F.coalesce(F.col("other_insurer_claims_3y"), F.lit(0)) >= 3).cast("int"))
           .withColumn("as_of", end))
    gar = (fact.groupBy("garage_id").agg(
        F.sum(F.when(F.col("decided_ts").isNotNull(), 1).otherwise(0)).alias("_dec"),
        F.sum(F.when(F.col("status") == "REJECTED", 1).otherwise(0)).alias("_rej"),
        F.sum(F.when(F.col("fnol_ts") >= end - F.expr("INTERVAL 30 DAYS"), 1).otherwise(0)).alias("garage_claims_30d")))
    gar = (garages.select("garage_id", "garage_name", F.col("network_status").alias("garage_network_status"))
           .join(gar, "garage_id", "left").fillna({"_dec": 0, "_rej": 0, "garage_claims_30d": 0})
           .withColumn("garage_risk_score", F.round((F.col("_rej") + 1) / (F.col("_dec") + 5), 4))
           .drop("_dec", "_rej").withColumn("as_of", end))
    return pol, gar


# ---------------------------------------------------------------- the app's tables


def app_tables(policy_cur, clauses, fact, golden, d, now_iso: str) -> dict:
    lit_src = [F.lit("GOLD_PIPELINE").alias("source"), F.lit(now_iso).alias("ingested_at")]
    book = policy_cur.where(F.col("portal_enabled") == "Y")
    pm = book.select(
        "policy_number", F.col("holder_email").alias("customer_email"), F.col("holder_name").alias("customer_name"),
        "provider_name", "policy_type", F.col("premium_amount").cast("double").alias("premium_amount"), "status",
        F.col("coverage_limit").cast("double").alias("coverage_limit"), F.col("deductible").cast("double").alias("deductible"),
        F.col("co_pay_pct").cast("double").alias("co_pay_pct"), "waiting_period_days",
        F.date_format("effective_date", "yyyy-MM-dd").alias("effective_date"),
        F.date_format("expiry_date", "yyyy-MM-dd").alias("expiry_date"),
        F.col("depreciation_rate").cast("double").alias("depreciation_rate"),
        F.col("vehicle_vin").alias("covered_vehicle_vin"), F.col("vehicle_make").alias("covered_make"),
        F.col("vehicle_model").alias("covered_model"), F.col("vehicle_year").alias("covered_year"),
        F.col("ncb_pct").cast("double").alias("no_claim_bonus_pct"),
        yn(F.col("zero_dep_addon")).alias("zero_depreciation_addon"), yn(F.col("rsa_addon")).alias("roadside_assistance_addon"),
        F.when(F.col("coverage_limit") < 500000, "LOW").when(F.col("coverage_limit") < 1000000, "MEDIUM")
        .otherwise("HIGH").alias("risk_band"),
        F.round(F.col("premium_amount") / F.col("coverage_limit") * 100, 3).cast("double").alias("premium_to_coverage_pct"),
        *lit_src)
    pc = (clauses.join(book.select("policy_number"), "policy_number")
          .select("policy_number", "section_ref", "title", "content_text", *lit_src))

    gf = C.CFG["garage_flag"]
    payout = F.coalesce(F.col("amount_approved"), F.col("amount_requested")).cast("double")
    g = (fact.where(F.col("garage_name").isNotNull()).withColumn("_payout", payout).groupBy("garage_name")
         .agg(F.count("*").alias("claim_count"), F.round(F.avg("_payout"), 2).alias("avg_payout")))
    st = g.agg(F.avg("avg_payout").alias("m"), F.stddev_pop("avg_payout").alias("s"), F.avg("claim_count").alias("c")).first()
    m, s, c = st["m"] or 0.0, (st["s"] or 1.0) or 1.0, st["c"] or 1.0
    grs = (g.withColumn("payout_anomaly_score", F.round((F.col("avg_payout") - F.lit(m)) / F.lit(s), 3))
           .withColumn("flagged_high_risk", (F.col("payout_anomaly_score") > gf["zscore"])
                       | (F.col("claim_count") > F.lit(c) * gf["volume_multiple"])))
    # garages the network itself has put on watch count as high-risk too
    watch = fact.where(F.col("garage_network_status") == "WATCHLIST").select("garage_name").distinct() \
        .withColumn("_watch", F.lit(True))
    grs = (grs.join(watch, "garage_name", "left")
           .withColumn("flagged_high_risk", F.col("flagged_high_risk") | F.coalesce(F.col("_watch"), F.lit(False)))
           .drop("_watch").select("garage_name", "claim_count", "avg_payout", "payout_anomaly_score",
                                  "flagged_high_risk", *lit_src))

    rb = C.CFG["risk_bands"]
    twelve = F.lit(d.isoformat()).cast("date") - F.expr("INTERVAL 365 DAYS")
    seg = Window.partitionBy("claim_type")
    cl = (fact.withColumn("_seg", F.avg("amount_requested").over(seg))
          .withColumn("_vs", F.round((F.col("amount_requested") - F.col("_seg")) / F.col("_seg") * 100, 2))
          .join(grs.where("flagged_high_risk").select("garage_name").withColumn("_hr", F.lit(1)), "garage_name", "left"))
    pr = (cl.groupBy("policy_number").agg(
        F.count("*").alias("total_claims_count"),
        F.sum(F.when(F.to_date("incident_ts") >= twelve, 1).otherwise(0)).alias("claims_count_12m"),
        F.round(F.sum("amount_requested"), 2).cast("double").alias("total_claimed_amount"),
        F.round(F.avg("amount_requested"), 2).cast("double").alias("avg_claim_amount"),
        F.round(F.avg("_vs"), 2).cast("double").alias("amount_vs_segment_avg_pct"),
        (F.max(F.coalesce(F.col("_hr"), F.lit(0))) == 1).alias("linked_high_risk_garage"))
        .withColumn("claim_frequency_percentile", F.round(F.percent_rank().over(Window.orderBy("claims_count_12m")), 4)))
    score = F.round(0.5 * F.col("claim_frequency_percentile") * 100
                    + 0.3 * F.least(F.greatest(F.col("amount_vs_segment_avg_pct"), F.lit(0.0)), F.lit(200.0)) / 2
                    + 0.2 * F.when(F.col("linked_high_risk_garage"), 100.0).otherwise(0.0), 1)
    prs = (pr.withColumn("fraud_risk_score", score)
           .withColumn("claim_risk_band", F.when(F.col("fraud_risk_score") <= rb["low_max"], "LOW")
                       .when(F.col("fraud_risk_score") <= rb["medium_max"], "MEDIUM").otherwise("HIGH"))
           .select("policy_number", "total_claims_count", "claims_count_12m", "total_claimed_amount",
                   "avg_claim_amount", "amount_vs_segment_avg_pct", "claim_frequency_percentile",
                   "linked_high_risk_garage", "fraud_risk_score", "claim_risk_band", *lit_src))

    scored = golden.where(F.col("email").isNotNull())
    cps = (scored.withColumn("credit_score_percentile",
                             F.when(F.col("credit_score").isNotNull(),
                                    F.round(F.percent_rank().over(Window.orderBy("credit_score")), 4)))
           .select(F.col("email").alias("customer_email"), "credit_score", "credit_score_percentile",
                   credit_band(F.col("credit_score")).alias("credit_band"), "loan_defaults_12m",
                   yn(F.col("active_vehicle_loan")).alias("active_vehicle_loan"), "driver_age", "years_licensed",
                   "traffic_violations_3y", yn(F.col("dui_history")).alias("dui_history"),
                   F.when(yn(F.col("dui_history")) | (F.col("traffic_violations_3y") >= 3), "POOR")
                   .when(F.col("traffic_violations_3y") >= 1, "MINOR").otherwise("CLEAN").alias("driving_record_band"),
                   yn(F.col("address_changed_90d")).alias("address_changed_90d"),
                   F.round(F.datediff(F.lit(d.isoformat()).cast("date"), F.col("customer_since")) / 365.25, 2)
                   .alias("years_with_insurer"),
                   F.col("policies_held"), "other_insurer_claims_3y", *lit_src))
    return {"policy_master": pm, "policy_clauses": pc, "garage_risk_signals": grs,
            "policy_risk_signals": prs, "customer_profile_signals": cps}


def kpi_ref(spark, names) -> None:
    cfg = C.load_json("config/kpi.json")
    rows = [(k["kpi_code"], k["name"], k["definition"], k["formula"], k["grain"], k["certified_view"], k["owner"],
             k["version"], k["certified_on"], k["glossary_term"]) for k in cfg["kpis"]]
    C.replace_table(spark.createDataFrame(rows, "kpi_code string, name string, definition string, formula string, "
                                                "grain string, certified_view string, owner string, version string, "
                                                "certified_on string, glossary_term string"),
                    names.t("ref", "kpi_definition"))
    params = [(k, json.dumps(v)) for k, v in cfg["parameters"].items()]
    C.replace_table(spark.createDataFrame(params, "parameter string, value_json string"), names.t("ref", "kpi_parameter"))


# ---------------------------------------------------------------- run


def run(spark, argv=None) -> dict:
    from datetime import datetime, timezone

    args = C.parse(parser(), argv)
    names = C.Names(args.db_prefix)
    C.ensure_databases(spark, names)
    d = args.business_date
    C.require_completed(spark, names, "mdm", d)
    day = F.lit(d.isoformat()).cast("date")
    upto = F.col("business_date") <= day
    audit = C.Audit(spark, names, "build_gold", d, args.pipeline_run)
    audit.load(STAGE, "*", "STARTED")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out = {}

    def publish(name, df, ttype, sources, partition=False, details=""):
        target = names.t("gold", name)
        before = C.snapshot_id(spark, target)
        if partition:
            C.write_partitions(df.withColumn("business_date", day), target, ["business_date"])
        else:
            C.replace_table(df, target)
        n = spark.table(target).where(F.col("business_date") == day).count() if partition else spark.table(target).count()
        audit.load(STAGE, name, "COMMITTED", rows_out=n, snapshot_before=before, snapshot_after=C.snapshot_id(spark, target),
                   message=details)
        audit.transform(f"build {name}", ttype, sources, target, None, n, details)
        out[name] = n
        print(f"gold.{name}: {n} rows" + (f" ({details})" if details else ""), flush=True)

    try:
        silver = lambda t: spark.table(names.t("silver", t))  # noqa: E731
        mdm = lambda t: spark.table(names.t("mdm", t))  # noqa: E731
        golden_snaps = mdm("customer_golden").where(upto).withColumn("credit_band", credit_band(F.col("credit_score")))
        dim_customer = scd2(golden_snaps, "golden_customer_id", CUSTOMER_TRACKED, "customer_sk").cache()
        publish("dim_customer", dim_customer, "survive", "mdm.customer_golden", details="SCD2")
        pol_snaps = silver("policy").where(upto)
        dim_policy = scd2(pol_snaps, "policy_number", POLICY_TRACKED, "policy_sk").cache()
        publish("dim_policy", dim_policy, "survive", "silver.policy", details="SCD2")
        garages = silver("garage").where(F.col("business_date") == day).drop("business_date")
        publish("dim_garage", garages, "standardise", "silver.garage")

        claims = silver("claim").where(F.col("business_date") == day).drop("business_date")
        vehicles = mdm("vehicle_xref").where(F.col("business_date") == day).drop("business_date")
        crashes = (silver("crash_event").where(F.col("business_date") == day).drop("business_date")
                   if C.table_exists(spark, names.t("silver", "crash_event")) else None)
        fact = fact_claim(claims, vehicles, garages, crashes, dim_policy, dim_customer).cache()
        publish("fact_claim", fact, "match", "silver.claim,mdm.vehicle_xref,silver.garage,silver.crash_event,"
                                             "gold.dim_policy,gold.dim_customer", partition=True)

        policy_cur = pol_snaps.where(F.col("business_date") == day).drop("business_date")
        golden = mdm("customer_golden").where(F.col("business_date") == day).drop("business_date")
        fact_d = fact.withColumn("business_date", day)
        feats = training_features(fact_d.where(F.col("status").isin("APPROVED", "REJECTED")), policy_cur, golden)
        publish("claim_training_features", feats, "standardise", "gold.fact_claim,silver.policy,mdm.customer_golden",
                details="decided claims, point-in-time features, labels approved and fraud_confirmed")
        pctx, gctx = scoring_context(fact, policy_cur, golden, vehicles, garages, d)
        publish("scoring_context_policy", pctx, "standardise", "gold.fact_claim,silver.policy,mdm.customer_golden")
        publish("scoring_context_garage", gctx, "standardise", "gold.fact_claim,silver.garage")

        for name, df in app_tables(policy_cur, silver("policy_clause").where(F.col("business_date") == day)
                                   .drop("business_date"), fact, golden, d, now_iso).items():
            publish(name, df, "standardise", "silver.policy,gold.fact_claim,mdm.customer_golden",
                    details="Copilot app feed")
        kpi_ref(spark, names)
        fact.unpersist()
        dim_policy.unpersist()
        dim_customer.unpersist()
        audit.load(STAGE, "*", "COMPLETED", rows_out=sum(out.values()))
    except Exception as e:
        audit.load(STAGE, "*", "FAILED", message=C.error_summary(e))
        raise
    finally:
        audit.flush()
    return out


def main() -> int:
    spark = C.get_spark("mcc-build-gold")
    run(spark, sys.argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
