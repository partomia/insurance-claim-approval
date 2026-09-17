"""
Stage 1 — Generate (bronze)
Synthesizes a larger, more realistic motor-policy dataset than Phase 1's
hand-seeded 3 rows, and lands it raw/untransformed in the bronze layer.

This stands in for a real source system extract (policy admin system, claims
warehouse, etc.) — in production this job would read from S3/Kafka/JDBC
instead of generating data in-process. Bronze is intentionally raw: no
cleaning, no dedup, no validation — that happens in later stages.

Writes:
  insurance_lakehouse_bronze.policy_master_raw
  insurance_lakehouse_bronze.policy_clauses_raw

Usage (CDE job, no args needed — all defaults are baked in):
    spark-submit generate_bronze.py [n_policies]
"""

import logging
import random
import sys
from datetime import datetime, timedelta, timezone

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRONZE_DB = "insurance_lakehouse_bronze"
DEFAULT_N_POLICIES = 60

PROVIDERS = [
    "Bajaj Allianz Motor", "ICICI Lombard Motor", "HDFC ERGO Motor",
    "Acko Drive", "Tata AIG Motor", "Reliance General Motor",
]
STATUSES = ["ACTIVE", "ACTIVE", "ACTIVE", "EXPIRED", "LAPSED", "CANCELLED"]  # weighted toward ACTIVE
VEHICLES = [
    ("Maruti Suzuki", "Baleno"), ("Hyundai", "Creta"), ("Tata", "Nexon"),
    ("Honda", "City"), ("Mahindra", "XUV700"), ("Kia", "Seltos"),
    ("Toyota", "Innova"), ("Volkswagen", "Taigun"),
]
FIRST_NAMES = ["Ananya", "Vikram", "Priya", "Arjun", "Kavya", "Rohan", "Neha", "Karthik", "Divya", "Sanjay"]
LAST_NAMES = ["Rao", "Shah", "Menon", "Iyer", "Nair", "Gupta", "Reddy", "Kapoor", "Joshi", "Singh"]

POLICY_MASTER_SCHEMA = StructType([
    StructField("policy_number", StringType(), False),
    StructField("customer_name", StringType(), True),
    StructField("customer_email", StringType(), True),
    StructField("provider_name", StringType(), True),
    StructField("policy_type", StringType(), True),
    StructField("premium_amount", DoubleType(), True),
    StructField("status", StringType(), True),
    StructField("coverage_limit", DoubleType(), True),
    StructField("deductible", DoubleType(), True),
    StructField("co_pay_pct", DoubleType(), True),
    StructField("waiting_period_days", IntegerType(), True),
    StructField("effective_date", StringType(), True),
    StructField("expiry_date", StringType(), True),
    StructField("depreciation_rate", DoubleType(), True),
    StructField("covered_vehicle_vin", StringType(), True),
    StructField("covered_make", StringType(), True),
    StructField("covered_model", StringType(), True),
    StructField("covered_year", IntegerType(), True),
    StructField("no_claim_bonus_pct", DoubleType(), True),
    StructField("zero_depreciation_addon", BooleanType(), True),
    StructField("roadside_assistance_addon", BooleanType(), True),
    StructField("source", StringType(), True),
    StructField("ingested_at", StringType(), True),
])

POLICY_CLAUSES_SCHEMA = StructType([
    StructField("policy_number", StringType(), False),
    StructField("title", StringType(), True),
    StructField("section_ref", StringType(), True),
    StructField("content_text", StringType(), True),
    StructField("source", StringType(), True),
    StructField("ingested_at", StringType(), True),
])

