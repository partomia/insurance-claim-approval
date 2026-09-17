"""Stage 4b — Curate risk signals (silver -> gold)
This is the actual "datalakehouse speciality" step: computing analytics over
the *entire* claims history population that a single OLTP row/query could
never produce on its own -- percentile ranks, peer-group (claim-type)
benchmarks, and garage-level anomaly detection -- then publishing compact,
per-key result tables.

Design notes:
  - Percentiles/benchmarks are computed over the FULL historical claims
    population (~800 policies, see generate_claims_bronze.py), not just
    policy_master's ~60 "currently active" rows -- larger population gives
    statistically meaningful percentiles. policy_risk_signals therefore
    covers more policy_numbers than policy_master/policy_clauses.
  - This step deliberately does NOT sync anything back to the app's SQLite
    OLTP database yet. That's a separate, later step once this analytics
    layer is validated (see cde/README.md roadmap) -- restricting/filtering
    to just the policies the live app cares about belongs there, not here.
  - Tables are dropped/recreated each run (like the rest of this pipeline);
    a production version would use incremental Iceberg MERGE instead.

Reads:
  insurance_lakehouse_silver.claims_history
Writes:
  insurance_lakehouse.policy_risk_signals   (per policy_number)
  insurance_lakehouse.garage_risk_signals   (per garage_name)

Usage (CDE job, no args needed):
    spark-submit curate_risk_signals_gold.py
"""

import logging
from datetime import datetime, timedelta, timezone

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SILVER_DB = "insurance_lakehouse_silver"
GOLD_DB = "insurance_lakehouse"

# Fixed thresholds for the fraud_risk_score -> claim_risk_band bucketing.
# Simple and explainable for a demo; a production model would likely use a
# calibrated/learned threshold instead.
BAND_LOW_MAX = 33.0
BAND_MEDIUM_MAX = 66.0

# Garage flagged high-risk if its payout anomaly z-score exceeds this, OR its
# claim volume is this many times the average garage's claim volume.
GARAGE_ZSCORE_THRESHOLD = 1.5
GARAGE_VOLUME_MULTIPLE_THRESHOLD = 2.5


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-curate-risk-signals-gold").getOrCreate()


def compute_garage_risk_signals(claims):
    """Per-garage aggregates + a z-score-based payout anomaly flag."""
    payout_col = F.coalesce(F.col("amount_approved"), F.col("amount_requested"))
    garage_agg = (
        claims.withColumn("_payout", payout_col)
        .groupBy("garage_name")
        .agg(
            F.count("*").alias("claim_count"),
            F.round(F.avg("_payout"), 2).alias("avg_payout"),
        )
    )

    stats = garage_agg.select(
        F.avg("avg_payout").alias("mean_payout"),
        F.stddev_pop("avg_payout").alias("std_payout"),
        F.avg("claim_count").alias("mean_claim_count"),
    ).first()
    mean_payout = stats["mean_payout"] or 0.0
    std_payout = stats["std_payout"] or 1.0
    mean_claim_count = stats["mean_claim_count"] or 1.0
    if std_payout == 0:
        std_payout = 1.0

    garage_signals = garage_agg.withColumn(
        "payout_anomaly_score",
        F.round((F.col("avg_payout") - F.lit(mean_payout)) / F.lit(std_payout), 3),
    ).withColumn(
        "flagged_high_risk",
        (F.col("payout_anomaly_score") > GARAGE_ZSCORE_THRESHOLD)
        | (F.col("claim_count") > F.lit(mean_claim_count) * GARAGE_VOLUME_MULTIPLE_THRESHOLD),
    )
    return garage_signals


