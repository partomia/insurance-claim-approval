"""Phase 1 of the Cloudera datalakehouse story: create + seed a small Iceberg
schema (via Impala) mirroring the app's policy reference data.

This is DELIBERATELY independent of DB_BACKEND / the app's OLTP database:
the live app keeps running on SQLite (see backend/config.py `uses_sqlite`),
and this script only proves out reading/writing an Iceberg table on the same
CDP cluster the app *could* use for DB_BACKEND=impala. It reuses the
IMPALA_* connection settings from backend/.env but targets a separate
schema (LAKEHOUSE_DATABASE, default "insurance_lakehouse").

Roadmap (not built here):
  Phase 2 — a Spark medallion pipeline (bronze/silver/gold) produces these
            same target tables at real volume, replacing this hand-seeded
            data. Schema stays compatible so nothing downstream changes.
  Phase 3 — an app-side ingestion script (cml.data_v1, mirroring a typical
            "load gold table via Impala into pandas" pattern) pulls
            policy_master/policy_clauses into SQLite + Chroma for RAG.

Usage:
    uv run python scripts/lakehouse_seed.py seed      # create schema/tables + insert demo rows
    uv run python scripts/lakehouse_seed.py verify    # read-only: counts + sample rows + DDL check
                                                       # (also checks policy_risk_signals /
                                                       # garage_risk_signals from the CDE
                                                       # claims-analytics pipeline, if present)
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from database import _impala_connect  # noqa: E402

settings = get_settings()

# --------------------------------------------------------------------------- #
# Demo data — mirrors the shape of models/policy.py (Policy, PolicyDocument),
# but intentionally not imported from scripts/seed.py to keep this script
# standalone (no SQLAlchemy session / SQLite side effects). Policy numbers are
# prefixed LH- so they're obviously distinct from the SQLite-seeded demo data
# if the two ever get merged in Phase 3.
# --------------------------------------------------------------------------- #
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

POLICIES = [
    {
        "policy_number": "LH-POL-1001",
        "customer_name": "Ananya Rao",
        "customer_email": "ananya.rao@example.com",
        "provider_name": "Bajaj Allianz Motor",
        "policy_type": "Motor",
        "premium_amount": 18500.0,
        "status": "ACTIVE",
        "coverage_limit": 800000.0,
        "deductible": 500.0,
        "co_pay_pct": 10.0,
        "waiting_period_days": 0,
        "effective_date": "2025-04-01",
        "expiry_date": "2026-03-31",
        "depreciation_rate": 5.0,
        "covered_vehicle_vin": "MA3ERLF1S00123456",
        "covered_make": "Maruti Suzuki",
        "covered_model": "Baleno",
        "covered_year": 2022,
        "no_claim_bonus_pct": 20.0,
        "zero_depreciation_addon": True,
        "roadside_assistance_addon": True,
    },
    {
        "policy_number": "LH-POL-1002",
        "customer_name": "Vikram Shah",
        "customer_email": "vikram.shah@example.com",
        "provider_name": "ICICI Lombard Motor",
        "policy_type": "Motor",
        "premium_amount": 24200.0,
        "status": "ACTIVE",
        "coverage_limit": 1200000.0,
        "deductible": 750.0,
        "co_pay_pct": 10.0,
        "waiting_period_days": 0,
        "effective_date": "2025-08-15",
        "expiry_date": "2026-08-14",
        "depreciation_rate": 10.0,
        "covered_vehicle_vin": "MBJZKF3AXPB654321",
        "covered_make": "Hyundai",
        "covered_model": "Creta",
        "covered_year": 2023,
        "no_claim_bonus_pct": 0.0,
        "zero_depreciation_addon": False,
        "roadside_assistance_addon": True,
    },
    {
        "policy_number": "LH-POL-1003",
        "customer_name": "Priya Menon",
        "customer_email": "priya.menon@example.com",
        "provider_name": "HDFC ERGO Motor",
        "policy_type": "Motor",
        "premium_amount": 15900.0,
        "status": "EXPIRED",
        "coverage_limit": 650000.0,
        "deductible": 500.0,
        "co_pay_pct": 15.0,
        "waiting_period_days": 0,
        "effective_date": "2024-01-10",
        "expiry_date": "2025-01-09",
        "depreciation_rate": 20.0,
        "covered_vehicle_vin": "MA1TA2AH9G0987654",
        "covered_make": "Tata",
        "covered_model": "Nexon",
        "covered_year": 2020,
        "no_claim_bonus_pct": 35.0,
        "zero_depreciation_addon": False,
        "roadside_assistance_addon": False,
    },
]

CLAUSE_TEMPLATE = [
    (
        "Policy Schedule",
        "Section 1.0",
        "This Motor Comprehensive Policy provides own-damage and third-party "
        "liability coverage for the insured private vehicle for a period of "
        "12 months from the effective date. Insured Declared Value (IDV) is "
        "the maximum settlement amount for total loss.",
    ),
    (
        "Coverage Details",
        "Section 4.2",
        "Own-damage coverage includes collision, theft, fire, vandalism, "
        "natural disasters, and glass breakage. Third-party liability covers "
        "bodily injury and property damage to third parties as required by law.",
    ),
    (
        "Exclusions",
        "Section 7.1",
        "Exclusions: driving under influence of alcohol or drugs, driving "
        "without a valid licence, racing or speed testing, commercial use "
        "without endorsement, consequential loss, mechanical/electrical "
        "breakdown, wear and tear, and damage caused by war or nuclear risks.",
    ),
    (
        "Claim Settlement",
        "Section 3.5",
        "Deductible applies per own-damage claim. Depreciation applied per "
        "the schedule unless the zero-depreciation add-on is active. Claims "
        "must be intimated within 48 hours of the incident.",
    ),
]

TABLES = ("policy_master", "policy_clauses")

# Phase 2b (CDE claims-analytics pipeline, see cde/README.md) — optional:
# only present after running rsingh-insurance-curate-risk-signals-gold (or
# the full Airflow DAG) at least once. Not created/seeded by this script.
ANALYTICS_TABLES = ("policy_risk_signals", "garage_risk_signals")


# --------------------------------------------------------------------------- #
# SQL helpers — impyla has no bind-parameter support over the HS2 protocol,
# so values are inlined with manual escaping. Fine for a small, trusted, admin
# seed script; do not reuse this pattern for user-supplied input.
# --------------------------------------------------------------------------- #
def sql_val(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def db() -> str:
    return settings.lakehouse_database


def run(cursor, sql: str, *, quiet: bool = False):
    if not quiet:
        print(f"  $ {sql.strip().splitlines()[0][:100]}...")
    cursor.execute(sql)


def create_schema_and_tables(cursor) -> None:
    print(f"\n==> Creating schema `{db()}` (if not exists)")
    run(cursor, f"CREATE DATABASE IF NOT EXISTS {db()}")

    print(f"\n==> Creating Iceberg table `{db()}.policy_master` (if not exists)")
    run(
        cursor,
        f"""
        CREATE TABLE IF NOT EXISTS {db()}.policy_master (
            policy_number STRING,
            customer_name STRING,
            customer_email STRING,
            provider_name STRING,
            policy_type STRING,
            premium_amount DOUBLE,
            status STRING,
            coverage_limit DOUBLE,
            deductible DOUBLE,
            co_pay_pct DOUBLE,
            waiting_period_days INT,
            effective_date STRING,
            expiry_date STRING,
            depreciation_rate DOUBLE,
            covered_vehicle_vin STRING,
            covered_make STRING,
            covered_model STRING,
            covered_year INT,
            no_claim_bonus_pct DOUBLE,
            zero_depreciation_addon BOOLEAN,
            roadside_assistance_addon BOOLEAN,
            source STRING,
            ingested_at STRING
        )
        STORED AS ICEBERG
        TBLPROPERTIES ('format-version'='2')
        """,
    )

    print(f"\n==> Creating Iceberg table `{db()}.policy_clauses` (if not exists)")
    run(
        cursor,
        f"""
        CREATE TABLE IF NOT EXISTS {db()}.policy_clauses (
            policy_number STRING,
            title STRING,
            section_ref STRING,
            content_text STRING,
            source STRING,
            ingested_at STRING
        )
        STORED AS ICEBERG
        TBLPROPERTIES ('format-version'='2')
        """,
    )


def truncate_if_supported(cursor, table: str) -> None:
    try:
        run(cursor, f"TRUNCATE TABLE {db()}.{table}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] TRUNCATE not supported/failed for {table} ({exc}); "
              f"inserting anyway (may duplicate rows on re-run)")


def seed_policy_master(cursor) -> None:
    truncate_if_supported(cursor, "policy_master")
    rows = []
    for p in POLICIES:
        cols = [
            "policy_number", "customer_name", "customer_email", "provider_name",
            "policy_type", "premium_amount", "status", "coverage_limit",
            "deductible", "co_pay_pct", "waiting_period_days", "effective_date",
            "expiry_date", "depreciation_rate", "covered_vehicle_vin",
            "covered_make", "covered_model", "covered_year",
            "no_claim_bonus_pct", "zero_depreciation_addon",
            "roadside_assistance_addon",
        ]
        vals = [sql_val(p[c]) for c in cols] + [sql_val("SEED"), sql_val(NOW)]
        rows.append("(" + ", ".join(vals) + ")")
    sql = f"INSERT INTO {db()}.policy_master VALUES\n  " + ",\n  ".join(rows)
    print(f"\n==> Inserting {len(rows)} rows into `{db()}.policy_master`")
    run(cursor, sql, quiet=True)


def seed_policy_clauses(cursor) -> None:
    truncate_if_supported(cursor, "policy_clauses")
    rows = []
    for p in POLICIES:
        for title, section_ref, content_text in CLAUSE_TEMPLATE:
            vals = [
                sql_val(p["policy_number"]),
                sql_val(title),
                sql_val(section_ref),
                sql_val(content_text),
                sql_val("SEED"),
                sql_val(NOW),
            ]
            rows.append("(" + ", ".join(vals) + ")")
    sql = f"INSERT INTO {db()}.policy_clauses VALUES\n  " + ",\n  ".join(rows)
    print(f"\n==> Inserting {len(rows)} rows into `{db()}.policy_clauses`")
    run(cursor, sql, quiet=True)


def verify(cursor) -> None:
    print(f"\n==> Verifying `{db()}` on {settings.impala_host}")
    for table in TABLES + ANALYTICS_TABLES:
        full = f"{db()}.{table}"
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {full}")
            (count,) = cursor.fetchone()
        except Exception as exc:  # noqa: BLE001
            hint = (
                " (not created yet — run the CDE claims-analytics pipeline, "
                "see cde/README.md)"
                if table in ANALYTICS_TABLES
                else ""
            )
            print(f"  [error] {full}: {exc}{hint}")
            continue
        print(f"  {full}: {count} rows")

        cursor.execute(f"SHOW CREATE TABLE {full}")
        ddl = "\n".join(r[0] for r in cursor.fetchall())
        iceberg_ok = "ICEBERG" in ddl.upper()
        print(f"    STORED AS ICEBERG: {'yes' if iceberg_ok else 'NO — unexpected!'}")

        cursor.execute(f"SELECT * FROM {full} LIMIT 2")
        cols = [d[0] for d in cursor.description]
        for row in cursor.fetchall():
            preview = dict(zip(cols, row))
            print(f"    sample: { {k: preview[k] for k in list(preview)[:4]} } ...")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["seed", "verify"], default="seed", nargs="?")
    args = parser.parse_args()

    print(f"Connecting to Impala @ {settings.impala_host} "
          f"(auth={settings.impala_auth_mechanism}) ...")
    conn = _impala_connect(database="default")
    cursor = conn.cursor()
    try:
        if args.mode == "seed":
            create_schema_and_tables(cursor)
            seed_policy_master(cursor)
            seed_policy_clauses(cursor)
            print("\n==> Seed complete. Run 'verify' to double-check:")
            print("    uv run python scripts/lakehouse_seed.py verify")
        verify(cursor)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
