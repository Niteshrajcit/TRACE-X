"""
Phase 2B foundation fix - regression coverage for the real incident found
during end-to-end verification: `audit_events.subject_id` was VARCHAR(36)
(sized for UUIDs) while a ring's subject_id is a 64-char SHA-256 ring_id,
so PostgreSQL raised `StringDataRightTruncation` *after*
`_write_ring_to_neo4j` had already committed on its own connection,
leaving a permanently orphaned Neo4j Ring node with no backing Postgres
row. Fixed in two parts: widening the column (migration
4e66e0da0ea0_widen_audit_events_subject_id_to_64_) and reordering
app/graph/ring_service.py::run_ring_detection so Postgres work
(persist + audit event) commits *before* the Neo4j write, with the Neo4j
write wrapped so its own failure can't roll back an already-committed
Postgres record.

Note on why these tests matter more than they might look: SQLite (this
suite's Postgres stand-in, tests/conftest.py) does not enforce VARCHAR
length at all, so the original truncation bug was invisible to the
automated suite - it only ever surfaced against real PostgreSQL. Test
`test_audit_event_column_is_wide_enough_for_a_ring_id` therefore asserts
the *schema definition* itself (dialect-independent), which is the part
a regression here can actually catch without live Postgres; the other
tests exercise the ordering/recovery logic via monkeypatched failures,
which is dialect-independent by construction.
"""
import pytest

from app.core.security import hash_pii
from app.db.models.accounts import Account
from app.db.models.audit import AuditEvent
from app.db.models.rings import DetectedRing
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


def _build_detectable_pair(client, graph_prefix):
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


def _ring_for(db, account_ids: set[str]) -> DetectedRing | None:
    from app.db.models.rings import DetectedRingMember

    for ring in db.query(DetectedRing).all():
        members = {
            row[0]
            for row in db.query(DetectedRingMember.account_id).filter(DetectedRingMember.ring_id == ring.ring_id).all()
        }
        if account_ids.issubset(members):
            return ring
    return None


def test_audit_event_column_is_wide_enough_for_a_ring_id():
    """Schema-level, dialect-independent: guards against the column being
    narrowed back to 36 chars (SQLite wouldn't catch that at runtime)."""
    assert AuditEvent.subject_id.type.length >= 64


def test_appending_a_64_char_ring_subject_id_round_trips_exactly(db):
    from app.audit.service import append_audit_event

    ring_id = "a" * 64  # the exact length compute_ring_id() produces (SHA-256 hex)
    event = append_audit_event(
        db, event_type="ring.detected", subject_type="ring", subject_id=ring_id, payload={"member_count": 2},
    )
    db.commit()
    db.refresh(event)
    assert event.subject_id == ring_id
    assert len(event.subject_id) == 64


def test_postgres_failure_during_ring_persistence_leaves_no_orphaned_neo4j_ring(client, db, graph_prefix, monkeypatch):
    """The exact bug: if the Postgres-side work for one ring fails, that
    ring's Neo4j write must never happen at all - not happen-then-fail,
    not leave a partial node. This simulates the original failure (an
    exception from append_audit_event) directly, independent of whatever
    the real column width happens to be in this environment.

    The monkeypatch is applied *before* the scenario is built: submitting
    the two transactions through the real HTTP client also auto-triggers
    real ring detection via the existing graph.updated pipeline
    (app/graph/handlers.py) - if the fault weren't active yet during setup,
    that automatic run would already persist a real, successful ring
    before this test ever gets to simulate the failure."""
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated Postgres failure (e.g. StringDataRightTruncation)")

    monkeypatch.setattr("app.graph.ring_service.append_audit_event", _boom)
    complaint_id, (a, b, c), device = _build_detectable_pair(client, graph_prefix)
    try:
        with pytest.raises(RuntimeError, match="simulated Postgres failure"):
            run_ring_detection(db)

        # No Ring node for this test's accounts should exist in Neo4j - the
        # Postgres failure must have happened *before* the Neo4j write, on
        # every run that touched this graph, automatic or explicit.
        hashes = [hash_pii(x) for x in (a, b, c)]
        orphans = _run(
            "MATCH (acc:Account)-[:MEMBER_OF_RING]->(r:Ring) WHERE acc.account_hash IN $hashes "
            "RETURN count(DISTINCT r) AS ring_count",
            hashes=hashes,
        )
        assert orphans[0]["ring_count"] == 0
    finally:
        db.rollback()
        _cleanup(complaint_id, [a, b, c], device)


