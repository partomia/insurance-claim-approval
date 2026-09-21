"""Closes the OLTP -> lakehouse loop (see cde/README.md § Roadmap): pushes
real, app-filed claims that have finished the AI decision pipeline into a
dedicated Iceberg bronze table (insurance_lakehouse_bronze.app_claims_raw)
via Impala -- so the CDE claims-analytics pipeline's fraud/risk analytics
(cde/jobs/curate/curate_risk_signals_gold.py) are computed over real claims
too, not just the ~4,000-row synthetic claims_history_raw population.

Deliberately a SEPARATE bronze table from claims_history_raw, never the same
one: generate_claims_bronze.py does a full DROP TABLE + CREATE AS SELECT on
claims_history_raw on every synthetic-data regen -- writing real claims into
that same table would destroy them on the next run. app_claims_raw is only
ever appended to by this script; transform_claims_silver.py unions the two
bronze sources into the shared silver `claims_history` table, so no changes
are needed to curate_risk_signals_gold.py at all -- real claims flow through
the exact same fraud/risk analytics automatically once they reach silver.

What gets exported: claims that (a) have completed the AI pipeline (a
ClaimDecision row exists), (b) are linked to a policy (so a policy_number is
resolvable), and (c) haven't been exported yet (`lakehouse_exported_at IS
NULL`). Idempotent/incremental: successfully-exported claims are marked with
`lakehouse_exported_at`, so re-running only pushes newly-decided claims.

Batch, not real-time, matching every other lakehouse.sh command (seed,
verify, ingest) -- run manually or on a schedule (see
cml/jobs/lakehouse_export_claims_job.py) before the CDE claims-analytics
pipeline runs. If real-time ever becomes a requirement, the same
generate/transform/curate Spark jobs can be re-run as a Structured
Streaming job instead of swapping this script out.

Known simplification: `garage_name` isn't captured anywhere in the app today
(the wizard only uploads a repair-estimate *document*, not a structured
garage name) -- exported rows use a fixed placeholder so they never spuriously
trip the garage-risk anomaly detection. Revisit by adding a real field to the
Claim model + wizard Step 3 if/when that story matters.

Usage:
    uv run python scripts/export_claims_to_lakehouse.py            # export + mark exported
    uv run python scripts/export_claims_to_lakehouse.py --dry-run  # preview only, no writes
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from database import SessionLocal, _impala_connect  # noqa: E402
from db_init import ensure_schema  # noqa: E402
from models.claim import Claim, ClaimStatus, IncidentType  # noqa: E402
from models.audit import ClaimDecision  # noqa: E402
from models.policy import Policy  # noqa: E402

settings = get_settings()

BRONZE_DB_SUFFIX = "_bronze"

# Placeholder until the app captures a real garage/repair-shop name
# (see module docstring) -- never trips the garage-risk anomaly detector.
GARAGE_PLACEHOLDER = "Unspecified — App Claim"

# Maps the app's IncidentType enum to the lakehouse claim_type vocabulary
# used by cde/jobs/generate/generate_claims_bronze.py and validated in
# cde/jobs/validate/validate_claims_bronze.py's VALID_CLAIM_TYPES.
INCIDENT_TYPE_MAP = {
    IncidentType.COLLISION: "Collision",
    IncidentType.THEFT: "Theft",
    IncidentType.FIRE: "Fire",
    IncidentType.NATURAL_DISASTER: "NaturalDisaster",
    IncidentType.GLASS_ONLY: "Glass",
    IncidentType.THIRD_PARTY_LIABILITY: "ThirdParty",
    IncidentType.VANDALISM: "Vandalism",
    IncidentType.OTHER: "Other",
}

# Maps the app's (much larger) ClaimStatus enum down to the lakehouse's
# APPROVED/REJECTED/PENDING/UNDER_REVIEW vocabulary. Only claims with a
# ClaimDecision are considered (see query below), so this only needs to
# cover post-decision states.
STATUS_MAP = {
    ClaimStatus.APPROVED: "APPROVED",
    ClaimStatus.REJECTED: "REJECTED",
    ClaimStatus.ESCALATE: "UNDER_REVIEW",
    ClaimStatus.HUMAN_REVIEW: "UNDER_REVIEW",
    ClaimStatus.PENDING_REVIEW: "UNDER_REVIEW",
    ClaimStatus.REQUEST_MORE_INFO: "PENDING",
    ClaimStatus.SUBMISSION_READY: "PENDING",
    ClaimStatus.SUBMITTED_TO_INSURER: "PENDING",
}


def bronze_db() -> str:
    return f"{settings.lakehouse_database}{BRONZE_DB_SUFFIX}"


def sql_val(v) -> str:
    """See lakehouse_seed.py -- impyla has no bind-parameter support over
    HS2, so values are inlined with manual escaping. Fine for this script's
    own computed values (never raw user input); do not reuse for anything
    that echoes untrusted strings verbatim."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def ensure_table(cursor) -> None:
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {bronze_db()}")
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {bronze_db()}.app_claims_raw (
            claim_id STRING,
            policy_number STRING,
            claim_type STRING,
            incident_date STRING,
            filed_date STRING,
            amount_requested DOUBLE,
            amount_approved DOUBLE,
            status STRING,
            garage_name STRING,
            source STRING,
            ingested_at STRING
        )
        STORED AS ICEBERG
        TBLPROPERTIES ('format-version'='2')
        """
    )


def fetch_exportable_claims(db) -> list[Claim]:
    """Claims that finished the AI pipeline, are linked to a policy, and
    haven't been exported to the lakehouse yet."""
    return (
        db.query(Claim)
        .join(ClaimDecision, ClaimDecision.claim_id == Claim.id)
        .filter(Claim.policy_id.isnot(None))
        .filter(Claim.lakehouse_exported_at.is_(None))
        .all()
    )


