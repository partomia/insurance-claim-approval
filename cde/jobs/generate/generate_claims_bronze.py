"""Stage 1b — Generate claims history (bronze)
Synthesizes a much larger, realistic *claims history* dataset than the ~60
active policies in policy_master — this is the volume the risk/fraud
analytics in curate_risk_signals_gold.py actually need. Without enough
population to compute percentiles/peer-averages over, those analytics are
meaningless; that's the whole reason this is a separate, bigger dataset.

Deliberately NOT 1:1 with policy_master's current ~60 "active" policies: it
uses a broader historical policy-number universe (LH-POL-2000..2799, 800
distinct policies) that happens to overlap with policy_master's default
60 rows (LH-POL-2000..2059, same numbering scheme as generate_bronze.py) as
a coincidental subset — exactly like a real claims warehouse holds history
for policies that have since lapsed/expired/renewed, not just the current
book. validate_claims_bronze.py treats full inclusion as informational, not
a hard failure, for this reason.

Seeded outliers (so the downstream analytics have something to find):
  - ~8% of policies are "frequent claimants" (4-8 claims each)
  - ~5% of individual claims have amount_requested inflated 2.5x-4x their
    claim-type peer average
  - 3 of 40 garages are "high-risk" and heavily overrepresented

Writes:
  insurance_lakehouse_bronze.claims_history_raw

Usage (CDE job, no args needed — all defaults are baked in):
    spark-submit generate_claims_bronze.py [n_claims]
"""

import logging
import random
import sys
from datetime import datetime, timedelta, timezone

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRONZE_DB = "insurance_lakehouse_bronze"
DEFAULT_N_CLAIMS = 4000

# Broader historical policy universe than policy_master's ~60 "active" rows
# (LH-POL-2000..2059, same numbering as generate_bronze.py's default
# N_POLICIES=60) -- see module docstring.
CLAIMS_POLICY_UNIVERSE_SIZE = 800
FREQUENT_CLAIMANT_PCT = 0.08
AMOUNT_OUTLIER_PCT = 0.05

# (mean, stddev) requested amount in INR, per claim type -- roughly
# proportionate to the coverage_limit ranges used in generate_bronze.py.
CLAIM_TYPE_PROFILES = {
    "Collision": (45000.0, 18000.0),
    "Theft": (280000.0, 110000.0),
    "Fire": (190000.0, 90000.0),
    "Glass": (4500.0, 1500.0),
    "ThirdParty": (60000.0, 28000.0),
    "NaturalDisaster": (130000.0, 60000.0),
}
CLAIM_TYPES = list(CLAIM_TYPE_PROFILES.keys())

STATUSES = ["APPROVED", "REJECTED", "PENDING", "UNDER_REVIEW"]
STATUS_WEIGHTS = [0.60, 0.15, 0.15, 0.10]

GARAGES = [
    "Prime Auto Body Shop, Mumbai", "Speedy Motors, Delhi", "City Garage, Bengaluru",
    "Highway Auto Care, Pune", "Metro Car Clinic, Chennai", "Elite Motors, Hyderabad",
    "Sunrise Auto Works, Ahmedabad", "Trust Garage, Kolkata", "Precision Auto, Jaipur",
    "Quick Fix Motors, Lucknow", "Reliable Car Care, Chandigarh", "Star Auto Body, Indore",
    "National Garage, Nagpur", "Comfort Motors, Surat", "Vision Auto Works, Kochi",
    "Premier Car Clinic, Bhopal", "Apex Motors, Patna", "Zenith Auto, Coimbatore",
    "Horizon Garage, Vadodara", "United Auto Care, Ludhiana", "Regal Motors, Nashik",
    "Diamond Auto Body, Rajkot", "Silver Line Garage, Visakhapatnam", "Classic Car Care, Agra",
    "Pioneer Motors, Guwahati", "Sunshine Auto, Thane", "Grand Auto Works, Faridabad",
    "Crown Garage, Ghaziabad", "Excel Motors, Amritsar", "Fortune Auto Care, Mysuru",
    # Intentional high-risk garages (heavily overrepresented + inflated payouts).
    "Rapid Repairs Garage, Mumbai", "Everfix Auto Body, Delhi", "Golden Wheels Motors, Pune",
    "Downtown Auto, Chennai", "Riverside Garage, Kolkata", "Lakeview Motors, Hyderabad",
    "Northside Auto Care, Jaipur", "Southgate Garage, Bengaluru", "Eastend Motors, Ahmedabad",
    "Westpark Auto, Lucknow",
]
HIGH_RISK_GARAGES = {"Rapid Repairs Garage, Mumbai", "Everfix Auto Body, Delhi", "Golden Wheels Motors, Pune"}

