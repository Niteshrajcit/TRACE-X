"""
Louvain execution and Neo4j-derived feature computation -
docs/AI_ML_ARCHITECTURE.md §2/§2a/§2b. Community IDs, membership, and every
feature here come from running the algorithm and querying the graph - none
of it is a GNN, and none of it is described as neural-network inference
anywhere in this module or its docs.
"""
from datetime import datetime
from typing import Optional

import networkx as nx
from neo4j import Driver

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.neo4j_client import get_driver

logger = get_logger(__name__)
settings = get_settings()

ALGORITHM_NAME = "louvain"


def algorithm_version() -> str:
    """The detection algorithm's version is NetworkX's own version string -
    Louvain here is exactly `networkx.algorithms.community.louvain_communities`,
    not a custom reimplementation, so its version is the honest answer to
    "algorithm_version" (docs/DATA_MODEL.md §2's Phase 2B addition)."""
    return f"networkx-{nx.__version__}"


def run_louvain(graph: nx.Graph, seed: Optional[int] = None) -> list[frozenset[str]]:
    """docs/AI_ML_ARCHITECTURE.md §2a: minimum 2 nodes and 1 edge to run at
    all; singleton communities (an account Louvain couldn't attach to
    anything, or a graph too small to partition) are filtered out - a ring
    has >=2 members by definition. Deterministic given a fixed seed and a
    deterministically-constructed input graph (app/graph/projection.py)."""
    if graph.number_of_nodes() < 2 or graph.number_of_edges() < 1:
        return []

    seed = seed if seed is not None else settings.louvain_random_seed
    raw_communities = nx.algorithms.community.louvain_communities(graph, seed=seed, weight="weight")
    return [frozenset(c) for c in raw_communities if len(c) >= 2]


def partition_modularity(graph: nx.Graph, communities: list[frozenset[str]]) -> Optional[float]:
    """docs/AI_ML_ARCHITECTURE.md §2's "modularity score as an unsupervised
    sanity check" - a property of the whole partition, not any one ring, so
    it's reported by the caller (app/graph/ring_service.py) alongside the
    detection run's summary, not persisted per-ring."""
    if not communities:
        return None
    # Louvain filters out singletons before this is called; modularity still
    # needs every node accounted for, so add back any node Louvain excluded
    # as its own singleton community (this is exactly what "filtered out"
    # means - it doesn't remove the node from the graph, only from the
    # persisted ring list).
    covered = {node for community in communities for node in community}
    singletons = [frozenset({node}) for node in graph.nodes() if node not in covered]
    return nx.algorithms.community.quality.modularity(graph, communities + singletons, weight="weight")


