"""
Neo4j connectivity (docs/DATA_MODEL.md §3). Phase 1 writes nothing to the
graph - the Graph Builder that populates it is Phase 2 work, gated on the
`/v1/transactions/ingest` endpoint this phase deliberately does not build.
This module exists so (a) the driver/connection plumbing is proven now
rather than invented under Phase 2 time pressure, and (b) the health check
can report real connectivity - or a real, non-fatal "unavailable" - rather
than pretending Neo4j is wired in when it isn't reachable.
"""
from typing import Optional

from neo4j import Driver, GraphDatabase

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)
settings = get_settings()

_driver: Optional[Driver] = None


def get_driver() -> Optional[Driver]:
    global _driver
    if _driver is None:
        try:
            _driver = GraphDatabase.driver(
                settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
            )
        except Exception as exc:  # driver construction itself rarely fails, but never crash startup
            logger.warning("neo4j.driver_init_failed", extra={"extra_fields": {"error": str(exc)}})
            return None
    return _driver


def check_connectivity() -> bool:
    driver = get_driver()
    if driver is None:
        return False
    try:
        driver.verify_connectivity()
        return True
    except Exception as exc:
        logger.warning("neo4j.unreachable", extra={"extra_fields": {"error": str(exc)}})
        return False


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


# docs/DATA_MODEL.md §3 constraints - safe to run repeatedly (IF NOT EXISTS).
# Not invoked automatically in Phase 1 (nothing writes to the graph yet);
# provided for `scripts/init_neo4j.py` and for Phase 2 to reuse verbatim.
SCHEMA_CONSTRAINTS = [
    "CREATE CONSTRAINT complaint_id_unique IF NOT EXISTS FOR (c:Complaint) REQUIRE c.complaint_id IS UNIQUE",
    "CREATE CONSTRAINT account_hash_unique IF NOT EXISTS FOR (a:Account) REQUIRE a.account_hash IS UNIQUE",
    "CREATE CONSTRAINT device_hash_unique IF NOT EXISTS FOR (d:Device) REQUIRE d.device_hash IS UNIQUE",
    "CREATE CONSTRAINT phone_hash_unique IF NOT EXISTS FOR (p:Phone) REQUIRE p.phone_hash IS UNIQUE",
    "CREATE CONSTRAINT exit_channel_id_unique IF NOT EXISTS FOR (e:ExitChannel) REQUIRE e.channel_id IS UNIQUE",
    "CREATE INDEX exit_channel_h3_cell IF NOT EXISTS FOR (e:ExitChannel) ON (e.h3_cell)",
]


def initialize_schema() -> None:
    driver = get_driver()
    if driver is None:
        raise RuntimeError("Neo4j driver is not available")
    with driver.session() as session:
        for statement in SCHEMA_CONSTRAINTS:
            session.run(statement)
