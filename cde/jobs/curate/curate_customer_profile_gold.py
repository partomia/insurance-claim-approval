"""Stage 4c — Curate customer profile signals (silver -> gold)
Publishes one compact row per customer with the raw profile attributes plus
population-level features only the lakehouse can compute:
  - credit_score_percentile: rank of this customer's credit score across the
    full ~800-customer population (NULL when there's no bureau hit)
  - credit_band: CIBIL-style bucket (EXCELLENT/GOOD/FAIR/POOR/NO_HIT)
  - driving_record_band: CLEAN / MINOR / POOR from violations + DUI history

The app's Customer Trust Score (backend/services/customer_trust_service.py)
is computed app-side from these columns, not here — keeps the scoring logic
and its reason codes in one explainable place, and lets non-lakehouse demo
customers (seeded directly in SQLite) be scored by the exact same code.

Writes via MERGE INTO once the table exists (same _bootstrap_or_merge
pattern as curate_gold.py / curate_risk_signals_gold.py), so every run
commits an Iceberg snapshot — `lakehouse history|as-of --table
customer_profile_signals` can show what a customer's profile looked like
when a claim was decided.

Reads:
  insurance_lakehouse_silver.customer_profile
Writes:
  insurance_lakehouse.customer_profile_signals   (per customer_email)

Usage (CDE job, no args needed):
    spark-submit curate_customer_profile_gold.py
"""

import logging
from datetime import datetime, timezone

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SILVER_DB = "insurance_lakehouse_silver"
GOLD_DB = "insurance_lakehouse"

# CIBIL-style credit buckets (lower bound inclusive).
CREDIT_EXCELLENT_MIN = 750
CREDIT_GOOD_MIN = 700
CREDIT_FAIR_MIN = 650


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-curate-customer-profile-gold").getOrCreate()


def _bootstrap_or_merge(spark: SparkSession, target: str, tmp_view: str, key_cols: list, row_count: int) -> None:
    """First run: CTAS. Every run after: MERGE INTO, so each run commits a new
    Iceberg snapshot instead of destroying history (see cde/README.md §
    Iceberg time travel). Duplicated per job file on purpose — CDE jobs are
    deployed as standalone application files with no shared module."""
    if spark.catalog.tableExists(target):
        on_clause = " AND ".join(f"t.{c} = s.{c}" for c in key_cols)
        spark.sql(f"""
            MERGE INTO {target} t
            USING {tmp_view} s
            ON {on_clause}
            WHEN MATCHED THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *
            WHEN NOT MATCHED BY SOURCE THEN DELETE
        """)
        logger.info("Merged %d source rows into %s (new snapshot committed)", row_count, target)
    else:
        spark.sql(f"""
            CREATE TABLE {target}
            USING iceberg
            TBLPROPERTIES ('format-version'='2')
            AS SELECT * FROM {tmp_view}
        """)
        logger.info("Bootstrapped %s with %d rows (first run)", target, row_count)


def compute_customer_profile_signals(profiles):
    scored = profiles.filter(F.col("credit_score").isNotNull())
    unscored = profiles.filter(F.col("credit_score").isNull())

    pct_window = Window.orderBy("credit_score")
    scored = scored.withColumn("credit_score_percentile", F.round(F.percent_rank().over(pct_window), 4))
    unscored = unscored.withColumn("credit_score_percentile", F.lit(None).cast("double"))
    signals = scored.unionByName(unscored)

    signals = signals.withColumn(
        "credit_band",
        F.when(F.col("credit_score").isNull(), "NO_HIT")
         .when(F.col("credit_score") >= CREDIT_EXCELLENT_MIN, "EXCELLENT")
         .when(F.col("credit_score") >= CREDIT_GOOD_MIN, "GOOD")
         .when(F.col("credit_score") >= CREDIT_FAIR_MIN, "FAIR")
         .otherwise("POOR"),
    ).withColumn(
        "driving_record_band",
        F.when(F.col("dui_history") | (F.col("traffic_violations_3y") >= 3), "POOR")
         .when(F.col("traffic_violations_3y") >= 1, "MINOR")
         .otherwise("CLEAN"),
    )
    return signals


def run(spark: SparkSession) -> None:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    profiles = spark.table(f"{SILVER_DB}.customer_profile").drop("source", "ingested_at")
    signals = compute_customer_profile_signals(profiles)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {GOLD_DB}")
    out = signals.withColumn("source", F.lit("GOLD_PIPELINE")).withColumn("ingested_at", F.lit(now_iso))
    out.createOrReplaceTempView("tmp_customer_profile_signals")
    _bootstrap_or_merge(
        spark, f"{GOLD_DB}.customer_profile_signals", "tmp_customer_profile_signals",
        key_cols=["customer_email"], row_count=out.count(),
    )

    logger.info("Credit band distribution:")
    out.groupBy("credit_band").count().orderBy("credit_band").show()
    logger.info("Driving record distribution:")
    out.groupBy("driving_record_band").count().orderBy("driving_record_band").show()


if __name__ == "__main__":
    spark = get_spark()
    try:
        run(spark)
    finally:
        spark.stop()
