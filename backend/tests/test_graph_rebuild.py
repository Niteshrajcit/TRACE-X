"""
docs/ARCHITECTURE.md: "PostgreSQL -> rebuild Neo4j -> same graph structure."

Uses `app.graph.rebuild.rebuild_complaint_subgraph` directly (not the full,
whole-instance-wiping `rebuild_all`/`wipe_graph`) - safe to run in an
automated suite against a real, shared Neo4j instance that may also hold
seeded/demo data. The full destructive wipe+rebuild is exercised
deliberately, once, as part of Phase 2A's live verification against the
Docker stack - not run unattended here.

Every test submits its own complaint with a `graph_prefix`-unique victim
account number (rather than reusing the shared `submitted_complaint`
fixture's fixed "VICTIM-0001") - docs/DATA_MODEL.md §3's canonical
traversal query is intentionally not scoped by complaint_id on
TRANSFERRED_TO edges (an account's full reachable set matters regardless of
which complaint's Postgres rows reference it), so any test asserting an
*exact* reachable-account count must own an account node no other test in
the suite ever touches - a shared real Neo4j instance would otherwise mix
in unrelated tests' edges on the same node.
"""
import pytest

from app.core.security import hash_pii
from app.db.neo4j_client import check_connectivity, get_driver
from app.db.session import SessionLocal
from app.graph.rebuild import rebuild_complaint_subgraph
from tests.conftest import auth_headers, service_token, valid_complaint_payload, valid_transaction_payload

pytestmark = pytest.mark.skipif(
    not check_connectivity(), reason="Neo4j not reachable - skipping real-graph tests"
)


def _run(query, **params):
    driver = get_driver()
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def _cleanup(complaint_id: str, account_numbers: list[str]):
    hashes = [hash_pii(n) for n in account_numbers]
    _run(
        "MATCH (n) WHERE n.complaint_id = $complaint_id OR n.account_hash IN $hashes DETACH DELETE n",
        complaint_id=complaint_id,
        hashes=hashes,
    )


def _submit_complaint_with_victim(client, victim_account_number: str, jurisdiction_hint: str) -> str:
    response = client.post(
        "/v1/complaints",
        json=valid_complaint_payload(
            jurisdiction_hint=jurisdiction_hint, victim_account_number=victim_account_number
        ),
    )
    assert response.status_code == 201
    return response.json()["complaint_id"]


def test_rebuild_reproduces_identical_edge_structure(client, jurisdiction_a, graph_prefix):
    victim = f"{graph_prefix}-victim"
    mule1, mule2 = f"{graph_prefix}-mule1", f"{graph_prefix}-mule2"
    complaint_id = _submit_complaint_with_victim(client, victim, "Chennai")

    try:
        def ingest(src, dst):
            return client.post(
                "/v1/transactions/ingest",
                json=valid_transaction_payload(
                    complaint_id=complaint_id, from_account_number=src, to_account_number=dst
                ),
                headers=auth_headers(service_token()),
            )

        r1 = ingest(victim, mule1)
        r2 = ingest(mule1, mule2)
        assert r1.status_code == 202
        assert r2.status_code == 202

        before = _run(
            "MATCH (:Complaint {complaint_id: $cid})-[:INVOLVES]->(v:Account) "
            "OPTIONAL MATCH p = (v)-[:TRANSFERRED_TO*1..6]->(a:Account) "
            "RETURN count(DISTINCT a) AS reachable_accounts, max(length(p)) AS max_depth",
            cid=complaint_id,
        )[0]
        assert before["reachable_accounts"] == 2  # mule1, mule2
        assert before["max_depth"] == 2

        # Simulate a Neo4j outage/data-loss for this complaint's subgraph.
        _cleanup(complaint_id, [victim, mule1, mule2])
        wiped = _run("MATCH (c:Complaint {complaint_id: $cid}) RETURN c", cid=complaint_id)
        assert wiped == []

        # Rebuild from Postgres alone.
        db = SessionLocal()
        try:
            summary = rebuild_complaint_subgraph(db, complaint_id)
        finally:
            db.close()
        assert summary["transactions_applied"] == 2

        after = _run(
            "MATCH (:Complaint {complaint_id: $cid})-[:INVOLVES]->(v:Account) "
            "OPTIONAL MATCH p = (v)-[:TRANSFERRED_TO*1..6]->(a:Account) "
            "RETURN count(DISTINCT a) AS reachable_accounts, max(length(p)) AS max_depth",
            cid=complaint_id,
        )[0]
        assert after == before  # equivalent structure, rebuilt purely from Postgres
    finally:
        _cleanup(complaint_id, [victim, mule1, mule2])


def test_rebuild_is_idempotent_when_graph_already_has_the_data(client, jurisdiction_a, graph_prefix):
    victim = f"{graph_prefix}-victim2"
    mule1 = f"{graph_prefix}-mule1b"
    complaint_id = _submit_complaint_with_victim(client, victim, "Chennai")

    try:
        client.post(
            "/v1/transactions/ingest",
            json=valid_transaction_payload(
                complaint_id=complaint_id, from_account_number=victim, to_account_number=mule1
            ),
            headers=auth_headers(service_token()),
        )

        db = SessionLocal()
        try:
            # Graph already has this (written live at ingestion time) -
            # re-running the rebuild step must not duplicate the edge.
            rebuild_complaint_subgraph(db, complaint_id)
        finally:
            db.close()

        rows = _run(
            "MATCH (:Complaint {complaint_id: $cid})-[:INVOLVES]->(v:Account)-[t:TRANSFERRED_TO]->(a:Account) "
            "RETURN t",
            cid=complaint_id,
        )
        assert len(rows) == 1
    finally:
        _cleanup(complaint_id, [victim, mule1])
