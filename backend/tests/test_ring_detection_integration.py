"""
Phase 2B, the required comprehensive integration test (section 8): the full
real pipeline, driven by the actual synthetic ground-truth generator -

    seed_mule_rings (planted rings) -> rebuild_all (Postgres -> Neo4j)
    -> run_ring_detection (Louvain) -> evaluate_against_ground_truth

run against the real Docker PostgreSQL + Neo4j stack (Neo4j; Postgres here
is the test suite's SQLite-in-memory stand-in - see backend/README.md's
documented one-line DATABASE_URL swap to point this at real Postgres), with
independent verification against both databases directly (section 9 - not
just trusting the summary dicts these functions return).

Uses `rebuild_all(db, wipe=False)` deliberately, never `wipe=True` -
app/graph/rebuild.py's module docstring is explicit that the destructive
wipe is only ever exercised against a real environment
(scripts/rebuild_neo4j_graph.py), never run unattended in the automated
suite against a shared Neo4j instance that may hold other data. `wipe=False`
is safe here because Postgres is reset per test (this file's own `db`
fixture via tests/conftest.py's autouse `_clean_database`), so
`_sync_complaintless_transactions` only ever sees the rows *this test* just
planted - nothing from any other test or prior run leaks into the sync.
"""
import pytest

from app.db.models.accounts import Account
from app.db.models.rings import DetectedRing, DetectedRingMember
from app.db.neo4j_client import check_connectivity, get_driver
from app.graph.evaluation import evaluate_against_ground_truth
from app.graph.rebuild import rebuild_all
from app.graph.ring_service import run_ring_detection
from app.synthetic.generator import seed_banks, seed_jurisdictions, seed_mule_rings

pytestmark = pytest.mark.skipif(
    not check_connectivity(), reason="Neo4j not reachable - skipping real-graph integration test"
)


def _run(query, **params):
    driver = get_driver()
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def test_planted_mule_rings_are_recovered_end_to_end(db):
    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    planted_rings = seed_mule_rings(db, bank_ids, jurisdiction_ids, ring_count=3)

    planted_account_id_sets = [set([r["victim_account_id"]] + r["mule_account_ids"]) for r in planted_rings]
    all_account_ids = [aid for s in planted_account_id_sets for aid in s]
    accounts = db.query(Account).filter(Account.account_id.in_(all_account_ids)).all()
    account_hashes = [a.account_hash for a in accounts]
    assert len(account_hashes) == len(all_account_ids), "every planted account must exist in Postgres"

    try:
        # --- Pipeline, exactly as the production event chain runs it ---
        rebuild_summary = rebuild_all(db, wipe=False)
        expected_min_hops = sum(len(r["mule_account_ids"]) for r in planted_rings)  # victim->mule1->mule2->... chain
        assert rebuild_summary["transactions_applied"] >= expected_min_hops

        detection_summary = run_ring_detection(db)
        assert detection_summary["communities_detected"] >= len(planted_rings), (
            "each planted ring is its own isolated connected component (no shared entities "
            "or transactions link separate rings by construction) - Louvain cannot merge "
            "disconnected components, so at least one community per planted ring is structurally guaranteed"
        )

        evaluation = evaluate_against_ground_truth(db)
        assert evaluation["evaluable"] is True
        assert evaluation["detection_coverage"] > 0.0, "not a single planted ring was recovered at all"
        assert any(row["recall"] > 0.0 for row in evaluation["per_ring"])

        # --- Independent verification (section 9): query Postgres and
        # Neo4j directly, rather than trusting the summary dicts above. ---

        detected_rings = db.query(DetectedRing).all()
        assert len(detected_rings) >= len(planted_rings)

        recovered_ring_ids = []
        for planted_set in planted_account_id_sets:
            for ring in detected_rings:
                members = {
                    row[0]
                    for row in db.query(DetectedRingMember.account_id)
                    .filter(DetectedRingMember.ring_id == ring.ring_id)
                    .all()
                }
                if members and members.issubset(planted_set) and len(members) >= 2:
                    recovered_ring_ids.append(ring.ring_id)
                    break
        assert recovered_ring_ids, "independent Postgres query found no detected ring fully contained in a planted ring"

        # Neo4j: query directly for the same recovered ring's :Ring/MEMBER_OF_RING
        # structure - a separate database, a separate query path, not a re-read
        # of what Postgres already claims.
        neo4j_ring_check = _run(
            "MATCH (a:Account)-[:MEMBER_OF_RING]->(r:Ring) WHERE r.ring_id IN $ring_ids "
            "RETURN r.ring_id AS ring_id, count(a) AS member_count",
            ring_ids=recovered_ring_ids,
        )
        assert len(neo4j_ring_check) > 0, "independent Neo4j query found no Ring node matching a recovered ring_id"
        for row in neo4j_ring_check:
            assert row["member_count"] >= 2
    finally:
        _run(
            "MATCH (a:Account)-[:MEMBER_OF_RING]->(r:Ring) WHERE a.account_hash IN $hashes DETACH DELETE r",
            hashes=account_hashes,
        )
        _run("MATCH (n) WHERE n.account_hash IN $hashes DETACH DELETE n", hashes=account_hashes)
