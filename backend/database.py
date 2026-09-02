from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from config import get_settings

settings = get_settings()
Base = declarative_base()

_engine = None
_SessionLocal = None


def _impala_connect_kwargs(*, database: str | None = None) -> dict:
    db = database or settings.impala_database
    kwargs = {
        "host": settings.impala_host,
        "port": settings.impala_port,
        "database": db,
        "use_ssl": settings.impala_use_ssl,
        "auth_mechanism": settings.impala_auth_mechanism,
        "use_http_transport": settings.impala_use_http_transport,
        "http_path": settings.impala_http_path,
        "kerberos_service_name": settings.impala_kerberos_service_name,
    }
    if settings.impala_user:
        kwargs["user"] = settings.impala_user
    if settings.impala_password:
        kwargs["password"] = settings.impala_password
    return kwargs


def _impala_connect(database: str | None = None):
    from impala.dbapi import connect

    return connect(**_impala_connect_kwargs(database=database))


def create_db_engine(*, database: str | None = None):
    db = database or settings.impala_database

    def creator():
        return _impala_connect(db)

    return create_engine(
        "impala://",
        creator=creator,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


class _EngineProxy:
    def __getattr__(self, name):
        return getattr(get_engine(), name)


engine = _EngineProxy()


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


class _SessionLocalProxy:
    def __call__(self, *args, **kwargs):
        return get_session_factory()(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(get_session_factory(), name)


SessionLocal = _SessionLocalProxy()


def test_impala_connection() -> None:
    with create_db_engine().connect() as conn:
        conn.execute(text("SELECT 1"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
