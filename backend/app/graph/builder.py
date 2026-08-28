"""
Graph Builder — Phase 2A (docs/AI_ML_ARCHITECTURE.md §1, docs/ARCHITECTURE.md,
docs/DATA_MODEL.md §3, docs/API_CONTRACT.md §1b/§1c).

PostgreSQL is the system of record; every function here is a *derived* write
to Neo4j and is called only after the corresponding Postgres row is already
committed. Failure here is caught and logged, never raised - a Neo4j outage
must not lose or block a real financial transaction record
(API_CONTRACT.md §1b). `scripts/rebuild_neo4j_graph.py` is what recovers
from any drift this causes.

Only the node/relationship types listed in API_CONTRACT.md §1c are written
here. Ring/sharing/case-linkage relationships are Ring Detector (Phase 2B,
Louvain) output and are deliberately not computed by this module.
"""
from typing import Optional

from neo4j import Driver

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.models.exit_channels import ExitChannel
from app.db.neo4j_client import get_driver

logger = get_logger(__name__)
settings = get_settings()

MAX_HOP_DEPTH = settings.max_hop_depth

# LinkedEntityType value -> (Neo4j node label, node id property, relationship type)
_ENTITY_GRAPH_SHAPE = {
    "device": ("Device", "device_hash", "HAS_DEVICE"),
    "phone": ("Phone", "phone_hash", "HAS_PHONE"),
    "ip": ("IP", "ip_hash", "HAS_IP"),
    "vpa": ("VPA", "vpa_hash", "HAS_VPA"),
}


def _safe_session(driver: Optional[Driver]):
    """Returns a Neo4j session, or None if the driver is unavailable. Callers
    treat None as "skip this write" rather than raising."""
    if driver is None:
        return None
    try:
        return driver.session()
    except Exception as exc:  # pragma: no cover - defensive, driver-level failure
        logger.warning("graph.session_unavailable", extra={"extra_fields": {"error": str(exc)}})
        return None


def sync_exit_channel(channel: ExitChannel, driver: Optional[Driver] = None) -> None:
    """MERGEs one ExitChannel reference-data node from its Postgres row.
    Called by the rebuild script for every row, and may also be called
    ad hoc when a transaction references a channel the graph hasn't seen
    yet. Never called by anything that should be *creating* new exit
    channels - those only ever come from Postgres."""
    driver = driver or get_driver()
    session = _safe_session(driver)
    if session is None:
        logger.warning("graph.sync_exit_channel_skipped", extra={"extra_fields": {"channel_id": channel.channel_id}})
        return
    try:
        with session:
            session.run(
                "MERGE (e:ExitChannel {channel_id: $channel_id}) "
                "SET e.channel_type = $channel_type, e.h3_cell = $h3_cell, "
                "    e.lat = $lat, e.lon = $lon",
                channel_id=channel.channel_id,
                channel_type=channel.channel_type.value,
                h3_cell=channel.h3_cell,
                lat=channel.geo_lat,
                lon=channel.geo_lon,
            )
    except Exception as exc:
        logger.warning(
            "graph.sync_exit_channel_failed",
            extra={"extra_fields": {"channel_id": channel.channel_id, "error": str(exc)}},
        )


def ensure_complaint_victim_link(
    complaint_id: str, victim_account_hash: str, driver: Optional[Driver] = None
) -> None:
    """(:Complaint)-[:INVOLVES]->(:Account) - idempotent, safe to call on
    every transaction for a complaint (MERGE, not CREATE)."""
    driver = driver or get_driver()
    session = _safe_session(driver)
    if session is None:
        logger.warning(
            "graph.victim_link_skipped", extra={"extra_fields": {"complaint_id": complaint_id}}
        )
        return
    try:
        with session:
            session.run(
                "MERGE (c:Complaint {complaint_id: $complaint_id}) "
                "MERGE (a:Account {account_hash: $account_hash}) "
                "MERGE (c)-[:INVOLVES]->(a)",
                complaint_id=complaint_id,
                account_hash=victim_account_hash,
            )
    except Exception as exc:
        logger.warning(
            "graph.victim_link_failed",
            extra={"extra_fields": {"complaint_id": complaint_id, "error": str(exc)}},
        )


# LinkedEntityType values that exist in Postgres (docs/DATA_MODEL.md §2) but
# are deliberately not represented as graph nodes in Phase 2A's approved
# entity list (API_CONTRACT.md §1c: Account/Device/Phone/IP/VPA/ExitChannel/
# Complaint only). Not an error when encountered - just not graphed.
_ENTITY_TYPES_NOT_GRAPHED = {"email", "address_cluster"}


