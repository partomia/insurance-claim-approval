"""Stage 2b — Validate claims history (bronze)
Data-quality gate on the claims bronze layer, same fail-fast pattern as
validate_bronze.py. One check is deliberately *informational only*: claims
reference a broader historical policy-number universe than policy_master's
current ~60 "active" rows (see generate_claims_bronze.py docstring), so
overlap with policy_master is logged, not enforced as a hard failure.

Also validates `app_claims_raw` if it exists -- real, app-filed claims
pushed by backend/scripts/export_claims_to_lakehouse.py (closing the OLTP ->
lakehouse loop, see cde/README.md § Closing the loop). Same checks, same
fail-fast gate; skipped gracefully (not a failure) if that table doesn't
exist yet on a fresh deployment.

Reads:
  insurance_lakehouse_bronze.claims_history_raw
  insurance_lakehouse_bronze.app_claims_raw      (if present; real app claims)
  insurance_lakehouse_bronze.policy_master_raw   (for the informational
                                                    overlap check only)

Usage (CDE job, no args needed):
    spark-submit validate_claims_bronze.py
"""

import logging
import sys

from pyspark.sql import SparkSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRONZE_DB = "insurance_lakehouse_bronze"
# "Vandalism"/"Other" cover app-filed claims whose IncidentType has no
# equivalent in the synthetic generator's 6-value vocabulary (see
# backend/scripts/export_claims_to_lakehouse.py's INCIDENT_TYPE_MAP).
VALID_CLAIM_TYPES = {
    "Collision", "Theft", "Fire", "Glass", "ThirdParty", "NaturalDisaster",
    "Vandalism", "Other",
}
VALID_STATUSES = {"APPROVED", "REJECTED", "PENDING", "UNDER_REVIEW"}


def get_spark() -> SparkSession:
    return SparkSession.builder.appName("insurance-validate-claims-bronze").getOrCreate()


def _validate_table(claims, table_label: str) -> list[str]:
    """Same checks against any claims-shaped DataFrame; returns a list of
    failure messages (empty = passed)."""
    failures = []

    total = claims.count()
    logger.info("%s: %d rows", table_label, total)
    if total == 0:
        failures.append(f"{table_label} is empty")

    null_id = claims.filter("claim_id IS NULL OR claim_id = ''").count()
    if null_id > 0:
        failures.append(f"{table_label}: {null_id} rows with null/empty claim_id")

    null_pn = claims.filter("policy_number IS NULL OR policy_number = ''").count()
    if null_pn > 0:
        failures.append(f"{table_label}: {null_pn} rows with null/empty policy_number")

    dupes = claims.groupBy("claim_id").count().filter("count > 1").count()
    if dupes > 0:
        failures.append(f"{table_label}: {dupes} duplicate claim_id values")

    bad_amount = claims.filter("amount_requested IS NULL OR amount_requested <= 0").count()
    if bad_amount > 0:
        failures.append(f"{table_label}: {bad_amount} rows with amount_requested <= 0")

    over_approved = claims.filter("amount_approved IS NOT NULL AND amount_approved > amount_requested").count()
    if over_approved > 0:
        failures.append(f"{table_label}: {over_approved} rows where amount_approved > amount_requested")

    bad_dates = claims.filter("incident_date IS NOT NULL AND filed_date IS NOT NULL AND filed_date < incident_date").count()
    if bad_dates > 0:
        failures.append(f"{table_label}: {bad_dates} rows where filed_date is before incident_date")

    types = {r.claim_type for r in claims.select("claim_type").distinct().collect()}
    unknown_types = types - VALID_CLAIM_TYPES
    if unknown_types:
        failures.append(f"{table_label}: unknown claim_type values: {unknown_types}")

    statuses = {r.status for r in claims.select("status").distinct().collect()}
    unknown_statuses = statuses - VALID_STATUSES
    if unknown_statuses:
        failures.append(f"{table_label}: unknown status values: {unknown_statuses}")

    return failures


def validate(spark: SparkSession) -> bool:
    failures = []

    claims = spark.table(f"{BRONZE_DB}.claims_history_raw")
    failures.extend(_validate_table(claims, "claims_history_raw"))

    try:
        app_claims = spark.table(f"{BRONZE_DB}.app_claims_raw")
        failures.extend(_validate_table(app_claims, "app_claims_raw"))
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "No %s.app_claims_raw table yet (%s) -- skipping (created once "
            "backend/scripts/export_claims_to_lakehouse.py runs at least once).",
            BRONZE_DB, exc,
        )

    # Informational only: claims intentionally span a broader historical
    # policy universe than the current policy_master snapshot.
    try:
        policies = spark.table(f"{BRONZE_DB}.policy_master_raw")
        claim_pns = claims.select("policy_number").distinct()
        overlap = claim_pns.join(policies.select("policy_number").distinct(), on="policy_number", how="inner").count()
        total_distinct = claim_pns.count()
        logger.info(
            "Policy-number overlap with policy_master_raw: %d / %d distinct claim policy_numbers "
            "(remainder represent historical/lapsed policies outside the current active snapshot -- expected)",
            overlap, total_distinct,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not compute policy_master overlap (informational only): %s", exc)

    if failures:
        for f in failures:
            logger.error("VALIDATION FAILED: %s", f)
        return False

    logger.info("All claims bronze validation checks passed.")
    return True


if __name__ == "__main__":
    spark = get_spark()
    try:
        ok = validate(spark)
    finally:
        spark.stop()
    sys.exit(0 if ok else 1)