CLAIMS_SCHEMA = StructType([
    StructField("claim_id", StringType(), False),
    StructField("policy_number", StringType(), False),
    StructField("claim_type", StringType(), True),
    StructField("incident_date", StringType(), True),
    StructField("filed_date", StringType(), True),
    StructField("amount_requested", DoubleType(), True),
    StructField("amount_approved", DoubleType(), True),
    StructField("status", StringType(), True),
    StructField("garage_name", StringType(), True),
    StructField("source", StringType(), True),
    StructField("ingested_at", StringType(), True),
])


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-generate-claims-bronze").getOrCreate()


def _pick_garage(rng: random.Random) -> str:
    # High-risk garages get ~8x the sampling weight of a normal garage.
    weights = [8.0 if g in HIGH_RISK_GARAGES else 1.0 for g in GARAGES]
    return rng.choices(GARAGES, weights=weights, k=1)[0]


def _claims_count_for_policy(rng: random.Random, is_frequent: bool) -> int:
    if is_frequent:
        return rng.randint(4, 8)
    return rng.choices([0, 1, 2, 3], weights=[30, 40, 20, 10], k=1)[0]


def generate_claim_rows(n_target: int, now: datetime, seed: int = 7):
    rng = random.Random(seed)
    policy_numbers = [f"LH-POL-{2000 + i}" for i in range(CLAIMS_POLICY_UNIVERSE_SIZE)]
    frequent_set = set(rng.sample(policy_numbers, int(CLAIMS_POLICY_UNIVERSE_SIZE * FREQUENT_CLAIMANT_PCT)))

    # First pass: decide how many claims each policy gets, until we hit ~n_target.
    plan = []  # list of policy_number, repeated per claim
    for pn in policy_numbers:
        count = _claims_count_for_policy(rng, pn in frequent_set)
        plan.extend([pn] * count)
    rng.shuffle(plan)
    if len(plan) > n_target:
        plan = plan[:n_target]
    elif len(plan) < n_target:
        # Top up by resampling random policies (weighted toward frequent claimants).
        pool = policy_numbers
        weights = [3.0 if pn in frequent_set else 1.0 for pn in pool]
        shortfall = n_target - len(plan)
        plan.extend(rng.choices(pool, weights=weights, k=shortfall))

    now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for i, policy_number in enumerate(plan):
        claim_type = rng.choice(CLAIM_TYPES)
        mean, sd = CLAIM_TYPE_PROFILES[claim_type]
        amount = max(500.0, rng.normalvariate(mean, sd))
        if rng.random() < AMOUNT_OUTLIER_PCT:
            amount *= rng.uniform(2.5, 4.0)
        amount = round(amount, 2)

        status = rng.choices(STATUSES, weights=STATUS_WEIGHTS, k=1)[0]
        amount_approved = round(amount * rng.uniform(0.75, 0.95), 2) if status == "APPROVED" else None

        days_back = rng.randint(1, 730)  # spread over trailing ~24 months
        incident_dt = now - timedelta(days=days_back)
        filed_dt = incident_dt + timedelta(days=rng.randint(0, 5))

        rows.append((
            f"CLM-{100000 + i}",
            policy_number,
            claim_type,
            incident_dt.strftime("%Y-%m-%d"),
            filed_dt.strftime("%Y-%m-%d"),
            amount,
            amount_approved,
            status,
            _pick_garage(rng),
            "BRONZE_GENERATED",
            now_iso,
        ))
    return rows


def write_bronze(spark: SparkSession, n_claims: int) -> None:
    now = datetime.now(timezone.utc)
    rows = generate_claim_rows(n_claims, now)
    df = spark.createDataFrame(rows, schema=CLAIMS_SCHEMA)

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {BRONZE_DB}")

    df.createOrReplaceTempView("tmp_claims_history_raw")
    spark.sql(f"DROP TABLE IF EXISTS {BRONZE_DB}.claims_history_raw")
    spark.sql(f"""
        CREATE TABLE {BRONZE_DB}.claims_history_raw
        USING iceberg
        TBLPROPERTIES ('format-version'='2')
        AS SELECT * FROM tmp_claims_history_raw
    """)
    logger.info("Wrote %d rows to %s.claims_history_raw", df.count(), BRONZE_DB)


def _is_unset(val: str) -> bool:
    """True if arg is missing or an unsubstituted CDE template like {{n_claims}}."""
    return not val or (val.startswith("{{") and val.endswith("}}"))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    n_claims = int(arg) if arg and not _is_unset(arg) else DEFAULT_N_CLAIMS

    spark = get_spark()
    try:
        logger.info("Generating %d synthetic claims into bronze...", n_claims)
        write_bronze(spark, n_claims)
    finally:
        spark.stop()