def link_entity(
    account_hash: str, entity_type: str, entity_hash: str, driver: Optional[Driver] = None
) -> None:
    """(:Account)-[:HAS_{TYPE}]->(:Device|Phone|IP|VPA {..._hash}). `entity_type`
    must be one of _ENTITY_GRAPH_SHAPE's keys (device/phone/ip/vpa) - a
    fixed, code-controlled set, never interpolated from request data, so
    building the Cypher label/relationship name via an f-string here carries
    no injection risk."""
    shape = _ENTITY_GRAPH_SHAPE.get(entity_type)
    if shape is None:
        if entity_type not in _ENTITY_TYPES_NOT_GRAPHED:
            logger.warning("graph.unknown_entity_type", extra={"extra_fields": {"entity_type": entity_type}})
        return
    label, id_property, relationship = shape

    driver = driver or get_driver()
    session = _safe_session(driver)
    if session is None:
        logger.warning("graph.link_entity_skipped", extra={"extra_fields": {"entity_type": entity_type}})
        return
    try:
        with session:
            session.run(
                f"MERGE (a:Account {{account_hash: $account_hash}}) "
                f"MERGE (n:{label} {{{id_property}: $entity_hash}}) "
                f"MERGE (a)-[:{relationship}]->(n)",
                account_hash=account_hash,
                entity_hash=entity_hash,
            )
    except Exception as exc:
        logger.warning(
            "graph.link_entity_failed",
            extra={"extra_fields": {"entity_type": entity_type, "error": str(exc)}},
        )


def apply_transaction(
    *,
    from_hash: str,
    to_hash: str,
    txn_id: str,
    amount: str,
    channel: str,
    hop_index: int,
    occurred_at: str,
    exit_channel_id: Optional[str] = None,
    driver: Optional[Driver] = None,
) -> bool:
    """(:Account)-[:TRANSFERRED_TO]->(:Account), and optionally
    (:Account)-[:EXITED_VIA]->(:ExitChannel). Returns False (and writes
    nothing) if `hop_index` is at or beyond the configured max depth - this
    is the bounded-traversal enforcement point for graph *writes*
    (API_CONTRACT.md §1a/§1c): the Postgres row is unaffected either way,
    only the derived graph edge is skipped."""
    if hop_index > MAX_HOP_DEPTH:
        logger.warning(
            "graph.transferred_to_skipped_max_depth",
            extra={"extra_fields": {"txn_id": txn_id, "hop_index": hop_index, "max_hop_depth": MAX_HOP_DEPTH}},
        )
        return False

    driver = driver or get_driver()
    session = _safe_session(driver)
    if session is None:
        logger.warning("graph.apply_transaction_skipped", extra={"extra_fields": {"txn_id": txn_id}})
        return False

    try:
        with session:
            session.run(
                "MERGE (a:Account {account_hash: $from_hash}) "
                "MERGE (b:Account {account_hash: $to_hash}) "
                "MERGE (a)-[t:TRANSFERRED_TO {txn_id: $txn_id}]->(b) "
                "SET t.amount = $amount, t.channel = $channel, "
                "    t.hop_index = $hop_index, t.occurred_at = $occurred_at",
                from_hash=from_hash,
                to_hash=to_hash,
                txn_id=txn_id,
                amount=amount,
                channel=channel,
                hop_index=hop_index,
                occurred_at=occurred_at,
            )
            if exit_channel_id:
                session.run(
                    "MATCH (b:Account {account_hash: $to_hash}) "
                    "MATCH (e:ExitChannel {channel_id: $exit_channel_id}) "
                    "MERGE (b)-[x:EXITED_VIA]->(e) "
                    "SET x.amount = $amount, x.occurred_at = $occurred_at",
                    to_hash=to_hash,
                    exit_channel_id=exit_channel_id,
                    amount=amount,
                    occurred_at=occurred_at,
                )
        return True
    except Exception as exc:
        logger.warning(
            "graph.apply_transaction_failed",
            extra={"extra_fields": {"txn_id": txn_id, "error": str(exc)}},
        )
        return False


def fetch_complaint_subgraph(
    complaint_id: str, max_depth: Optional[int] = None, driver: Optional[Driver] = None
) -> list[dict]:
    """Bounded-depth read (API_CONTRACT.md §1a "bounded traversal"; matches
    DATA_MODEL.md §3's documented canonical query). `max_depth` is always an
    int from our own config or an explicit caller value, never raw request
    input - Cypher's `*1..N` variable-length path syntax cannot be
    parameterized, so inlining it via f-string is the standard, safe
    approach here (not a request-controlled injection surface)."""
    depth = max_depth or MAX_HOP_DEPTH
    driver = driver or get_driver()
    session = _safe_session(driver)
    if session is None:
        return []

    query = (
        "MATCH (c:Complaint {complaint_id: $complaint_id})-[:INVOLVES]->(v:Account) "
        f"OPTIONAL MATCH path = (v)-[:TRANSFERRED_TO*1..{depth}]->(a:Account) "
        "RETURN v.account_hash AS victim_hash, "
        "       [n IN nodes(path) | n.account_hash] AS chain_hashes, "
        "       length(path) AS depth"
    )
    try:
        with session:
            result = session.run(query, complaint_id=complaint_id)
            return [dict(record) for record in result]
    except Exception as exc:
        logger.warning(
            "graph.fetch_subgraph_failed",
            extra={"extra_fields": {"complaint_id": complaint_id, "error": str(exc)}},
        )
        return []
