"""
Stage 3 — Transform (bronze -> silver)
Cleans and conforms the raw bronze data: drops invalid rows (defense in
depth after the validate stage), trims/standardises strings, casts types
explicitly, and dedupes by policy_number (keeping the most recently
ingested row per key).

Reads:
  insurance_lakehouse_bronze.policy_master_raw
  insurance_lakehouse_bronze.policy_clauses_raw
Writes:
  insurance_lakehouse_silver.policy_master
  insurance_lakehouse_silver.policy_clauses

Usage (CDE job, no args needed):
    spark-submit transform_silver.py
"""

import logging

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRONZE_DB = "insurance_lakehouse_bronze"
SILVER_DB = "insurance_lakehouse_silver"


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-transform-silver").getOrCreate()


def clean_policies(df):
    df = df.filter("policy_number IS NOT NULL AND policy_number != ''")
    df = df.withColumn("customer_name", F.trim("customer_name"))
    df = df.withColumn("customer_email", F.lower(F.trim("customer_email")))
    df = df.withColumn("provider_name", F.trim("provider_name"))
    df = df.withColumn("status", F.upper(F.trim("status")))
    df = df.withColumn("covered_make", F.trim("covered_make"))
    df = df.withColumn("covered_model", F.trim("covered_model"))

    # Dedupe: keep the most recently ingested row per policy_number.
    w = Window.partitionBy("policy_number").orderBy(F.col("ingested_at").desc())
    df = df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")
    return df


def clean_clauses(df, valid_policy_numbers):
    df = df.filter("policy_number IS NOT NULL AND content_text IS NOT NULL AND content_text != ''")
    df = df.withColumn("title", F.trim("title"))
    df = df.withColumn("section_ref", F.trim("section_ref"))
    df = df.withColumn("content_text", F.trim("content_text"))
    # Drop clauses whose policy didn't survive cleaning (orphans).
    df = df.join(valid_policy_numbers, on="policy_number", how="inner")
    # Dedupe exact duplicate (policy_number, section_ref) pairs.
    w = Window.partitionBy("policy_number", "section_ref").orderBy(F.col("ingested_at").desc())
    df = df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")
    return df


def run(spark: SparkSession) -> None:
    policies_raw = spark.table(f"{BRONZE_DB}.policy_master_raw")
    clauses_raw = spark.table(f"{BRONZE_DB}.policy_clauses_raw")

    policies_silver = clean_policies(policies_raw)
    valid_policy_numbers = policies_silver.select("policy_number").distinct()
    clauses_silver = clean_clauses(clauses_raw, valid_policy_numbers)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {SILVER_DB}")

    policies_silver.createOrReplaceTempView("tmp_policy_master_silver")
    spark.sql(f"DROP TABLE IF EXISTS {SILVER_DB}.policy_master")
    spark.sql(f"""
        CREATE TABLE {SILVER_DB}.policy_master
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_policy_master_silver
    """)
    logger.info("Wrote %d rows to %s.policy_master", policies_silver.count(), SILVER_DB)

    clauses_silver.createOrReplaceTempView("tmp_policy_clauses_silver")
    spark.sql(f"DROP TABLE IF EXISTS {SILVER_DB}.policy_clauses")
    spark.sql(f"""
        CREATE TABLE {SILVER_DB}.policy_clauses
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_policy_clauses_silver
    """)
    logger.info("Wrote %d rows to %s.policy_clauses", clauses_silver.count(), SILVER_DB)


if __name__ == "__main__":
    spark = get_spark()
    try:
        run(spark)
    finally:
        spark.stop()