def build_row(claim: Claim, policy_number: str, now_iso: str) -> tuple:
    decision = claim.decision
    status = STATUS_MAP.get(claim.status, "PENDING")
    amount_approved = decision.payable_amount if (decision and status == "APPROVED") else None
    claim_type = INCIDENT_TYPE_MAP.get(claim.incident_type, "Other")

    return (
        claim.claim_number,
        policy_number,
        claim_type,
        claim.incident_datetime.strftime("%Y-%m-%d") if claim.incident_datetime else None,
        claim.created_at.strftime("%Y-%m-%d") if claim.created_at else None,
        float(claim.claim_amount),
        float(amount_approved) if amount_approved is not None else None,
        status,
        GARAGE_PLACEHOLDER,
        "APP",
        now_iso,
    )


def run(dry_run: bool = False) -> None:
    ensure_schema()  # make sure lakehouse_exported_at (new column) exists

    db = SessionLocal()
    try:
        claims = fetch_exportable_claims(db)
        if not claims:
            print("No newly-decided, policy-linked, unexported claims found — nothing to export.")
            return

        rows = []
        skipped_no_policy_number = 0
        for claim in claims:
            policy = db.query(Policy).filter(Policy.id == claim.policy_id).first()
            if not policy or not policy.policy_number:
                skipped_no_policy_number += 1
                continue
            rows.append((claim, policy.policy_number))

        if not rows:
            print(
                f"Found {len(claims)} candidate claim(s), but none resolved a policy_number "
                f"({skipped_no_policy_number} skipped) — nothing to export."
            )
            return

        now = datetime.now(timezone.utc)
        now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
        values = [build_row(claim, policy_number, now_iso) for claim, policy_number in rows]

        print(f"\n==> {len(values)} claim(s) ready to export "
              f"({skipped_no_policy_number} skipped — no linked policy_number):")
        for row in values:
            print(f"    {row[0]}  policy={row[1]}  type={row[2]}  status={row[7]}  amount={row[5]}")

        if dry_run:
            print("\n[dry-run] Not writing to Impala or marking claims as exported.")
            return

        print(f"\nConnecting to Impala @ {settings.impala_host} (auth={settings.impala_auth_mechanism}) ...")
        conn = _impala_connect(database="default")
        cursor = conn.cursor()
        try:
            ensure_table(cursor)
            cols = [
                "claim_id", "policy_number", "claim_type", "incident_date", "filed_date",
                "amount_requested", "amount_approved", "status", "garage_name", "source",
                "ingested_at",
            ]
            value_rows = []
            for row in values:
                vals = [sql_val(v) for v in row]
                value_rows.append("(" + ", ".join(vals) + ")")
            sql = (
                f"INSERT INTO {bronze_db()}.app_claims_raw ({', '.join(cols)}) VALUES\n  "
                + ",\n  ".join(value_rows)
            )
            cursor.execute(sql)
            print(f"==> Inserted {len(values)} row(s) into {bronze_db()}.app_claims_raw")
        finally:
            cursor.close()
            conn.close()

        # Only mark as exported AFTER the Impala insert above succeeded, so a
        # failed run leaves every candidate claim re-exportable next time.
        for claim, _ in rows:
            claim.lakehouse_exported_at = now
        db.commit()
        print(f"==> Marked {len(rows)} claim(s) as exported (lakehouse_exported_at={now_iso})")
        print(
            "\nNext: run the CDE claims-analytics pipeline (transform-claims-silver -> "
            "curate-risk-signals-gold, see cde/README.md) to fold these into "
            "policy_risk_signals, then `bash cml/cli.sh lakehouse ingest` to pull the "
            "refreshed fraud_risk_score back into the app."
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be exported, without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
