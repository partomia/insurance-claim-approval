"""Stage 1c — Generate customer profile / bureau data (bronze)
Synthesizes the customer-side attributes a real insurer would pull from
external sources — a credit bureau (CIBIL-style 300-900 score, recent loan
defaults), the transport authority (VAHAN/Parivahan-style licence age and
traffic violations), and the industry claims bureau (IIB-style claim count at
*other* insurers) — plus internal relationship data (tenure, policies held).
In production this job would read those feeds (S3 drops / partner APIs); here
it generates them in-process, same as generate_bronze.py.

Population: CUSTOMER_UNIVERSE_SIZE customers, customer0..customer799@example.com
— the same email scheme generate_bronze.py uses for policy_master
(customer{i}@example.com for LH-POL-{2000+i}), so the first ~60 rows line up
with the app's lakehouse-ingested customers, and the rest give the gold-layer
percentiles a statistically meaningful population (same reasoning as
generate_claims_bronze.py's 800-policy claims universe).

Seeded outliers (so the downstream trust score has something to find):
  - ~7% "financially stressed" (credit < 600 and 1-3 loan defaults in 12m)
  - ~4% cross-insurer serial claimants (3-6 claims at other insurers in 3y)
  - ~3% recent address change on a new customer relationship

Deliberately NOT generated: gender, religion, caste, or any protected
attribute. driver_age is generated for reference/analytics but the app's
trust score intentionally does not use it (driving experience is captured by
years_licensed instead) — see backend/services/customer_trust_service.py.

Writes:
  insurance_lakehouse_bronze.customer_profile_raw

Usage (CDE job, no args needed — all defaults are baked in):
    spark-submit generate_customer_profile_bronze.py [n_customers] [seed|YYYY-MM-DD]
"""

import logging
import random
import sys
from datetime import datetime, timezone

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
CUSTOMER_UNIVERSE_SIZE = 800
FINANCIAL_STRESS_PCT = 0.07
CROSS_INSURER_CLAIMANT_PCT = 0.04
RECENT_ADDRESS_CHANGE_PCT = 0.03

CUSTOMER_PROFILE_SCHEMA = StructType([
    StructField("customer_email", StringType(), False),
    StructField("credit_score", IntegerType(), True),
    StructField("loan_defaults_12m", IntegerType(), True),
    StructField("active_vehicle_loan", BooleanType(), True),
    StructField("driver_age", IntegerType(), True),
    StructField("years_licensed", IntegerType(), True),
    StructField("traffic_violations_3y", IntegerType(), True),
    StructField("dui_history", BooleanType(), True),
    StructField("address_changed_90d", BooleanType(), True),
    StructField("years_with_insurer", DoubleType(), True),
    StructField("policies_held", IntegerType(), True),
    StructField("other_insurer_claims_3y", IntegerType(), True),
    StructField("source", StringType(), True),
    StructField("ingested_at", StringType(), True),
])


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-generate-customer-profile-bronze").getOrCreate()


def generate_customer_rows(n: int, now_iso: str, anchor: datetime, seed: int = None):
    # Seeded by calendar day, same convention as generate_bronze.py — re-runs
    # within a day are idempotent, a day boundary (or explicit seed) evolves
    # the population so gold MERGE INTO commits a real Iceberg snapshot diff.
    if seed is None:
        seed = int(anchor.strftime("%Y%m%d"))
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        # One latent "carefulness" draw per customer drives correlated
        # attributes (credit, violations, tenure) so the data isn't pure noise.
        care = rng.betavariate(5, 2)
        is_stressed = rng.random() < FINANCIAL_STRESS_PCT
        is_cross_claimant = rng.random() < CROSS_INSURER_CLAIMANT_PCT
        is_address_churn = rng.random() < RECENT_ADDRESS_CHANGE_PCT

        if is_stressed:
            credit = rng.randint(420, 599)
            defaults = rng.randint(1, 3)
        else:
            credit = int(max(300, min(900, rng.gauss(530 + care * 300, 45))))
            defaults = 1 if rng.random() < 0.03 else 0

        driver_age = rng.randint(21, 68)
        years_licensed = max(0, min(driver_age - 18, int(rng.gauss(care * 18, 4))))
        violations = rng.choices([0, 1, 2, 3, 4], weights=[60 * care, 20, 10, 6, 4], k=1)[0]
        dui = rng.random() < (0.06 if care < 0.45 else 0.01)

        years_with_insurer = round(0.2 if is_address_churn else rng.uniform(0.3, 1 + care * 11), 1)
        policies_held = rng.choices([1, 2, 3], weights=[70, 22, 8], k=1)[0]
        other_claims = rng.randint(3, 6) if is_cross_claimant else rng.choices([0, 1, 2], weights=[75, 20, 5], k=1)[0]

        rows.append((
            f"customer{i}@example.com",
            credit,
            defaults,
            rng.random() < 0.45,
            driver_age,
            years_licensed,
            violations,
            dui,
            is_address_churn or rng.random() < 0.02,
            years_with_insurer,
            policies_held,
            other_claims,
            "BRONZE_GENERATED",
            now_iso,
        ))
    return rows


def write_bronze(spark: SparkSession, n_customers: int, seed: int = None) -> None:
    anchor = datetime.now(timezone.utc).replace(tzinfo=None)
    now_iso = anchor.strftime("%Y-%m-%d %H:%M:%S")

    rows = generate_customer_rows(n_customers, now_iso, anchor, seed=seed)
    df = spark.createDataFrame(rows, schema=CUSTOMER_PROFILE_SCHEMA)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {BRONZE_DB}")
    df.createOrReplaceTempView("tmp_customer_profile_raw")
    spark.sql(f"DROP TABLE IF EXISTS {BRONZE_DB}.customer_profile_raw")
    spark.sql(f"""
        CREATE TABLE {BRONZE_DB}.customer_profile_raw
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_customer_profile_raw
    """)
    logger.info("Wrote %d rows to %s.customer_profile_raw", df.count(), BRONZE_DB)


def _is_unset(val: str) -> bool:
    """True if arg is missing or an unsubstituted CDE template like {{n_customers}}."""
    return not val or (val.startswith("{{") and val.endswith("}}"))


def _parse_seed_arg(val: str) -> int:
    """Raw int seed, or a YYYY-MM-DD date string (same formula as the default
    calendar-day seed) — lets cde/scripts/time_travel_drill.sh simulate an
    earlier day's population on demand."""
    if len(val) == 10 and val[4] == "-" and val[7] == "-":
        return int(datetime.strptime(val, "%Y-%m-%d").strftime("%Y%m%d"))
    return int(val)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    n_customers = int(arg) if arg and not _is_unset(arg) else CUSTOMER_UNIVERSE_SIZE

    seed_arg = sys.argv[2] if len(sys.argv) > 2 else None
    seed = _parse_seed_arg(seed_arg) if seed_arg and not _is_unset(seed_arg) else None

    spark = get_spark()
    try:
        logger.info("Generating %d synthetic customer profiles into bronze...", n_customers)
        write_bronze(spark, n_customers, seed=seed)
    finally:
        spark.stop()