CLAUSE_TEMPLATE = [
    ("Policy Schedule", "Section 1.0",
     "This Motor Comprehensive Policy provides own-damage and third-party "
     "liability coverage for the insured private vehicle for a period of "
     "12 months from the effective date. Insured Declared Value (IDV) is "
     "the maximum settlement amount for total loss."),
    ("Coverage Details", "Section 4.2",
     "Own-damage coverage includes collision, theft, fire, vandalism, "
     "natural disasters, and glass breakage. Third-party liability covers "
     "bodily injury and property damage to third parties as required by law."),
    ("Exclusions", "Section 7.1",
     "Exclusions: driving under influence of alcohol or drugs, driving "
     "without a valid licence, racing or speed testing, commercial use "
     "without endorsement, consequential loss, mechanical/electrical "
     "breakdown, wear and tear, and damage caused by war or nuclear risks."),
    ("Claim Settlement", "Section 3.5",
     "Deductible applies per own-damage claim. Depreciation applied per "
     "the schedule unless the zero-depreciation add-on is active. Claims "
     "must be intimated within 48 hours of the incident."),
]


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-generate-bronze").getOrCreate()


def generate_policy_rows(n: int, now_iso: str, seed: int = 42):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        make, model = rng.choice(VEHICLES)
        effective = datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 640))
        rows.append((
            f"LH-POL-{2000 + i}",
            f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            f"customer{i}@example.com",
            rng.choice(PROVIDERS),
            "Motor",
            round(rng.uniform(8000, 35000), 2),
            rng.choice(STATUSES),
            round(rng.uniform(300000, 1500000), 2),
            round(rng.choice([500.0, 750.0, 1000.0]), 2),
            round(rng.uniform(0, 15), 1),
            0,
            effective.strftime("%Y-%m-%d"),
            (effective + timedelta(days=365)).strftime("%Y-%m-%d"),
            round(rng.uniform(5, 25), 1),
            f"MA{rng.randint(1000000000000, 9999999999999)}",
            make,
            model,
            rng.randint(2018, 2024),
            round(rng.uniform(0, 50), 1),
            rng.choice([True, False]),
            rng.choice([True, False]),
            "BRONZE_GENERATED",
            now_iso,
        ))
    return rows


def generate_clause_rows(policy_numbers, now_iso: str):
    rows = []
    for policy_number in policy_numbers:
        for title, section_ref, content_text in CLAUSE_TEMPLATE:
            rows.append((policy_number, title, section_ref, content_text, "BRONZE_GENERATED", now_iso))
    return rows


def write_bronze(spark: SparkSession, n_policies: int) -> None:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    policy_rows = generate_policy_rows(n_policies, now_iso)
    policy_df = spark.createDataFrame(policy_rows, schema=POLICY_MASTER_SCHEMA)

    clause_rows = generate_clause_rows([r[0] for r in policy_rows], now_iso)
    clause_df = spark.createDataFrame(clause_rows, schema=POLICY_CLAUSES_SCHEMA)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {BRONZE_DB}")

    policy_df.createOrReplaceTempView("tmp_policy_master_raw")
    spark.sql(f"DROP TABLE IF EXISTS {BRONZE_DB}.policy_master_raw")
    spark.sql(f"""
        CREATE TABLE {BRONZE_DB}.policy_master_raw
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_policy_master_raw
    """)
    logger.info("Wrote %d rows to %s.policy_master_raw", policy_df.count(), BRONZE_DB)

    clause_df.createOrReplaceTempView("tmp_policy_clauses_raw")
    spark.sql(f"DROP TABLE IF EXISTS {BRONZE_DB}.policy_clauses_raw")
    spark.sql(f"""
        CREATE TABLE {BRONZE_DB}.policy_clauses_raw
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_policy_clauses_raw
    """)
    logger.info("Wrote %d rows to %s.policy_clauses_raw", clause_df.count(), BRONZE_DB)


def _is_unset(val: str) -> bool:
    """True if arg is missing or an unsubstituted CDE template like {{n_policies}}."""
    return not val or (val.startswith("{{") and val.endswith("}}"))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    n_policies = int(arg) if arg and not _is_unset(arg) else DEFAULT_N_POLICIES

    spark = get_spark()
    try:
        logger.info("Generating %d synthetic policies into bronze...", n_policies)
        write_bronze(spark, n_policies)
    finally:
        spark.stop()
