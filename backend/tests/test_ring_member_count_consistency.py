"""
Regression coverage for a real defect found during Phase 2B closure
verification: `DetectedRing.member_count` was set from the raw Neo4j
graph community size (`features["member_count"]`), while
`detected_ring_members` only ever got a row per account_hash that
actually resolved to a PostgreSQL `accounts` row. When a detected
community includes any account_hash with no matching Postgres row (the
concrete case found: historical Neo4j-only test contamination from
before this session's test-isolation fix), the two numbers silently
diverged - `member_count` claimed more members than `detected_ring_members`
actually listed, with no warning logged.

Fixed in app/graph/ring_service.py::_persist_ring: `member_count` is now
always `len(member_account_ids)` - the actually-persisted set - with a
warning logged whenever that differs from the graph's raw community size.
The audit event and returned summary dict were changed to match, so every
surface reporting a ring's member count agrees with what's actually in
detected_ring_members.

These three tests cover exactly the three resolution states named in the
fix: every graph member resolves to a Postgres account (full), some do
(partial - the same shape as the real historical bug), and none do (zero -
the exact shape of the real contaminated ring, `ff53e73...`, found during
the audit). Neo4j-only accounts are injected directly via
app.graph.builder.apply_transaction (bypassing the normal HTTP ingestion
path, which always creates the Postgres account alongside the graph node)
so the test can control resolution state precisely.
"""
import uuid

import pytest

from app.core.security import hash_pii
from app.db.models.rings import DetectedRing, DetectedRingMember
from app.db.neo4j_client import check_connectivity, get_driver
from app.graph.builder import apply_transaction
from app.graph.ring_service import run_ring_detection
from tests.conftest import auth_headers, service_token, valid_complaint_payload, valid_transaction_payload

pytestmark = pytest.mark.skipif(
    not check_connectivity(), reason="Neo4j not reachable - skipping real-graph tests"
)


def _run(query, **params):
    driver = get_driver()
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def _cleanup_hashes(hashes):
    _run("MATCH (a:Account) WHERE a.account_hash IN $hashes DETACH DELETE a", hashes=hashes)


def _cleanup_complaint(complaint_id, account_numbers):
    hashes = [hash_pii(n) for n in account_numbers]
    _run(
        "MATCH (a:Account)-[:MEMBER_OF_RING]->(r:Ring) WHERE a.account_hash IN $hashes DETACH DELETE r",
        hashes=hashes,
    )
    _run(
        "MATCH (n) WHERE n.complaint_id = $cid OR n.account_hash IN $hashes DETACH DELETE n",
        cid=complaint_id, hashes=hashes,
    )


def _submit_complaint(client, victim_account_number):
    response = client.post(
        "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai", victim_account_number=victim_account_number)
    )
    assert response.status_code == 201
    return response.json()["complaint_id"]


def _ring_for_ghost_pair(db, ghost_a: str, ghost_b: str) -> DetectedRing | None:
    """Locate the persisted ring by member_hashes rather than by querying
    detected_ring_members (which is exactly the table under test - looking
    it up that way here would be circular)."""
    from app.graph.ring_service import compute_ring_id
    from app.graph.community_detection import ALGORITHM_NAME, algorithm_version

    ring_id = compute_ring_id(frozenset({ghost_a, ghost_b}), ALGORITHM_NAME, algorithm_version())
    return db.query(DetectedRing).filter(DetectedRing.ring_id == ring_id).first()


def test_member_count_matches_full_postgres_resolution(client, db, graph_prefix):
    """Baseline: every graph member resolves to a real Postgres account -
    member_count must equal the graph size, matching detected_ring_members
    row-for-row (this was already correct before the fix; guards against a
    future change accidentally breaking the common case)."""
    a, b, c = f"{graph_prefix}-fa", f"{graph_prefix}-fb", f"{graph_prefix}-fc"
    device = f"{graph_prefix}-full-device"
    complaint_id = _submit_complaint(client, a)
    try:
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
        run_ring_detection(db)

        from app.db.models.accounts import Account

        account_ids = {
            row[0]
            for row in db.query(Account.account_id)
            .filter(Account.account_hash.in_([hash_pii(a), hash_pii(b), hash_pii(c)]))
            .all()
        }
        ring = None
        for candidate in db.query(DetectedRing).all():
            members = {
                row[0]
                for row in db.query(DetectedRingMember.account_id).filter(DetectedRingMember.ring_id == candidate.ring_id).all()
            }
            if account_ids.issubset(members):
                ring = candidate
                break
        assert ring is not None

        persisted_row_count = (
            db.query(DetectedRingMember).filter(DetectedRingMember.ring_id == ring.ring_id).count()
        )
        assert ring.member_count == persisted_row_count == 3
    finally:
        _cleanup_complaint(complaint_id, [a, b, c])
        _run("MATCH (d:Device {device_hash: $h}) DETACH DELETE d", h=hash_pii(device))