def compute_neo4j_features(
    member_hashes: frozenset[str], graph: nx.Graph, driver: Optional[Driver] = None
) -> dict:
    """Everything computable from Neo4j plus the projection graph itself -
    geographic_spread_km (needs Postgres account coordinates) is added
    separately by app/graph/ring_service.py, which has both a DB session
    and this function's output available."""
    driver = driver or get_driver()
    if driver is None:
        raise RuntimeError("Neo4j is not reachable - cannot compute ring features")

    members = list(member_hashes)
    n = len(members)

    with driver.session() as session:
        txn_stats = session.run(
            """
            MATCH (a:Account)-[t:TRANSFERRED_TO]->(b:Account)
            WHERE a.account_hash IN $members AND b.account_hash IN $members
            RETURN count(t) AS txn_count, sum(toFloat(t.amount)) AS total_amount,
                   collect(t.occurred_at) AS occurred_at_values
            """,
            members=members,
        ).single()

        fan_in = session.run(
            """
            MATCH (outsider:Account)-[t:TRANSFERRED_TO]->(member:Account)
            WHERE member.account_hash IN $members AND NOT outsider.account_hash IN $members
            RETURN count(t) AS fan_in_count, coalesce(sum(toFloat(t.amount)), 0.0) AS fan_in_amount
            """,
            members=members,
        ).single()

        fan_out = session.run(
            """
            MATCH (member:Account)-[t:TRANSFERRED_TO]->(outsider:Account)
            WHERE member.account_hash IN $members AND NOT outsider.account_hash IN $members
            RETURN count(t) AS fan_out_count, coalesce(sum(toFloat(t.amount)), 0.0) AS fan_out_amount
            """,
            members=members,
        ).single()

        entity_counts = {}
        for label, has_rel in [("device", "HAS_DEVICE"), ("phone", "HAS_PHONE"), ("ip", "HAS_IP"), ("vpa", "HAS_VPA")]:
            result = session.run(
                f"""
                MATCH (a:Account)-[:{has_rel}]->(e)
                WHERE a.account_hash IN $members
                RETURN count(DISTINCT e) AS entity_count
                """,
                members=members,
            ).single()
            entity_counts[label] = result["entity_count"]

        internal_shares = session.run(
            """
            MATCH (a:Account)-[r:SHARES_DEVICE_WITH|SHARES_PHONE_WITH|SHARES_IP_WITH|SHARES_VPA_WITH]->(b:Account)
            WHERE a.account_hash IN $members AND b.account_hash IN $members
            RETURN count(r) AS shared_entity_edges
            """,
            members=members,
        ).single()["shared_entity_edges"]

        exit_info = session.run(
            """
            MATCH (a:Account)-[:EXITED_VIA]->(e:ExitChannel)
            WHERE a.account_hash IN $members
            RETURN collect(DISTINCT e.channel_id) AS exit_channel_ids, count(*) AS exit_edge_count
            """,
            members=members,
        ).single()

    txn_count = txn_stats["txn_count"] or 0
    total_amount = txn_stats["total_amount"] or 0.0
    average_amount = (total_amount / txn_count) if txn_count else None

    occurred_at_values = [v for v in txn_stats["occurred_at_values"] if v]
    velocity, burst_ratio = _time_features(occurred_at_values)

    possible_pairs = (n * (n - 1)) / 2 if n > 1 else 0
    internal_weight = sum(
        data["weight"] for u, v, data in graph.edges(members, data=True) if v in member_hashes
    )
    cohesion_score = (internal_weight / possible_pairs) if possible_pairs else 0.0
    entity_sharing_density = (internal_shares / possible_pairs) if possible_pairs else 0.0

    exit_channel_ids = exit_info["exit_channel_ids"] or []
    exit_edge_count = exit_info["exit_edge_count"] or 0
    exit_concentration = (
        1 - (len(exit_channel_ids) / exit_edge_count) if exit_edge_count else None
    )

    fan_in_amount = fan_in["fan_in_amount"] or 0.0
    fan_out_amount = fan_out["fan_out_amount"] or 0.0
    fan_in_to_fan_out_ratio = (fan_in_amount / fan_out_amount) if fan_out_amount else None

    return {
        "member_count": n,
        "transaction_count": txn_count,
        "total_amount": total_amount,
        "average_transaction_amount": average_amount,
        "transaction_velocity": velocity,
        "burst_ratio": burst_ratio,
        "fan_in_count": fan_in["fan_in_count"] or 0,
        "fan_out_count": fan_out["fan_out_count"] or 0,
        "fan_in_amount": fan_in_amount,
        "fan_out_amount": fan_out_amount,
        "fan_in_to_fan_out_amount_ratio": fan_in_to_fan_out_ratio,
        "device_count": entity_counts["device"],
        "ip_count": entity_counts["ip"],
        "phone_count": entity_counts["phone"],
        "vpa_count": entity_counts["vpa"],
        "entity_sharing_density": entity_sharing_density,
        "cohesion_score": cohesion_score,
        "exit_channel_ids": sorted(exit_channel_ids),
        "exit_concentration": exit_concentration,
    }


def _time_features(occurred_at_values: list[str]) -> tuple[Optional[float], Optional[float]]:
    """docs/AI_ML_ARCHITECTURE.md §2a: velocity and burst_ratio, both null
    (not a fabricated divide-by-zero guard) when the data can't support a
    real rate."""
    if len(occurred_at_values) < 2:
        return None, None

    timestamps = sorted(datetime.fromisoformat(v) for v in occurred_at_values)
    span_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0
    velocity = (len(timestamps) / span_hours) if span_hours > 0 else None

    buckets: dict[str, int] = {}
    for ts in timestamps:
        bucket_key = ts.strftime("%Y-%m-%dT%H")
        buckets[bucket_key] = buckets.get(bucket_key, 0) + 1
    burst_ratio = max(buckets.values()) / len(timestamps) if buckets else None

    return velocity, burst_ratio
