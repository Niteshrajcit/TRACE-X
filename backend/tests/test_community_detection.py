"""
Pure unit tests for app/graph/community_detection.py's Louvain wrapper and
app/graph/ring_service.py's ring_id hashing - docs/AI_ML_ARCHITECTURE.md
§2a's minimum-size/singleton-filtering/determinism rules and §DATA_MODEL.md
§2's deterministic-ring_id contract. No Neo4j, no Postgres, no HTTP - these
exercise the graph-theory and hashing logic directly against an in-memory
networkx.Graph, so they run everywhere (including with no Docker at all)
and fail fast on a logic regression without needing live infrastructure to
even notice.
"""
import networkx as nx

from app.graph import community_detection
from app.graph.ring_service import compute_ring_id


def _weighted_graph(edges: dict[tuple[str, str], float]) -> nx.Graph:
    g = nx.Graph()
    for (u, v), weight in edges.items():
        g.add_edge(u, v, weight=weight)
    return g


def test_run_louvain_returns_empty_below_minimum_graph_size():
    # A single node, no edges - below "≥2 nodes and ≥1 edge" (§2a).
    g = nx.Graph()
    g.add_node("solo")
    assert community_detection.run_louvain(g, seed=42) == []

    assert community_detection.run_louvain(nx.Graph(), seed=42) == []


def test_run_louvain_filters_out_singleton_communities():
    # Two tightly-connected pairs plus one isolated-but-present node with no
    # edges of its own weight to attach to any pair - Louvain may still
    # place it in a trivial community of size 1, which must be filtered
    # before the caller ever sees it (a ring has >=2 members by definition).
    g = _weighted_graph({("a", "b"): 5.0, ("c", "d"): 5.0})
    g.add_node("solo")  # isolated node, zero edges
    communities = community_detection.run_louvain(g, seed=42)
    assert all(len(c) >= 2 for c in communities)
    covered = {node for c in communities for node in c}
    assert "solo" not in covered


def test_run_louvain_separates_two_disconnected_dense_clusters():
    # Two disjoint tightly-connected triangles with no edges between them -
    # Louvain cannot merge disconnected components (the same structural
    # guarantee test_ring_detection_integration.py relies on for planted,
    # isolated mule rings), so this must always yield exactly two
    # communities, one per triangle, regardless of Louvain's internal
    # tie-breaking.
    g = _weighted_graph(
        {
            ("a1", "a2"): 3.0, ("a2", "a3"): 3.0, ("a1", "a3"): 3.0,
            ("b1", "b2"): 3.0, ("b2", "b3"): 3.0, ("b1", "b3"): 3.0,
        }
    )
    communities = community_detection.run_louvain(g, seed=42)
    assert len(communities) == 2
    triangle_a, triangle_b = {"a1", "a2", "a3"}, {"b1", "b2", "b3"}
    found = {frozenset(c) for c in communities}
    assert frozenset(triangle_a) in found
    assert frozenset(triangle_b) in found


def test_run_louvain_is_deterministic_for_a_fixed_seed():
    g = _weighted_graph(
        {
            ("a1", "a2"): 3.0, ("a2", "a3"): 3.0, ("a1", "a3"): 3.0,
            ("b1", "b2"): 3.0, ("b2", "b3"): 3.0, ("b1", "b3"): 3.0,
            ("a3", "b1"): 0.5,  # a weak cross-cluster edge, not enough to merge them
        }
    )
    first = community_detection.run_louvain(g, seed=42)
    second = community_detection.run_louvain(g, seed=42)
    assert {frozenset(c) for c in first} == {frozenset(c) for c in second}


def test_partition_modularity_is_none_for_no_communities():
    assert community_detection.partition_modularity(nx.Graph(), []) is None


def test_partition_modularity_accounts_for_every_node_including_uncovered_singletons():
    # partition_modularity must not crash or silently under-count when the
    # communities list (post-filtering) doesn't cover every node in the
    # graph - the docstring is explicit that singletons get added back as
    # their own trivial community rather than dropped from the calculation.
    g = _weighted_graph({("a", "b"): 5.0})
    g.add_node("uncovered")
    modularity = community_detection.partition_modularity(g, [frozenset({"a", "b"})])
    assert modularity is not None
    assert isinstance(modularity, float)


def test_algorithm_version_matches_networkx_and_is_stable():
    version = community_detection.algorithm_version()
    assert version == f"networkx-{nx.__version__}"
    assert community_detection.algorithm_version() == version  # stable across calls


def test_compute_ring_id_is_deterministic_for_identical_membership_and_algorithm():
    members = frozenset({"hash-a", "hash-b", "hash-c"})
    first = compute_ring_id(members, "louvain", "networkx-3.6.1")
    second = compute_ring_id(members, "louvain", "networkx-3.6.1")
    assert first == second


def test_compute_ring_id_is_independent_of_member_set_iteration_order():
    # frozenset iteration order is not insertion order - the ring_id must be
    # computed from a canonical (sorted) form, not whatever order the set
    # happens to iterate in, or the "same membership -> same ring_id"
    # contract (app/db/models/rings.py) would be unreliable in practice.
    a = compute_ring_id(frozenset({"z-hash", "a-hash", "m-hash"}), "louvain", "networkx-3.6.1")
    b = compute_ring_id(frozenset({"m-hash", "z-hash", "a-hash"}), "louvain", "networkx-3.6.1")
    assert a == b


def test_compute_ring_id_differs_for_different_membership():
    a = compute_ring_id(frozenset({"hash-a", "hash-b"}), "louvain", "networkx-3.6.1")
    b = compute_ring_id(frozenset({"hash-a", "hash-c"}), "louvain", "networkx-3.6.1")
    assert a != b


def test_compute_ring_id_differs_for_different_algorithm_or_version():
    members = frozenset({"hash-a", "hash-b"})
    base = compute_ring_id(members, "louvain", "networkx-3.6.1")
    different_version = compute_ring_id(members, "louvain", "networkx-3.6.2")
    different_algorithm = compute_ring_id(members, "label_propagation", "networkx-3.6.1")
    assert base != different_version
    assert base != different_algorithm