def test_neo4j_failure_does_not_roll_back_the_committed_postgres_ring(client, db, graph_prefix, monkeypatch):
    """Same setup-ordering reasoning as above, mirrored for the Neo4j-side
    failure: the fault must be active during the automatic runs triggered
    by scenario setup too, or those would already succeed in Neo4j before
    this test gets to assert anything."""
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated Neo4j failure (e.g. connection drop mid-write)")

    monkeypatch.setattr("app.graph.ring_service._write_ring_to_neo4j", _boom)
    complaint_id, (a, b, c), device = _build_detectable_pair(client, graph_prefix)
    try:
        # Must NOT raise - a Neo4j failure is caught and logged, not
        # propagated, precisely so it cannot undo the Postgres commit that
        # already happened for this ring.
        run_ring_detection(db)

        account_ids = {
            row[0]
            for row in db.query(Account.account_id)
            .filter(Account.account_hash.in_([hash_pii(a), hash_pii(b), hash_pii(c)]))
            .all()
        }
        ring = _ring_for(db, account_ids)
        assert ring is not None, "Postgres must hold the ring despite the Neo4j write failing"

        # And Neo4j must NOT have it yet - the failure really happened, this
        # isn't accidentally passing because the write succeeded anyway.
        hashes = [hash_pii(x) for x in (a, b, c)]
        neo4j_rows = _run(
            "MATCH (acc:Account)-[:MEMBER_OF_RING]->(r:Ring) WHERE acc.account_hash IN $hashes "
            "RETURN count(DISTINCT r) AS ring_count",
            hashes=hashes,
        )
        assert neo4j_rows[0]["ring_count"] == 0
    finally:
        _cleanup(complaint_id, [a, b, c], device)


def test_redetection_reconciles_neo4j_after_a_prior_neo4j_write_failure(client, db, graph_prefix, monkeypatch):
    """Idempotent retry / self-healing: once the transient Neo4j failure is
    gone, simply re-running detection (exactly what the next real
    graph.updated event does automatically) must fill in the missing
    Neo4j Ring node - deterministically, with the same ring_id, no
    duplicate Postgres row."""
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated Neo4j failure")

    monkeypatch.setattr("app.graph.ring_service._write_ring_to_neo4j", _boom)
    complaint_id, (a, b, c), device = _build_detectable_pair(client, graph_prefix)
    try:
        run_ring_detection(db)
        monkeypatch.undo()

        account_ids = {
            row[0]
            for row in db.query(Account.account_id)
            .filter(Account.account_hash.in_([hash_pii(a), hash_pii(b), hash_pii(c)]))
            .all()
        }
        ring_before = _ring_for(db, account_ids)
        assert ring_before is not None

        run_ring_detection(db)  # real write this time - no monkeypatch active

        hashes = [hash_pii(x) for x in (a, b, c)]
        neo4j_rows = _run(
            "MATCH (acc:Account)-[:MEMBER_OF_RING]->(r:Ring) WHERE acc.account_hash IN $hashes "
            "RETURN DISTINCT r.ring_id AS ring_id",
            hashes=hashes,
        )
        assert len(neo4j_rows) == 1
        assert neo4j_rows[0]["ring_id"] == ring_before.ring_id

        # Still exactly one Postgres row for this ring_id - reconciliation
        # via retry must never duplicate the persisted record.
        assert db.query(DetectedRing).filter(DetectedRing.ring_id == ring_before.ring_id).count() == 1
    finally:
        _cleanup(complaint_id, [a, b, c], device)
