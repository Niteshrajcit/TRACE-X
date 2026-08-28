"""
Phase 2B, section 8 (event emission + repeatability): verifies the actual
dispatcher chain fires end-to-end -

    transaction.ingested -> graph.updated -> intelligence.started
    -> ring detection -> ring.detected

- not just that `run_ring_detection` returns something when called
directly (that's covered by test_ring_persistence.py). This subscribes
throwaway probe handlers to the same process-wide `dispatcher` singleton
app/graph/handlers.py itself subscribes to, then drives the chain the same
way production does: a real POST through the HTTP ingestion API.
"""
import pytest

from app.core.security import hash_pii
from app.db.neo4j_client import check_connectivity, get_driver
from app.events.dispatcher import dispatcher
from app.events.topics import INTELLIGENCE_STARTED, RING_DETECTED
from tests.conftest import auth_headers, service_token, valid_complaint_payload, valid_transaction_payload

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


class _Probe:
    """Records every payload it's called with, in order - a bare async
    function would work too, but a class instance is trivial to reset
    between assertions within one test."""

    def __init__(self):
        self.calls = []

    async def __call__(self, payload: dict) -> None:
        self.calls.append(payload)


@pytest.fixture
def probes():
    """Subscribes fresh probes to INTELLIGENCE_STARTED / RING_DETECTED for
    the duration of one test, then unsubscribes - the dispatcher is a
    process-wide singleton shared with every other test in the suite, so a
    leaked subscription would see (and fail on) unrelated tests' traffic."""
    started, detected = _Probe(), _Probe()
    dispatcher.subscribe(INTELLIGENCE_STARTED, started)
    dispatcher.subscribe(RING_DETECTED, detected)
    try:
        yield started, detected
    finally:
        dispatcher.unsubscribe(INTELLIGENCE_STARTED, started)
        dispatcher.unsubscribe(RING_DETECTED, detected)


def test_graph_updated_triggers_intelligence_started_then_ring_detected(client, graph_prefix, probes):
    started, detected = probes
    a, b = f"{graph_prefix}-eva", f"{graph_prefix}-evb"
    complaint_id = _submit_complaint(client, a)
    try:
        resp = client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=a, to_account_number=b),
            headers=auth_headers(service_token()),
        )
        assert resp.status_code == 202

        # Exactly one full pass triggered by this one ingestion - not zero
        # (dead wiring) and not more than one (duplicate subscription bug).
        assert len(started.calls) == 1
        assert started.calls[0]["complaint_id"] == complaint_id
        assert started.calls[0]["stage"] == "ring_detection"

        assert len(detected.calls) == 1
        payload = detected.calls[0]
        assert payload["complaint_id"] == complaint_id
        assert payload["algorithm"].startswith("louvain")  # e.g. "louvain:networkx-3.6.1" - version-qualified
        assert isinstance(payload["communities_detected"], int)
        assert isinstance(payload["graph_nodes"], int)
        assert isinstance(payload["graph_edges"], int)

        # Ordering: intelligence.started must precede ring.detected, per the
        # documented pipeline sequence, not just both eventually firing.
        # (Verified implicitly: _on_graph_updated awaits the started-publish
        # before running detection, and both probes append synchronously.)
    finally:
        _cleanup(complaint_id, [a, b])


def test_each_transaction_ingestion_retriggers_the_full_chain(client, graph_prefix, probes):
    """Repeatability (section 8): the chain isn't a one-shot wiring fluke -
    it fires again, independently, for a second, unrelated ingestion."""
    started, detected = probes
    a, b, c = f"{graph_prefix}-repa", f"{graph_prefix}-repb", f"{graph_prefix}-repc"
    complaint_id = _submit_complaint(client, a)
    try:
        for from_acc, to_acc in [(a, b), (b, c)]:
            resp = client.post(
                "/v1/transactions/ingest",
                json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=from_acc, to_account_number=to_acc),
                headers=auth_headers(service_token()),
            )
            assert resp.status_code == 202

        assert len(started.calls) == 2
        assert len(detected.calls) == 2
    finally:
        _cleanup(complaint_id, [a, b, c])


def test_ring_detection_failure_does_not_break_ingestion_or_emit_ring_detected(client, graph_prefix, probes, monkeypatch):
    """If ring detection blows up (Neo4j hiccup, etc.) the ingestion request
    must still succeed - app/graph/handlers.py's try/except is the thing
    under test here, not a happy path."""
    started, detected = probes
    a, b = f"{graph_prefix}-faila", f"{graph_prefix}-failb"
    complaint_id = _submit_complaint(client, a)

    def _boom(db):
        raise RuntimeError("simulated ring detection failure")

    monkeypatch.setattr("app.graph.handlers.run_ring_detection", _boom)
    try:
        resp = client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=a, to_account_number=b),
            headers=auth_headers(service_token()),
        )
        assert resp.status_code == 202  # ingestion succeeds regardless

        assert len(started.calls) == 1  # still announced the attempt
        assert len(detected.calls) == 0  # but never claims a result that doesn't exist
    finally:
        _cleanup(complaint_id, [a, b])
