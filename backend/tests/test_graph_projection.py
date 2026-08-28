"""
docs/AI_ML_ARCHITECTURE.md §2a, against real Neo4j. The projection is
GLOBAL (runs over the whole graph, by design - see §2a's "Scope" row), so
these tests never assert exact whole-graph node/edge counts (the shared
instance may hold other tests' or seeded data) - they check the *induced
subgraph* on this test's own uniquely-tagged accounts instead, which is
correct regardless of what else exists in the graph.
"""
import pytest

from app.core.security import hash_pii
from app.db.neo4j_client import check_connectivity, get_driver
from app.graph.projection import build_account_projection, graph_fingerprint, materialize_shared_entity_edges
from tests.conftest import auth_headers, service_token, valid_transaction_payload

pytestmark = pytest.mark.skipif(
    not check_connectivity(), reason="Neo4j not reachable - skipping real-graph tests"
)


def _run(query, **params):
    driver = get_driver()
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def _cleanup(complaint_id, account_numbers):
    hashes = [hash_pii(n) for n in account_numbers]
    _run(
        "MATCH (n) WHERE n.complaint_id = $cid OR n.account_hash IN $hashes DETACH DELETE n",
        cid=complaint_id, hashes=hashes,
    )


def _submit_complaint(client, victim_account_number, jurisdiction_hint="Chennai"):
    from tests.conftest import valid_complaint_payload

    response = client.post(
        "/v1/complaints",
        json=valid_complaint_payload(jurisdiction_hint=jurisdiction_hint, victim_account_number=victim_account_number),
    )
    assert response.status_code == 201
    return response.json()["complaint_id"]


def test_repeated_transactions_are_additive_in_edge_weight(client, graph_prefix):
    a, b = f"{graph_prefix}-a", f"{graph_prefix}-b"
    complaint_id = _submit_complaint(client, a)
    try:
        for _ in range(3):  # three separate transfers between the same two accounts
            resp = client.post(
                "/v1/transactions/ingest",
                json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=a, to_account_number=b),
                headers=auth_headers(service_token()),
            )
            assert resp.status_code == 202

        graph = build_account_projection()
        weight = graph[hash_pii(a)][hash_pii(b)]["weight"]
        assert weight == 3  # additive, not deduplicated to 1 (AI_ML_ARCHITECTURE.md §2a)
    finally:
        _cleanup(complaint_id, [a, b])


def test_shared_device_edge_is_materialized_and_weighted(client, graph_prefix):
    a, b, c = f"{graph_prefix}-sda", f"{graph_prefix}-sdb", f"{graph_prefix}-sdc"
    complaint_id = _submit_complaint(client, a)
    shared_device = f"{graph_prefix}-device"
    try:
        # a and b both transact using the same device; c is unrelated.
        client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(
                complaint_id=complaint_id, from_account_number=a, to_account_number=c, device_id=shared_device
            ),
            headers=auth_headers(service_token()),
        )
        client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(
                complaint_id=complaint_id, from_account_number=b, to_account_number=c, device_id=shared_device
            ),
            headers=auth_headers(service_token()),
        )

        materialize_shared_entity_edges()
        # Undirected pattern deliberately: materialize_shared_entity_edges()
        # canonicalizes direction via account_hash ordering (whichever of a/b
        # sorts first), which this test must not assume - it verifies the
        # relationship exists between the two accounts, not which direction
        # it happened to be written in.
        shares = _run(
            "MATCH (x:Account {account_hash: $ah})-[r:SHARES_DEVICE_WITH]-(y:Account {account_hash: $bh}) "
            "RETURN r.shared_count AS cnt",
            ah=hash_pii(a), bh=hash_pii(b),
        )
        assert len(shares) == 1
        assert shares[0]["cnt"] == 1

        graph = build_account_projection()
        # weight(a,b) = 2 (device coefficient) * 1 (shared device count) = 2
        # a and b never transacted directly, so this weight comes entirely
        # from the shared-device signal.
        assert graph[hash_pii(a)][hash_pii(b)]["weight"] == 2
    finally:
        _cleanup(complaint_id, [a, b, c])
        _run("MATCH (d:Device {device_hash: $h}) DETACH DELETE d", h=hash_pii(shared_device))


def test_ip_sharing_is_weighted_lower_than_device_sharing(client, graph_prefix):
    """AI_ML_ARCHITECTURE.md §2a: IP gets 1x, device gets 2x - a documented,
    reasoned difference, not an arbitrary one."""
    a, b, c = f"{graph_prefix}-ipa", f"{graph_prefix}-ipb", f"{graph_prefix}-ipc"
    complaint_id = _submit_complaint(client, a)
    shared_ip = f"{graph_prefix}-ip-addr"
    try:
        client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(
                complaint_id=complaint_id, from_account_number=a, to_account_number=c, ip_address=shared_ip
            ),
            headers=auth_headers(service_token()),
        )
        client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(
                complaint_id=complaint_id, from_account_number=b, to_account_number=c, ip_address=shared_ip
            ),
            headers=auth_headers(service_token()),
        )

        materialize_shared_entity_edges()
        graph = build_account_projection()
        assert graph[hash_pii(a)][hash_pii(b)]["weight"] == 1
    finally:
        _cleanup(complaint_id, [a, b, c])
        _run("MATCH (i:IP {ip_hash: $h}) DETACH DELETE i", h=hash_pii(shared_ip))


def test_projection_is_deterministic_across_repeated_builds(client, graph_prefix):
    a, b = f"{graph_prefix}-deta", f"{graph_prefix}-detb"
    complaint_id = _submit_complaint(client, a)
    try:
        client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=a, to_account_number=b),
            headers=auth_headers(service_token()),
        )

        first = build_account_projection()
        second = build_account_projection()
        assert graph_fingerprint(first) == graph_fingerprint(second)
    finally:
        _cleanup(complaint_id, [a, b])


def test_directed_transfer_becomes_a_single_undirected_edge(client, graph_prefix):
    a, b = f"{graph_prefix}-dira", f"{graph_prefix}-dirb"
    complaint_id = _submit_complaint(client, a)
    try:
        client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=a, to_account_number=b),
            headers=auth_headers(service_token()),
        )
        graph = build_account_projection()
        # networkx.Graph is inherently undirected - accessing either order
        # must return the same edge/weight.
        assert graph[hash_pii(a)][hash_pii(b)] == graph[hash_pii(b)][hash_pii(a)]
    finally:
        _cleanup(complaint_id, [a, b])
