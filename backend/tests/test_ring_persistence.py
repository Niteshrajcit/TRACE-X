"""
docs/db/models/rings.py - persistence, and reproducibility ("the system
must be able to reproduce the result from the same graph input").
Ring detection is global, so these tests locate *their own* ring by
membership rather than asserting whole-graph counts.
"""
import pytest

from app.core.security import hash_pii
from app.db.models.accounts import Account
from app.db.models.rings import DetectedRing, DetectedRingComplaint, DetectedRingMember
from app.db.neo4j_client import check_connectivity, get_driver
from app.graph.ring_service import run_ring_detection
from tests.conftest import auth_headers, service_token, valid_complaint_payload, valid_transaction_payload

pytestmark = pytest.mark.skipif(
    not check_connectivity(), reason="Neo4j not reachable - skipping real-graph tests"
)


def _run(query, **params):
    driver = get_driver()
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def _cleanup(complaint_id, account_numbers, device=None):
    hashes = [hash_pii(n) for n in account_numbers]
    # Ring nodes are keyed by a content hash of member account hashes, not
    # by anything graph_prefix-taggable directly - deleting them via the
    # MEMBER_OF_RING relationship from the accounts we *do* know, before
    # those accounts are gone, is the only way to catch them here.
    _run(
        "MATCH (a:Account)-[:MEMBER_OF_RING]->(r:Ring) WHERE a.account_hash IN $hashes DETACH DELETE r",
        hashes=hashes,
    )
    _run(
        "MATCH (n) WHERE n.complaint_id = $cid OR n.account_hash IN $hashes DETACH DELETE n",
        cid=complaint_id, hashes=hashes,
    )
    if device:
        _run("MATCH (d:Device {device_hash: $h}) DETACH DELETE d", h=hash_pii(device))


def _submit_complaint(client, victim_account_number):
    response = client.post(
        "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai", victim_account_number=victim_account_number)
    )
    assert response.status_code == 201
    return response.json()["complaint_id"]


def _find_ring_containing(db, account_ids: set[str]) -> DetectedRing | None:
    for ring in db.query(DetectedRing).all():
        members = {
            row[0]
            for row in db.query(DetectedRingMember.account_id).filter(DetectedRingMember.ring_id == ring.ring_id).all()
        }
        if account_ids.issubset(members):
            return ring
    return None


def _build_detectable_pair(client, graph_prefix):
    """Two accounts, tightly connected (transaction + shared device) so
    they reliably land in one Louvain community together."""
    a, b, c = f"{graph_prefix}-pa", f"{graph_prefix}-pb", f"{graph_prefix}-pc"
    device = f"{graph_prefix}-shared-device"
    complaint_id = _submit_complaint(client, a)

    client.post(
        "/v1/transactions/ingest",
        json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=a, to_account_number=b, device_id=device),
        headers=auth_headers(service_token()),
    )
    client.post(
        "/v1/transactions/ingest",
        json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=b, to_account_number=c, device_id=device),
        headers=auth_headers(service_token()),
    )
    return complaint_id, (a, b, c), device


def test_ring_is_persisted_with_correct_features(client, db, graph_prefix):
    complaint_id, (a, b, c), device = _build_detectable_pair(client, graph_prefix)
    try:
        run_ring_detection(db)  # already triggered automatically by graph.updated, but explicit here for clarity

        accounts = db.query(Account).filter(Account.account_hash.in_([hash_pii(a), hash_pii(b), hash_pii(c)])).all()
        account_ids = {acc.account_id for acc in accounts}

        ring = _find_ring_containing(db, account_ids)
        assert ring is not None, "no persisted ring contains the test's own tightly-connected accounts"
        assert ring.transaction_count >= 2
        assert ring.algorithm_name == "louvain"
        assert "networkx" in ring.algorithm_version
        assert ring.device_count >= 1
        assert float(ring.cohesion_score) > 0

        # Complaint association (docs/db/models/rings.py: DetectedRingComplaint)
        linked_complaints = {
            row[0]
            for row in db.query(DetectedRingComplaint.complaint_id)
            .filter(DetectedRingComplaint.ring_id == ring.ring_id)
            .all()
        }
        assert complaint_id in linked_complaints
    finally:
        _cleanup(complaint_id, [a, b, c], device)


def test_ring_detection_is_reproducible_on_an_unchanged_graph(client, db, graph_prefix):
    complaint_id, (a, b, c), device = _build_detectable_pair(client, graph_prefix)
    try:
        first_summary = run_ring_detection(db)
        second_summary = run_ring_detection(db)

        assert first_summary["source_graph_fingerprint"] == second_summary["source_graph_fingerprint"]

        accounts = db.query(Account).filter(Account.account_hash.in_([hash_pii(a), hash_pii(b), hash_pii(c)])).all()
        account_ids = {acc.account_id for acc in accounts}
        ring = _find_ring_containing(db, account_ids)
        assert ring is not None

        # Exactly one row per ring_id - a second run must UPDATE in place,
        # never accumulate a duplicate record (app/db/models/rings.py's
        # module docstring).
        assert db.query(DetectedRing).filter(DetectedRing.ring_id == ring.ring_id).count() == 1
    finally:
        _cleanup(complaint_id, [a, b, c], device)


def test_ring_written_to_neo4j_matches_postgres(client, db, graph_prefix):
    complaint_id, (a, b, c), device = _build_detectable_pair(client, graph_prefix)
    try:
        run_ring_detection(db)

        accounts = db.query(Account).filter(Account.account_hash.in_([hash_pii(a), hash_pii(b), hash_pii(c)])).all()
        account_ids = {acc.account_id for acc in accounts}
        ring = _find_ring_containing(db, account_ids)
        assert ring is not None

        neo4j_rows = _run(
            "MATCH (r:Ring {ring_id: $ring_id}) "
            "MATCH (acc:Account)-[m:MEMBER_OF_RING]->(r) "
            "RETURN count(acc) AS member_count, r.model_version AS model_version",
            ring_id=ring.ring_id,
        )
        assert len(neo4j_rows) == 1
        assert neo4j_rows[0]["member_count"] == ring.member_count
        assert neo4j_rows[0]["model_version"] == ring.algorithm_version
    finally:
        _cleanup(complaint_id, [a, b, c], device)
