import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db


@pytest.fixture(autouse=True)
def isolate_chroma_db(tmp_path, monkeypatch):
    """Use a fresh Chroma path per test to avoid cross-test pollution."""
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
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
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
