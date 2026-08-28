"""
Graph projection for Louvain community detection - docs/AI_ML_ARCHITECTURE.md
§2a defines this precisely; this module implements it exactly as documented,
nothing more. Read that section before changing anything here.
"""
from typing import Optional

import networkx as nx
from neo4j import Driver

from app.core.logging_config import get_logger
from app.db.neo4j_client import get_driver

logger = get_logger(__name__)

# (Neo4j relationship type, weight coefficient) - coefficients and their
# reasoning are documented in AI_ML_ARCHITECTURE.md §2a, not re-derived here.
_SHARED_ENTITY_RELATIONSHIPS = [
    ("SHARES_DEVICE_WITH", 2),
    ("SHARES_PHONE_WITH", 2),
    ("SHARES_IP_WITH", 1),
    ("SHARES_VPA_WITH", 2),
]

# (HAS_* relationship, derived SHARES_*_WITH relationship) pairs used to
# materialize the shared-entity edges before projection.
_HAS_TO_SHARES = [
    ("HAS_DEVICE", "SHARES_DEVICE_WITH"),
    ("HAS_PHONE", "SHARES_PHONE_WITH"),
    ("HAS_IP", "SHARES_IP_WITH"),
    ("HAS_VPA", "SHARES_VPA_WITH"),
]


def materialize_shared_entity_edges(driver: Optional[Driver] = None) -> dict:
    """Computes and MERGEs SHARES_DEVICE_WITH/SHARES_PHONE_WITH/
    SHARES_IP_WITH/SHARES_VPA_WITH edges between every pair of accounts that
    share a Device/Phone/IP/VPA node - real, inspectable Neo4j relationships
    (not just an in-memory projection artifact), matching DATA_MODEL.md §3's
    original "derived from shared Device node" design. Idempotent: re-running
    recomputes `shared_count` in place rather than duplicating edges."""
    driver = driver or get_driver()
    if driver is None:
        raise RuntimeError("Neo4j is not reachable - cannot materialize shared-entity edges")

    counts = {}
    with driver.session() as session:
        for has_rel, shares_rel in _HAS_TO_SHARES:
            result = session.run(
                f"""
                MATCH (a:Account)-[:{has_rel}]->(e)<-[:{has_rel}]-(b:Account)
                WHERE a.account_hash < b.account_hash
                WITH a, b, count(DISTINCT e) AS shared_count
                MERGE (a)-[r:{shares_rel}]->(b)
                SET r.shared_count = shared_count
                RETURN count(*) AS pairs
                """
            )
            counts[shares_rel] = result.single()["pairs"]
    return counts


def build_account_projection(driver: Optional[Driver] = None) -> nx.Graph:
    """Builds the deterministic, undirected, weighted Account graph Louvain
    runs over. Call `materialize_shared_entity_edges` first (or via
    `app/graph/ring_service.py`'s orchestration, which always does both in
    order) so the SHARES_*_WITH edges this reads actually exist and reflect
    the current graph state.

    Determinism: every Cypher query orders its results explicitly (Neo4j
    gives no row-order guarantee otherwise), so nodes/edges are always
    inserted into the NetworkX graph in the same order for the same
    underlying data - Louvain's own determinism (a fixed seed,
    settings.louvain_random_seed) only holds if its *input* graph is built
    deterministically too.
    """
    driver = driver or get_driver()
    if driver is None:
        raise RuntimeError("Neo4j is not reachable - cannot build projection")

    graph = nx.Graph()

    with driver.session() as session:
        rows = session.run(
            """
            MATCH (a:Account)-[t:TRANSFERRED_TO]->(b:Account)
            WHERE a.account_hash <> b.account_hash
            RETURN a.account_hash AS from_hash, b.account_hash AS to_hash, count(t) AS txn_count
            ORDER BY from_hash, to_hash
            """
        )
        for record in rows:
            a, b = sorted([record["from_hash"], record["to_hash"]])
            existing = graph.get_edge_data(a, b, default={}).get("weight", 0)
            graph.add_edge(a, b, weight=existing + record["txn_count"])

        for shares_rel, coefficient in _SHARED_ENTITY_RELATIONSHIPS:
            rows = session.run(
                f"""
                MATCH (a:Account)-[r:{shares_rel}]->(b:Account)
                RETURN a.account_hash AS ah, b.account_hash AS bh, coalesce(r.shared_count, 1) AS cnt
                ORDER BY ah, bh
                """
            )
            for record in rows:
                a, b = sorted([record["ah"], record["bh"]])
                contribution = coefficient * record["cnt"]
                existing = graph.get_edge_data(a, b, default={}).get("weight", 0)
                graph.add_edge(a, b, weight=existing + contribution)

    logger.info(
        "graph.projection_built",
        extra={"extra_fields": {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges()}},
    )
    return graph


def graph_fingerprint(graph: nx.Graph) -> str:
    """A stable hash of the projection's structure - used as
    `detected_rings.source_graph_fingerprint` so "reproduce the result from
    the same graph input" is independently checkable: re-running detection
    against an unchanged graph must produce the identical fingerprint."""
    import hashlib

    edges = sorted(
        (u, v, graph[u][v]["weight"]) for u, v in graph.edges()
    )
    canonical = "|".join(f"{u}:{v}:{w}" for u, v, w in edges)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
