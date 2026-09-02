import os

import pytest

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from sqlalchemy.orm import sessionmaker

from database import Base, create_db_engine, get_db, test_impala_connection


@pytest.fixture(scope="session")
def impala_engine():
    """Shared Impala engine; skip entire session if CDP Impala is unreachable."""
    try:
        test_impala_connection()
    except Exception as exc:
        pytest.skip(f"Impala not reachable: {exc}")
    engine = create_db_engine()
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(autouse=True)
def isolate_chroma_db(tmp_path, monkeypatch):
    chroma_path = str(tmp_path / "chroma")
    monkeypatch.setenv("CHROMA_DB_PATH", chroma_path)
    from config import get_settings

    get_settings.cache_clear()
    import rag.chroma_store as chroma_mod

    chroma_mod.settings = get_settings()
    chroma_mod.chroma_store._client = None
    chroma_mod.chroma_store._collection = None
    chroma_mod.chroma_store._embeddings = None


@pytest.fixture
def db_session(impala_engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=impala_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    from main import app

    app.dependency_overrides[get_db] = override_get_db
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
