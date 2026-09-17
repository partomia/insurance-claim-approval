"""
Stage 2 — Validate (bronze)
Data-quality gate on the bronze layer. Exits with code 1 on any failure so
CDE/Airflow marks the job run FAILED and stops the pipeline before bad data
reaches silver/gold — the same fail-fast pattern as a Great Expectations
checkpoint, implemented with plain Spark so no extra dependency is required.
(Swap in Great Expectations later if you want richer expectation suites.)

Reads:
  insurance_lakehouse_bronze.policy_master_raw
  insurance_lakehouse_bronze.policy_clauses_raw

Usage (CDE job, no args needed):
    spark-submit validate_bronze.py
"""

import logging
import sys

from pyspark.sql import SparkSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRONZE_DB = "insurance_lakehouse_bronze"
VALID_STATUSES = {"ACTIVE", "EXPIRED", "LAPSED", "CANCELLED"}


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-validate-bronze").getOrCreate()


def validate(spark: SparkSession) -> bool:
    failures = []

    policies = spark.table(f"{BRONZE_DB}.policy_master_raw")
    clauses = spark.table(f"{BRONZE_DB}.policy_clauses_raw")

    total_policies = policies.count()
    logger.info("policy_master_raw: %d rows", total_policies)
    if total_policies == 0:
        failures.append("policy_master_raw is empty")

    null_pn = policies.filter("policy_number IS NULL OR policy_number = ''").count()
    if null_pn > 0:
        failures.append(f"{null_pn} rows with null/empty policy_number")

    dupes = (
        policies.groupBy("policy_number").count()
        .filter("count > 1")
        .count()
    )
    if dupes > 0:
        failures.append(f"{dupes} duplicate policy_number values in policy_master_raw")

    bad_premium = policies.filter("premium_amount IS NULL OR premium_amount <= 0").count()
    if bad_premium > 0:
        failures.append(f"{bad_premium} rows with premium_amount <= 0")

    bad_coverage = policies.filter("coverage_limit IS NULL OR coverage_limit <= 0").count()
    if bad_coverage > 0:
        failures.append(f"{bad_coverage} rows with coverage_limit <= 0")

    statuses = {r.status for r in policies.select("status").distinct().collect()}
    unknown_statuses = statuses - VALID_STATUSES
    if unknown_statuses:
        failures.append(f"Unknown status values: {unknown_statuses}")

    total_clauses = clauses.count()
    logger.info("policy_clauses_raw: %d rows", total_clauses)
    if total_clauses == 0:
        failures.append("policy_clauses_raw is empty")

    # Referential check: every clause must point at a real policy.
    orphan_clauses = (
        clauses.select("policy_number").distinct()
        .join(policies.select("policy_number").distinct(), on="policy_number", how="left_anti")
        .count()
    )
    if orphan_clauses > 0:
        failures.append(f"{orphan_clauses} distinct policy_number(s) in policy_clauses_raw with no matching policy")

    if failures:
        for f in failures:
            logger.error("VALIDATION FAILED: %s", f)
        return False

    logger.info("All bronze validation checks passed (%d policies, %d clauses).", total_policies, total_clauses)
    return True


if __name__ == "__main__":
    spark = get_spark()
    try:
        ok = validate(spark)
    finally:
        spark.stop()
    sys.exit(0 if ok else 1)
