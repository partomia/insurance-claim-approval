"""Stage 2c/3c — Validate + transform customer profiles (bronze -> silver)
Folds the validate and transform stages into one job for this smaller,
single-table feed: logs data-quality counts, fails hard only if nothing
usable survives, then cleans/conforms and dedupes by customer_email.

Rules:
  - customer_email required, lower-cased/trimmed (the join key to the app's
    Customer.email and to policy_master.customer_email).
  - credit_score clamped to the bureau's 300-900 range; NULL stays NULL
    ("no bureau hit" is a real, distinct state — the app treats it as
    neutral, never as a bad score).
  - Counts (defaults, violations, claims, policies) floored at 0.
  - years_licensed can't exceed driver_age - 18.
  - Dedupe: most recently ingested row per customer_email.

Reads:
  insurance_lakehouse_bronze.customer_profile_raw
Writes:
  insurance_lakehouse_silver.customer_profile

Usage (CDE job, no args needed):
    spark-submit transform_customer_profile_silver.py
"""

import logging
import sys

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRONZE_DB = "insurance_lakehouse_bronze"
SILVER_DB = "insurance_lakehouse_silver"


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-transform-customer-profile-silver").getOrCreate()


def log_quality(df) -> int:
    total = df.count()
    missing_email = df.filter("customer_email IS NULL OR trim(customer_email) = ''").count()
    out_of_range_credit = df.filter("credit_score IS NOT NULL AND (credit_score < 300 OR credit_score > 900)").count()
    null_credit = df.filter("credit_score IS NULL").count()
    logger.info(
        "Bronze quality: %d rows, %d missing email (dropped), %d credit out of range (clamped), %d no bureau hit",
        total, missing_email, out_of_range_credit, null_credit,
    )
    return total - missing_email


def clean_profiles(df):
    df = df.filter("customer_email IS NOT NULL AND trim(customer_email) != ''")
    df = df.withColumn("customer_email", F.lower(F.trim("customer_email")))
    df = df.withColumn(
        "credit_score",
        F.when(F.col("credit_score").isNull(), F.lit(None).cast("int"))
         .otherwise(F.least(F.greatest(F.col("credit_score"), F.lit(300)), F.lit(900))),
    )
    for col in ("loan_defaults_12m", "traffic_violations_3y", "other_insurer_claims_3y", "policies_held", "years_licensed"):
        df = df.withColumn(col, F.greatest(F.coalesce(F.col(col), F.lit(0)), F.lit(0)))
    df = df.withColumn("policies_held", F.greatest(F.col("policies_held"), F.lit(1)))
    df = df.withColumn(
        "years_licensed",
        F.when(F.col("driver_age").isNotNull(), F.least(F.col("years_licensed"), F.greatest(F.col("driver_age") - 18, F.lit(0))))
         .otherwise(F.col("years_licensed")),
    )
    df = df.withColumn("years_with_insurer", F.greatest(F.coalesce(F.col("years_with_insurer"), F.lit(0.0)), F.lit(0.0)))
    for col in ("active_vehicle_loan", "dui_history", "address_changed_90d"):
        df = df.withColumn(col, F.coalesce(F.col(col), F.lit(False)))

    w = Window.partitionBy("customer_email").orderBy(F.col("ingested_at").desc())
    return df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")


def run(spark: SparkSession) -> None:
    raw = spark.table(f"{BRONZE_DB}.customer_profile_raw")
    usable = log_quality(raw)
    if usable == 0:
        logger.error("No usable customer profile rows in bronze — failing the job")
        sys.exit(1)

    silver = clean_profiles(raw)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {SILVER_DB}")
    silver.createOrReplaceTempView("tmp_customer_profile_silver")
    spark.sql(f"DROP TABLE IF EXISTS {SILVER_DB}.customer_profile")
    spark.sql(f"""
        CREATE TABLE {SILVER_DB}.customer_profile
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_customer_profile_silver
    """)
    logger.info("Wrote %d rows to %s.customer_profile", silver.count(), SILVER_DB)


if __name__ == "__main__":
    spark = get_spark()
    try:
        run(spark)
    finally:
        spark.stop()
