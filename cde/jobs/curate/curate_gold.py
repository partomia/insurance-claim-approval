"""
Stage 4 — Curate (silver -> gold)
Final business-ready layer: adds a couple of simple derived/curated columns
and writes to the SAME tables Phase 1 hand-seeded via Impala
(insurance_lakehouse.policy_master / policy_clauses) — this pipeline now
becomes the real source of that data going forward. Downstream consumers
(Hue/Impala queries, a future app-side ingestion job) don't need to change:
same database, same table names, same core columns, just pipeline-produced
instead of hand-seeded, and with two additive enrichment columns.

Reads:
  insurance_lakehouse_silver.policy_master
  insurance_lakehouse_silver.policy_clauses
Writes:
  insurance_lakehouse.policy_master   (adds: risk_band, premium_to_coverage_pct)
  insurance_lakehouse.policy_clauses

Usage (CDE job, no args needed):
    spark-submit curate_gold.py
"""

import logging
from datetime import datetime, timezone

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SILVER_DB = "insurance_lakehouse_silver"
GOLD_DB = "insurance_lakehouse"  # same schema Phase 1 (lakehouse_seed.py) used


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-curate-gold").getOrCreate()


def curate_policies(df, now_iso: str):
    df = df.withColumn(
        "risk_band",
        F.when(F.col("coverage_limit") < 500000, "LOW")
         .when(F.col("coverage_limit") < 1000000, "MEDIUM")
         .otherwise("HIGH"),
    )
    df = df.withColumn(
        "premium_to_coverage_pct",
        F.round(F.col("premium_amount") / F.col("coverage_limit") * 100, 3),
    )
    df = df.withColumn("source", F.lit("GOLD_PIPELINE"))
    df = df.withColumn("ingested_at", F.lit(now_iso))
    return df


def curate_clauses(df, now_iso: str):
    return df.withColumn("source", F.lit("GOLD_PIPELINE")).withColumn("ingested_at", F.lit(now_iso))


def run(spark: SparkSession) -> None:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    policies_silver = spark.table(f"{SILVER_DB}.policy_master")
    clauses_silver = spark.table(f"{SILVER_DB}.policy_clauses")

    policies_gold = curate_policies(policies_silver, now_iso)
    clauses_gold = curate_clauses(clauses_silver, now_iso)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {GOLD_DB}")

    policies_gold.createOrReplaceTempView("tmp_policy_master_gold")
    spark.sql(f"DROP TABLE IF EXISTS {GOLD_DB}.policy_master")
    spark.sql(f"""
        CREATE TABLE {GOLD_DB}.policy_master
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_policy_master_gold
    """)
    logger.info("Wrote %d rows to %s.policy_master", policies_gold.count(), GOLD_DB)

    clauses_gold.createOrReplaceTempView("tmp_policy_clauses_gold")
    spark.sql(f"DROP TABLE IF EXISTS {GOLD_DB}.policy_clauses")
    spark.sql(f"""
        CREATE TABLE {GOLD_DB}.policy_clauses
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_policy_clauses_gold
    """)
    logger.info("Wrote %d rows to %s.policy_clauses", clauses_gold.count(), GOLD_DB)

    logger.info("Gold curation complete. Risk band distribution:")
    policies_gold.groupBy("risk_band").count().show()


if __name__ == "__main__":
    spark = get_spark()
    try:
        run(spark)
    finally:
        spark.stop()