def compute_policy_risk_signals(claims, garage_signals, now: datetime):
    twelve_months_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")

    # Peer benchmark: this claim's amount vs. the average for its claim_type,
    # computed over the *entire* population (window, not a groupBy+join, so
    # every row keeps its per-claim deviation for later per-policy averaging).
    segment_avg_window = Window.partitionBy("claim_type")
    claims_with_segment = claims.withColumn(
        "segment_avg_amount", F.avg("amount_requested").over(segment_avg_window)
    ).withColumn(
        "amount_vs_segment_avg_pct",
        F.round((F.col("amount_requested") - F.col("segment_avg_amount")) / F.col("segment_avg_amount") * 100, 2),
    )

    high_risk_garages = [r.garage_name for r in garage_signals.filter("flagged_high_risk = true").collect()]
    claims_with_segment = claims_with_segment.withColumn(
        "_is_high_risk_garage_claim", F.col("garage_name").isin(high_risk_garages)
    )

    policy_agg = claims_with_segment.groupBy("policy_number").agg(
        F.count("*").alias("total_claims_count"),
        F.sum(F.when(F.col("incident_date") >= twelve_months_ago, 1).otherwise(0)).alias("claims_count_12m"),
        F.round(F.sum("amount_requested"), 2).alias("total_claimed_amount"),
        F.round(F.avg("amount_requested"), 2).alias("avg_claim_amount"),
        F.round(F.avg("amount_vs_segment_avg_pct"), 2).alias("amount_vs_segment_avg_pct"),
        F.max(F.col("_is_high_risk_garage_claim").cast("int")).alias("_linked_high_risk_garage_int"),
    ).withColumn("linked_high_risk_garage", F.col("_linked_high_risk_garage_int") == 1).drop("_linked_high_risk_garage_int")

    # Percentile rank of claim frequency (0-1) across the full population.
    freq_window = Window.orderBy("claims_count_12m")
    policy_agg = policy_agg.withColumn(
        "claim_frequency_percentile", F.round(F.percent_rank().over(freq_window), 4)
    )

    # Composite fraud_risk_score (0-100): 50% frequency percentile, 30%
    # amount-vs-peer deviation (capped at 200%, scaled to 0-100), 20% garage flag.
    freq_component = F.col("claim_frequency_percentile") * 100
    amount_component = F.least(F.greatest(F.col("amount_vs_segment_avg_pct"), F.lit(0.0)), F.lit(200.0)) / F.lit(2.0)
    garage_component = F.when(F.col("linked_high_risk_garage"), F.lit(100.0)).otherwise(F.lit(0.0))

    policy_signals = policy_agg.withColumn(
        "fraud_risk_score",
        F.round(F.lit(0.5) * freq_component + F.lit(0.3) * amount_component + F.lit(0.2) * garage_component, 1),
    ).withColumn(
        "claim_risk_band",
        F.when(F.col("fraud_risk_score") <= BAND_LOW_MAX, "LOW")
         .when(F.col("fraud_risk_score") <= BAND_MEDIUM_MAX, "MEDIUM")
         .otherwise("HIGH"),
    )
    return policy_signals


def run(spark: SparkSession) -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%d %H:%M:%S")

    claims = spark.table(f"{SILVER_DB}.claims_history")

    garage_signals = compute_garage_risk_signals(claims)
    policy_signals = compute_policy_risk_signals(claims, garage_signals, now)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {GOLD_DB}")

    garage_out = garage_signals.withColumn("source", F.lit("GOLD_PIPELINE")).withColumn("ingested_at", F.lit(now_iso))
    garage_out.createOrReplaceTempView("tmp_garage_risk_signals")
    spark.sql(f"DROP TABLE IF EXISTS {GOLD_DB}.garage_risk_signals")
    spark.sql(f"""
        CREATE TABLE {GOLD_DB}.garage_risk_signals
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_garage_risk_signals
    """)
    logger.info("Wrote %d rows to %s.garage_risk_signals", garage_out.count(), GOLD_DB)

    policy_out = policy_signals.withColumn("source", F.lit("GOLD_PIPELINE")).withColumn("ingested_at", F.lit(now_iso))
    policy_out.createOrReplaceTempView("tmp_policy_risk_signals")
    spark.sql(f"DROP TABLE IF EXISTS {GOLD_DB}.policy_risk_signals")
    spark.sql(f"""
        CREATE TABLE {GOLD_DB}.policy_risk_signals
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_policy_risk_signals
    """)
    logger.info("Wrote %d rows to %s.policy_risk_signals", policy_out.count(), GOLD_DB)

    logger.info("Risk band distribution:")
    policy_out.groupBy("claim_risk_band").count().orderBy("claim_risk_band").show()
    logger.info("High-risk garages flagged: %d", garage_out.filter("flagged_high_risk = true").count())


if __name__ == "__main__":
    spark = get_spark()
    try:
        run(spark)
    finally:
        spark.stop()
