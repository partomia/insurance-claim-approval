"""Stage 3b — Transform claims (bronze -> silver)
Cleans and conforms the raw claims bronze data: drops invalid rows (defense
in depth after validate), trims/standardizes strings, and dedupes by
claim_id (keeping the most recently ingested row per key). Same pattern as
transform_silver.py.

Reads:
  insurance_lakehouse_bronze.claims_history_raw
Writes:
  insurance_lakehouse_silver.claims_history

Usage (CDE job, no args needed):
    spark-submit transform_claims_silver.py
"""

import logging

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRONZE_DB = "insurance_lakehouse_bronze"
SILVER_DB = "insurance_lakehouse_silver"


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-transform-claims-silver").getOrCreate()


def clean_claims(df):
    df = df.filter("claim_id IS NOT NULL AND claim_id != ''")
    df = df.filter("policy_number IS NOT NULL AND policy_number != ''")
    df = df.filter("amount_requested IS NOT NULL AND amount_requested > 0")
    df = df.withColumn("policy_number", F.trim("policy_number"))
    df = df.withColumn("claim_type", F.trim("claim_type"))
    df = df.withColumn("status", F.upper(F.trim("status")))
    df = df.withColumn("garage_name", F.trim("garage_name"))

    # Dedupe: keep the most recently ingested row per claim_id.
    w = Window.partitionBy("claim_id").orderBy(F.col("ingested_at").desc())
    df = df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")
    return df


def run(spark: SparkSession) -> None:
    claims_raw = spark.table(f"{BRONZE_DB}.claims_history_raw")
    claims_silver = clean_claims(claims_raw)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {SILVER_DB}")

    claims_silver.createOrReplaceTempView("tmp_claims_history_silver")
    spark.sql(f"DROP TABLE IF EXISTS {SILVER_DB}.claims_history")
    spark.sql(f"""
        CREATE TABLE {SILVER_DB}.claims_history
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_claims_history_silver
    """)
    logger.info("Wrote %d rows to %s.claims_history", claims_silver.count(), SILVER_DB)


if __name__ == "__main__":
    spark = get_spark()
    try:
        run(spark)
    finally:
        spark.stop()
