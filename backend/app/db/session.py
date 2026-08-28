"""
Engine/session setup.

The models use only cross-dialect SQLAlchemy types (String-encoded UUIDs,
generic JSON, plain Float lat/lon instead of a PostGIS Geography column) so
the exact same model code runs against the documented PostgreSQL+PostGIS
target (docker-compose) and against SQLite (this phase's local/test runs,
since Docker is not available in every environment this gets built in - see
the Phase 0/1 report's "known issues" for the concrete PostGIS migration
this implies before Phase 3/4's geospatial queries are needed).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

settings = get_settings()


def _make_engine():
    url = settings.database_url
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        # In-memory SQLite (used by the test suite) needs a StaticPool so
        # every connection in the pool shares the same in-memory database -
        # otherwise each new connection would see an empty schema.
        if ":memory:" in url:
            return create_engine(
                url, connect_args=connect_args, poolclass=StaticPool
            )
        return create_engine(url, connect_args=connect_args)
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
