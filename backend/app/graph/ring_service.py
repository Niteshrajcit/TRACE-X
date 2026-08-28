"""
Orchestrates one full ring-detection run (docs/AI_ML_ARCHITECTURE.md §2/§2a/
§2b, docs/DATA_MODEL.md §2 Phase 2B addition):

    materialize shared-entity edges -> build projection -> Louvain
    -> per-community features -> persist to Postgres -> write Ring/
    MEMBER_OF_RING to Neo4j -> audit event

PostgreSQL remains authoritative for the persisted ring records; Neo4j's
Ring/MEMBER_OF_RING nodes are a derived view of the same result, rebuildable
by re-running this module against an unchanged graph (same ring_id, same
feature values - see app/db/models/rings.py's module docstring).
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from neo4j import Driver
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.audit.service import append_audit_event
from app.core.logging_config import get_logger
from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.rings import DetectedRing, DetectedRingComplaint, DetectedRingMember
from app.db.models.transactions import Transaction
from app.graph.schemas import RingSummary
from app.db.neo4j_client import get_driver
from app.graph import community_detection, projection
from app.graph.geo import haversine_km

logger = get_logger(__name__)


def compute_ring_id(member_hashes: frozenset[str], algorithm_name: str, algorithm_version: str) -> str:
    """Deterministic: identical membership + algorithm + version always
    produces the identical ring_id (app/db/models/rings.py's module
    docstring explains why this matters)."""
    canonical = "|".join(sorted(member_hashes)) + f"|{algorithm_name}|{algorithm_version}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _geographic_spread_km(db: Session, member_hashes: frozenset[str]) -> Optional[float]:
    accounts = db.query(Account).filter(Account.account_hash.in_(member_hashes)).all()
    coords = [
        (a.branch_lat, a.branch_lon) for a in accounts if a.branch_lat is not None and a.branch_lon is not None
    ]
    if len(coords) < 2:
        return None
    max_distance = 0.0
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            max_distance = max(max_distance, haversine_km(*coords[i], *coords[j]))
    return max_distance


def _associated_complaint_ids(db: Session, account_ids: list[str]) -> list[str]:
    """A ring is associated with a complaint when a member is that
    complaint's victim account, or appears in one of its transactions
    (docs/db/models/rings.py's DetectedRingComplaint docstring)."""
    via_victim = {
        row[0]
        for row in db.query(Complaint.complaint_id)
        .filter(Complaint.victim_account_id.in_(account_ids))
        .all()
    }
    via_transaction = {
        row[0]
        for row in db.query(Transaction.complaint_id)
        .filter(
            or_(Transaction.from_account_id.in_(account_ids), Transaction.to_account_id.in_(account_ids)),
            Transaction.complaint_id.isnot(None),
        )
        .distinct()
        .all()
    }
    return sorted(via_victim | via_transaction)


def _write_ring_to_neo4j(
    driver: Driver, ring_id: str, member_hashes: frozenset[str], cohesion_score: float, model_version: str
) -> None:
    with driver.session() as session:
        session.run(
            "MERGE (r:Ring {ring_id: $ring_id}) SET r.detected_at = $detected_at, r.model_version = $version",
            ring_id=ring_id,
            detected_at=datetime.now(timezone.utc).isoformat(),
            version=model_version,
        )
        for account_hash in member_hashes:
            session.run(
                "MATCH (a:Account {account_hash: $account_hash}) "
                "MATCH (r:Ring {ring_id: $ring_id}) "
                "MERGE (a)-[m:MEMBER_OF_RING]->(r) "
                "SET m.cohesion_score = $cohesion_score",
                account_hash=account_hash,
                ring_id=ring_id,
                cohesion_score=cohesion_score,
            )


def _persist_ring(
    db: Session, ring_id: str, features: dict, member_account_ids: list[str], complaint_ids: list[str],
    fingerprint: str, algorithm_name: str, algorithm_version: str,
) -> DetectedRing:
    suspiciousness_features = {
        "cohesion_score": {
            "value": features["cohesion_score"],
            "formula": "internal_edge_weight_sum / (n*(n-1)/2)",
        },
        "entity_sharing_density": {
            "value": features["entity_sharing_density"],
            "formula": "internal_shares_edges / (n*(n-1)/2)",
        },
        "fan_in_to_fan_out_amount_ratio": {
            "value": features["fan_in_to_fan_out_amount_ratio"],
            "formula": "fan_in_amount / fan_out_amount",
        },
        "transaction_velocity": {
            "value": features["transaction_velocity"],
            "formula": "internal_transaction_count / hours_spanned",
        },
        "burst_ratio": {
            "value": features["burst_ratio"],
            "formula": "max(transactions in any 1-hour bucket) / total_internal_transactions",
        },
        "exit_concentration": {
            "value": features["exit_concentration"],
            "formula": "1 - (distinct_exit_channels / total_exit_edges)",
        },
        "geographic_spread_km": {
            "value": features["geographic_spread_km"],
            "formula": "max pairwise Haversine distance among members with known coordinates",
        },
    }

    ring = db.query(DetectedRing).filter(DetectedRing.ring_id == ring_id).first()
    if ring is None:
        ring = DetectedRing(ring_id=ring_id)
        db.add(ring)

    # member_count must equal what's actually persisted in detected_ring_members,
    # not the raw Neo4j graph community size (features["member_count"]) - a
    # community can include account_hashes with no matching Postgres accounts
    # row (e.g. historical Neo4j-only test contamination), in which case those
    # two numbers silently diverged before this fix, misrepresenting the ring
    # to anything reading detected_rings without cross-checking detected_ring_members.
    resolved_member_count = len(member_account_ids)
    if resolved_member_count != features["member_count"]:
        logger.warning(
            "ring_detection.member_count_mismatch",
            extra={
                "extra_fields": {
                    "ring_id": ring_id,
                    "graph_member_count": features["member_count"],
                    "resolved_postgres_member_count": resolved_member_count,
                }
            },
        )

    ring.detected_at = datetime.now(timezone.utc)
    ring.algorithm_name = algorithm_name
    ring.algorithm_version = algorithm_version
    ring.source_graph_fingerprint = fingerprint
    ring.member_count = resolved_member_count
    ring.transaction_count = features["transaction_count"]
    ring.total_amount = features["total_amount"]
    ring.average_transaction_amount = features["average_transaction_amount"]
    ring.transaction_velocity = features["transaction_velocity"]
    ring.fan_in_count = features["fan_in_count"]
    ring.fan_out_count = features["fan_out_count"]
    ring.fan_in_amount = features["fan_in_amount"]
    ring.fan_out_amount = features["fan_out_amount"]
    ring.device_count = features["device_count"]
    ring.ip_count = features["ip_count"]
    ring.phone_count = features["phone_count"]
    ring.vpa_count = features["vpa_count"]
    ring.geographic_spread_km = features["geographic_spread_km"]
    ring.burst_ratio = features["burst_ratio"]
    ring.cohesion_score = features["cohesion_score"]
    ring.exit_channel_ids = features["exit_channel_ids"]
    ring.suspiciousness_features = suspiciousness_features
    ring.is_synthetic = True
    db.flush()

    db.query(DetectedRingMember).filter(DetectedRingMember.ring_id == ring_id).delete()
    for account_id in member_account_ids:
        db.add(DetectedRingMember(ring_id=ring_id, account_id=account_id))

    db.query(DetectedRingComplaint).filter(DetectedRingComplaint.ring_id == ring_id).delete()
    for complaint_id in complaint_ids:
        db.add(DetectedRingComplaint(ring_id=ring_id, complaint_id=complaint_id))

    db.flush()
    return ring


def get_rings_for_complaint(db: Session, complaint_id: str) -> list[RingSummary]:
    """Investigator-facing read - API_CONTRACT.md's locked `rings` array,
    served via GET /v1/complaints/{complaint_id}/rings. Never touches
    accounts.ring_id (the synthetic ground truth)."""
    ring_ids = [
        row[0]
        for row in db.query(DetectedRingComplaint.ring_id)
        .filter(DetectedRingComplaint.complaint_id == complaint_id)
        .all()
    ]
    if not ring_ids:
        return []

    rings = db.query(DetectedRing).filter(DetectedRing.ring_id.in_(ring_ids)).all()
    summaries = []
    for ring in rings:
        member_account_ids = [
            row[0]
            for row in db.query(DetectedRingMember.account_id)
            .filter(DetectedRingMember.ring_id == ring.ring_id)
            .all()
        ]
        summaries.append(
            RingSummary(
                ring_id=ring.ring_id,
                detected_at=ring.detected_at,
                algorithm_name=ring.algorithm_name,
                algorithm_version=ring.algorithm_version,
                member_count=ring.member_count,
                member_account_ids=member_account_ids,
                transaction_count=ring.transaction_count,
                total_amount=ring.total_amount,
                average_transaction_amount=ring.average_transaction_amount,
                transaction_velocity=ring.transaction_velocity,
                burst_ratio=ring.burst_ratio,
                fan_in_count=ring.fan_in_count,
                fan_out_count=ring.fan_out_count,
                fan_in_amount=ring.fan_in_amount,
                fan_out_amount=ring.fan_out_amount,
                device_count=ring.device_count,
                ip_count=ring.ip_count,
                phone_count=ring.phone_count,
                vpa_count=ring.vpa_count,
                geographic_spread_km=ring.geographic_spread_km,
                cohesion_score=ring.cohesion_score,
                exit_channel_ids=ring.exit_channel_ids or [],
            )
        )
    return summaries


def run_ring_detection(db: Session, driver: Optional[Driver] = None) -> dict:
    """The full pipeline. Returns a summary dict (never includes the
    synthetic ground truth - app/graph/evaluation.py is the only module
    allowed to touch accounts.ring_id, and it's never called from here)."""
    driver = driver or get_driver()
    if driver is None:
        raise RuntimeError("Neo4j is not reachable - cannot run ring detection")

    projection.materialize_shared_entity_edges(driver)
    graph = projection.build_account_projection(driver)
    fingerprint = projection.graph_fingerprint(graph)

    communities = community_detection.run_louvain(graph)
    modularity = community_detection.partition_modularity(graph, communities)
    algo_version = community_detection.algorithm_version()

    ring_summaries = []
    for member_hashes in communities:
        features = community_detection.compute_neo4j_features(member_hashes, graph, driver)
        features["geographic_spread_km"] = _geographic_spread_km(db, member_hashes)

        ring_id = compute_ring_id(member_hashes, community_detection.ALGORITHM_NAME, algo_version)

        member_accounts = db.query(Account).filter(Account.account_hash.in_(member_hashes)).all()
        member_account_ids = [a.account_id for a in member_accounts]
        complaint_ids = _associated_complaint_ids(db, member_account_ids)

        _persist_ring(
            db, ring_id, features, member_account_ids, complaint_ids, fingerprint,
            community_detection.ALGORITHM_NAME, algo_version,
        )
        append_audit_event(
            db,
            event_type="ring.detected",
            subject_type="ring",
            subject_id=ring_id,
            payload={
                # The resolved (persisted) count, not the raw graph community
                # size - must match detected_rings.member_count exactly, or
                # the audit trail would repeat the same inconsistency this
                # fix removes from the table itself.
                "member_count": len(member_account_ids),
                "transaction_count": features["transaction_count"],
                "cohesion_score": features["cohesion_score"],
                "algorithm": f"{community_detection.ALGORITHM_NAME}:{algo_version}",
            },
        )
        # PostgreSQL is the authoritative system of record (docs/ARCHITECTURE.md:
        # "Neo4j is a derived/rebuildable intelligence graph") - committed here,
        # per ring, *before* the Neo4j write, not batched at the end of the
        # loop. This ordering is the fix for a real incident: a Postgres-side
        # failure (audit_events.subject_id was too narrow for a 64-char
        # ring_id) used to be raised *after* `_write_ring_to_neo4j` had
        # already committed on its own independent connection, leaving a
        # Neo4j Ring node with no backing Postgres row. Committing first
        # means a Postgres failure never reaches the Neo4j write at all - no
        # orphan is possible on that path, and an earlier ring in the same
        # detection run is never rolled back by a later ring's failure.
        db.commit()

        try:
            _write_ring_to_neo4j(driver, ring_id, member_hashes, features["cohesion_score"], algo_version)
        except Exception as exc:
            # Postgres already holds the authoritative, committed record for
            # this ring. A Neo4j failure here leaves Neo4j momentarily behind
            # Postgres, never the reverse - and it self-heals: ring_id is
            # deterministic and this write MERGEs, so the next detection run
            # safely re-creates exactly this node, no duplicate-write risk.
            logger.warning(
                "ring_detection.neo4j_write_failed",
                extra={"extra_fields": {"ring_id": ring_id, "error": str(exc)}},
            )

        ring_summaries.append(
            {
                "ring_id": ring_id,
                "member_count": len(member_account_ids),  # resolved count, consistent with detected_rings
                "member_account_ids": member_account_ids,
                "cohesion_score": features["cohesion_score"],
                "complaint_ids": complaint_ids,
            }
        )

    logger.info(
        "ring_detection.completed",
        extra={
            "extra_fields": {
                "graph_nodes": graph.number_of_nodes(),
                "graph_edges": graph.number_of_edges(),
                "communities_detected": len(communities),
                "modularity": modularity,
            }
        },
    )

    return {
        "graph_nodes": graph.number_of_nodes(),
        "graph_edges": graph.number_of_edges(),
        "communities_detected": len(communities),
        "modularity": modularity,
        "algorithm": f"{community_detection.ALGORITHM_NAME}:{algo_version}",
        "source_graph_fingerprint": fingerprint,
        "rings": ring_summaries,
    }
