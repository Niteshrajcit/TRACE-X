from fastapi import APIRouter
from sqlalchemy import text

from app.db.neo4j_client import check_connectivity
from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness + dependency status. Postgres is required (system of record,
    docs/ARCHITECTURE.md §2); Neo4j is best-effort in this phase since
    nothing writes to it yet (see app/db/neo4j_client.py) - its absence is
    reported, not fatal."""
    postgres_ok = True
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception:
        postgres_ok = False

    neo4j_ok = check_connectivity()

    return {
        "status": "ok" if postgres_ok else "degraded",
        "dependencies": {
            "postgres": "up" if postgres_ok else "down",
            "neo4j": "up" if neo4j_ok else "unavailable",
        },
    }
