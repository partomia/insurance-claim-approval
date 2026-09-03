import os

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
    _backfill_assistant_threads()


def _backfill_assistant_threads() -> None:
    if not settings.assistant_backfill_on_startup:
        return

    from services.assistant_memory_service import backfill_legacy_messages

    db = SessionLocal()
    try:
        backfill_legacy_messages(db)
    finally:
        db.close()