def test_member_count_matches_partial_postgres_resolution(client, db, graph_prefix):
    """One real Postgres-backed account, plus a Neo4j-only "ghost" account
    injected directly into the graph and connected to it - reproducing the
    exact shape of the real historical bug at a smaller scale. member_count
    must reflect only the resolved account, not the full graph community.

    `_submit_complaint` alone already creates `a`'s real Postgres account
    (as the complaint's victim) - no separate transaction is needed to
    resolve it, which keeps this test to a single graph edge (a <-> ghost)
    and therefore a single occurred_at value, avoiding an unrelated,
    pre-existing sensitivity in _time_features() to mixed naive/aware
    timestamp formats when a community spans multiple transactions."""
    a = f"{graph_prefix}-pa"
    ghost = f"ghost-{uuid.uuid4().hex}"
    complaint_id = _submit_complaint(client, a)
    try:
        # `ghost` is written straight to Neo4j only - no Postgres account
        # ever created for it, exactly like the historical contamination.
        applied = apply_transaction(
            from_hash=hash_pii(a), to_hash=ghost, txn_id=str(uuid.uuid4()),
            amount="1000.00", channel="upi", hop_index=1, occurred_at="2026-08-27T09:00:00+00:00",
        )
        assert applied

        run_ring_detection(db)

        ring = _ring_for_ghost_pair(db, hash_pii(a), ghost)
        assert ring is not None, "expected a's community (now including the ghost account) to be detected"

        persisted_row_count = (
            db.query(DetectedRingMember).filter(DetectedRingMember.ring_id == ring.ring_id).count()
        )
        assert persisted_row_count == 1, "only the real Postgres-backed account should have a member row"
        assert ring.member_count == 1, "member_count must match the resolved (persisted) set, not the graph size"

        # Neo4j itself is unaffected by this fix - it still reflects every
        # graph member, resolved or not.
        neo4j_rows = _run(
            "MATCH (a:Account)-[:MEMBER_OF_RING]->(r:Ring {ring_id: $ring_id}) RETURN count(a) AS cnt",
            ring_id=ring.ring_id,
        )
        assert neo4j_rows[0]["cnt"] == 2
    finally:
        _cleanup_complaint(complaint_id, [a])
        _cleanup_hashes([ghost])


def test_member_count_matches_zero_postgres_resolution(db):
    """Neither graph member resolves to a Postgres account at all - the
    exact shape of the real ff53e73 contamination found during the audit.
    Per the approved fix (reconcile, don't withhold): the ring is still
    persisted, but member_count must be 0, matching zero
    detected_ring_members rows - never the raw graph size."""
    ghost_a, ghost_b = f"ghost-{uuid.uuid4().hex}", f"ghost-{uuid.uuid4().hex}"
    try:
        applied = apply_transaction(
            from_hash=ghost_a, to_hash=ghost_b, txn_id=str(uuid.uuid4()),
            amount="500.00", channel="upi", hop_index=1, occurred_at="2026-08-27T09:00:00+00:00",
        )
        assert applied

        run_ring_detection(db)

        ring = _ring_for_ghost_pair(db, ghost_a, ghost_b)
        assert ring is not None, "a ring must still be persisted (reconcile, not withhold)"

        persisted_row_count = (
            db.query(DetectedRingMember).filter(DetectedRingMember.ring_id == ring.ring_id).count()
        )
        assert persisted_row_count == 0
        assert ring.member_count == 0

        neo4j_rows = _run(
            "MATCH (a:Account)-[:MEMBER_OF_RING]->(r:Ring {ring_id: $ring_id}) RETURN count(a) AS cnt",
            ring_id=ring.ring_id,
        )
        assert neo4j_rows[0]["cnt"] == 2, "Neo4j still reflects the true graph structure, unaffected by this fix"
    finally:
        _cleanup_hashes([ghost_a, ghost_b])
