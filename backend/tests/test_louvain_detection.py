"""
Pure Louvain-algorithm tests against hand-built NetworkX graphs - no Neo4j
dependency, since `run_louvain`/`partition_modularity`
(app/graph/community_detection.py) operate on an already-built graph object.
docs/AI_ML_ARCHITECTURE.md §2's "Do NOT implement a GNN" / "Do NOT describe
Louvain as neural-network inference" is enforced structurally here too: this
module never imports torch or any neural-network library, and the docstrings
throughout app/graph/ call it exactly what it is.
"""
import networkx as nx

from app.graph.community_detection import (
    ALGORITHM_NAME,
    algorithm_version,
    partition_modularity,
    run_louvain,
)


def test_algorithm_is_named_louvain_not_a_neural_network():
    assert ALGORITHM_NAME == "louvain"
    assert "networkx" in algorithm_version()
    assert "gnn" not in algorithm_version().lower()
    assert "neural" not in algorithm_version().lower()


def test_louvain_recovers_two_disjoint_cliques():
    graph = nx.Graph()
    # Two tight 4-node cliques, connected by nothing.
    clique_a = ["a1", "a2", "a3", "a4"]
    clique_b = ["b1", "b2", "b3", "b4"]
    for nodes in (clique_a, clique_b):
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                graph.add_edge(nodes[i], nodes[j], weight=10)

    communities = run_louvain(graph, seed=42)
    assert len(communities) == 2
    found_sets = {frozenset(c) for c in communities}
    assert frozenset(clique_a) in found_sets
    assert frozenset(clique_b) in found_sets


def test_louvain_is_deterministic_with_a_fixed_seed():
    graph = nx.Graph()
    for i in range(20):
        graph.add_edge(f"n{i}", f"n{(i + 1) % 20}", weight=(i % 5) + 1)
        graph.add_edge(f"n{i}", f"n{(i + 7) % 20}", weight=(i % 3) + 1)

    first = run_louvain(graph, seed=42)
    second = run_louvain(graph, seed=42)
    assert first == second  # frozensets, order-independent equality


def test_louvain_filters_out_singleton_communities():
    graph = nx.Graph()
    graph.add_edge("a1", "a2", weight=10)
    graph.add_edge("a2", "a3", weight=10)
    graph.add_node("isolated")  # no edges at all

    communities = run_louvain(graph, seed=42)
    all_members = {member for community in communities for member in community}
    assert "isolated" not in all_members
    assert all(len(c) >= 2 for c in communities)


def test_louvain_returns_empty_for_graph_below_minimum_size():
    empty_graph = nx.Graph()
    assert run_louvain(empty_graph) == []

    single_node = nx.Graph()
    single_node.add_node("a1")
    assert run_louvain(single_node) == []

    no_edges = nx.Graph()
    no_edges.add_node("a1")
    no_edges.add_node("a2")
    assert run_louvain(no_edges) == []


def test_background_noise_does_not_merge_into_a_genuine_tight_cluster():
    """A genuine ring (dense, high-weight internal connections) plus
    separate pairs connected only by single weak (weight=1) edges - the kind
    of coincidental single shared-IP link that's common between unrelated
    accounts (AI_ML_ARCHITECTURE.md §2a's documented reasoning for IP's
    lower weight). The weak background pairs must not be absorbed into the
    genuine cluster."""
    graph = nx.Graph()
    ring = ["r1", "r2", "r3", "r4"]
    for i in range(len(ring)):
        for j in range(i + 1, len(ring)):
            graph.add_edge(ring[i], ring[j], weight=10)

    # Unrelated background pairs, each a single weak coincidental link.
    graph.add_edge("noise1", "noise2", weight=1)
    graph.add_edge("noise3", "noise4", weight=1)
    # One weak link *from* the background into the ring - should not be
    # enough to pull a background node into the tight cluster.
    graph.add_edge("noise1", "r1", weight=1)

    communities = run_louvain(graph, seed=42)
    ring_community = next((c for c in communities if set(ring).issubset(c)), None)
    assert ring_community is not None, "the genuine tight cluster was not recovered as its own community"
    assert "noise1" not in ring_community, "a single weak coincidental edge merged unrelated noise into the ring"


def test_partition_modularity_is_none_for_no_communities():
    graph = nx.Graph()
    assert partition_modularity(graph, []) is None


def test_partition_modularity_returns_a_real_value_for_a_clear_partition():
    graph = nx.Graph()
    clique_a, clique_b = ["a1", "a2", "a3"], ["b1", "b2", "b3"]
    for nodes in (clique_a, clique_b):
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                graph.add_edge(nodes[i], nodes[j], weight=5)

    communities = run_louvain(graph, seed=42)
    modularity = partition_modularity(graph, communities)
    assert modularity is not None
    assert modularity > 0  # a real, well-separated partition should score positively
