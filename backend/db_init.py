import os

from sqlalchemy import inspect, text

from config import get_settings
from database import Base, SessionLocal, get_engine

settings = get_settings()


def ensure_schema(force_reset: bool = False) -> None:
    """Create missing tables for the configured backend. Only wipe when forced."""
    should_reset = force_reset or os.getenv("FORCE_DB_RESET", "").lower() in ("1", "true", "yes")

    if should_reset:
        print("FORCE_DB_RESET: recreating database tables...")
        Base.metadata.drop_all(bind=get_engine())

    Base.metadata.create_all(bind=get_engine())

    # SQLite doesn't get columns added by create_all() on pre-existing tables,
    # so heal simple additive drift (new nullable/default columns) in place.
    if settings.uses_sqlite and not should_reset:
        _heal_sqlite_column_drift()
        _heal_sqlite_enum_drift()

    _backfill_assistant_threads()


def _heal_sqlite_column_drift() -> None:
    """Add model columns missing from existing SQLite tables via ALTER TABLE.

    Handles the common case where the ORM gained new nullable/default columns
    after the local `insurance.db` was first created. Columns that SQLite can't
    add non-destructively (e.g. new NOT NULL without a default) are reported so
    the operator can set FORCE_DB_RESET=1 to rebuild.
    """
    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            live_cols = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in live_cols:
                    continue
                ddl = _sqlite_add_column_ddl(table.name, column)
                if ddl is None:
                    print(
                        f"⚠ Cannot auto-add column {table.name}.{column.name} "
                        f"(needs a default or NOT NULL rebuild). "
                        f"Set FORCE_DB_RESET=1 to recreate the DB."
                    )
                    continue
                print(f"Healing schema: adding {table.name}.{column.name}")
                conn.execute(text(ddl))


def _heal_sqlite_enum_drift() -> None:
    """Rewrite stored enum values that are no longer defined by the ORM enum.

    When an Enum member is renamed/removed (e.g. a legacy DocumentType 'PROOF'),
    SQLAlchemy raises LookupError while *loading* any row that still holds the
    old string — turning every query that touches it into a 500. We can't drop
    the data, so map orphaned values to a safe bucket. Only enums that define an
    'OTHER' member are healed; status-like enums without a neutral fallback are
    left untouched (and reported) so we never silently mislabel them.
    """
    from sqlalchemy import Enum as SAEnum

    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            for column in table.columns:
                if not isinstance(column.type, SAEnum):
                    continue
                valid = set(column.type.enums)
                rows = conn.execute(
                    text(f'SELECT DISTINCT "{column.name}" FROM "{table.name}"')
                ).fetchall()
                orphaned = {r[0] for r in rows if r[0] is not None} - valid
                if not orphaned:
                    continue
                if "OTHER" not in valid:
                    print(
                        f"⚠ {table.name}.{column.name} holds values not in the "
                        f"current enum ({sorted(orphaned)}) and has no 'OTHER' "
                        f"fallback. Set FORCE_DB_RESET=1 or migrate manually."
                    )
                    continue
                for bad in orphaned:
                    print(
                        f"Healing enum drift: {table.name}.{column.name} "
                        f"'{bad}' → 'OTHER'"
                    )
                    conn.execute(
                        text(
                            f'UPDATE "{table.name}" SET "{column.name}" = \'OTHER\' '
                            f'WHERE "{column.name}" = :bad'
                        ),
                        {"bad": bad},
                    )


def _sqlite_add_column_ddl(table_name: str, column) -> str | None:
    """Build an `ALTER TABLE ... ADD COLUMN` for SQLite, or None if unsafe."""
    try:
        col_type = column.type.compile(dialect=get_engine().dialect)
    except Exception:
        col_type = "TEXT"

    import enum

    default = column.default
    default_sql = None
    if default is not None and getattr(default, "is_scalar", False):
        value = default.arg
        if isinstance(value, enum.Enum):
            # Enum columns store the member value (e.g. "COLLISION"), not repr.
            value = value.value
        if isinstance(value, bool):
            default_sql = "1" if value else "0"
        elif isinstance(value, (int, float)):
            default_sql = str(value)
        else:
            escaped = str(value).replace("'", "''")
            default_sql = f"'{escaped}'"

    # SQLite forbids adding a NOT NULL column without a constant default.
    if not column.nullable and default_sql is None:
        return None

    ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {col_type}'
    if not column.nullable:
        ddl += " NOT NULL"
    if default_sql is not None:
        ddl += f" DEFAULT {default_sql}"
    return ddl


def _backfill_assistant_threads() -> None:
    if not settings.assistant_backfill_on_startup:
        return

    from services.assistant_memory_service import backfill_legacy_messages

    db = SessionLocal()
    try:
        backfill_legacy_messages(db)
    finally:
        db.close()
