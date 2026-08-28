"""Shared helpers for the ORM models."""
import uuid


def new_uuid() -> str:
    """UUIDs are stored as 36-char strings (not the Postgres-native UUID
    type) so the identical model definitions work unmodified against both
    PostgreSQL (docker-compose, the documented target) and SQLite (this
    phase's Docker-less local/test runs). Trivial to switch to
    sqlalchemy.Uuid once we standardize on a single database engine for
    every environment."""
    return str(uuid.uuid4())
