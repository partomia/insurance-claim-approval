import os

from sqlalchemy import inspect, text

from config import get_settings
from database import Base, SessionLocal, engine

settings = get_settings()

# Additive column migrations for SQLite (never drop data)
SQLITE_COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "policies": [
        ("customer_id", "INTEGER"),
        ("provider_id", "INTEGER"),
        ("premium_amount", "FLOAT DEFAULT 0"),
    ],
    "claims": [
        ("submission_step", "INTEGER DEFAULT 1"),
        ("policy_context_json", "TEXT DEFAULT '{}'"),
        ("policy_docs_source", "VARCHAR(32)"),
        ("escalation_flags", "TEXT DEFAULT '[]'"),
        ("escalation_messages", "TEXT DEFAULT '[]'"),
        ("assigned_agent", "VARCHAR(255)"),
        ("assigned_at", "DATETIME"),
        ("evidence_mismatch", "INTEGER DEFAULT 0"),
        ("evidence_issues", "TEXT DEFAULT '[]'"),
        ("pipeline_run_id", "INTEGER DEFAULT 0"),
        ("assigned_agent_id", "INTEGER"),
    ],
    "claim_decisions": [
        ("payout_breakdown", "TEXT DEFAULT '{}'"),
        ("approval_probability", "FLOAT"),
        ("coverage_estimate", "FLOAT"),
        ("expected_settlement", "FLOAT"),
        ("potential_problems", "TEXT DEFAULT '[]'"),
        ("recommendations", "TEXT DEFAULT '[]'"),
        ("missing_documents", "TEXT DEFAULT '[]'"),
        ("policy_clause_matches", "TEXT DEFAULT '[]'"),
        ("fraud_signals", "TEXT DEFAULT '[]'"),
        ("next_best_action", "VARCHAR(255)"),
        ("ai_explanation", "TEXT"),
    ],
}


def _apply_sqlite_migrations() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    with engine.begin() as conn:
        for table, columns in SQLITE_COLUMN_MIGRATIONS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_def in columns:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"))

        # Remove legacy table from early prototypes
        if "users" in tables:
            conn.execute(text("DROP TABLE IF EXISTS users"))

        _migrate_claims_nullable_policy_id(conn)


def _migrate_claims_nullable_policy_id(conn) -> None:
    """SQLite cannot ALTER COLUMN nullability — rebuild claims if policy_id is NOT NULL."""
    rows = conn.execute(text("PRAGMA table_info(claims)")).fetchall()
    if not rows:
        return
    policy_col = next((r for r in rows if r[1] == "policy_id"), None)
    if not policy_col or policy_col[3] == 0:
        return

    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(
        text(
            """
            CREATE TABLE claims_new (
                id INTEGER NOT NULL PRIMARY KEY,
                claim_number VARCHAR NOT NULL UNIQUE,
                customer_id INTEGER NOT NULL,
                policy_id INTEGER,
                incident_description TEXT NOT NULL,
                incident_datetime DATETIME NOT NULL,
                location VARCHAR NOT NULL,
                claim_amount FLOAT NOT NULL,
                status VARCHAR NOT NULL,
                submission_step INTEGER NOT NULL DEFAULT 1,
                policy_context_json TEXT NOT NULL DEFAULT '{}',
                policy_docs_source VARCHAR(32),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(customer_id) REFERENCES customers (id),
                FOREIGN KEY(policy_id) REFERENCES policies (id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO claims_new (
                id, claim_number, customer_id, policy_id, incident_description,
                incident_datetime, location, claim_amount, status, submission_step,
                policy_context_json, policy_docs_source, created_at, updated_at
            )
            SELECT
                id, claim_number, customer_id, policy_id, incident_description,
                incident_datetime, location, claim_amount, status, submission_step,
                policy_context_json, policy_docs_source, created_at, updated_at
            FROM claims
            """
        )
    )
    conn.execute(text("DROP TABLE claims"))
    conn.execute(text("ALTER TABLE claims_new RENAME TO claims"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_claims_id ON claims (id)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_claims_claim_number ON claims (claim_number)"))
    conn.execute(text("PRAGMA foreign_keys=ON"))


def ensure_schema(force_reset: bool = False) -> None:
    """Create missing tables/columns. Only wipe DB when explicitly forced."""
    should_reset = force_reset or os.getenv("FORCE_DB_RESET", "").lower() in ("1", "true", "yes")

    if should_reset:
        print("FORCE_DB_RESET: recreating database...")
        Base.metadata.drop_all(bind=engine)

    Base.metadata.create_all(bind=engine)
    _apply_sqlite_migrations()
    _backfill_assistant_threads()


def _backfill_assistant_threads() -> None:
    """Migrate legacy flat chat messages into assistant threads (one-time).

    Gated by `ASSISTANT_BACKFILL_ON_STARTUP` — flip to false in production once
    the first successful boot has migrated data, so we don't table-scan legacy
    chat tables on every restart.
    """
    if not settings.assistant_backfill_on_startup:
        return

    from services.assistant_memory_service import backfill_legacy_messages

    db = SessionLocal()
    try:
        backfill_legacy_messages(db)
    finally:
        db.close()
