"""
Integration tests for the Phase 2C corridor prediction pipeline -
docs/AI_ML_ARCHITECTURE.md §3, wired RING_DETECTED -> corridor predictor ->
persist -> CORRIDOR_PREDICTION_COMPLETED (app/graph/handlers.py).

Genuine, documented gap found while writing these tests: `find_or_create_account`
(app/shared/accounts.py, used by every real complaint/transaction endpoint)
never sets Account.branch_lat/lon - only app/synthetic/generator.py's
_make_synthetic_account does. Corridor prediction requires geolocation on
both ends of every hop, so it can never fire for a purely real-API-submitted
account today; this is a pre-existing architecture gap (no request field
anywhere carries account branch geolocation), not something Phase 2C
created or should silently work around by touching Phase 2A's frozen
ingestion contract. These tests set branch_lat/lon directly after real
HTTP submission - exactly mirroring what the synthetic generator already
does, disclosed as test setup, not a claim that real ingestion sets it.
"""
import uuid

import pytest

from app.core.security import hash_pii
from app.db.models.accounts import Account
from app.db.models.predictions import Prediction
from app.db.neo4j_client import check_connectivity, get_driver
from app.graph.corridor import (
    get_prediction_for_complaint,
    reset_cached_model,
    run_corridor_prediction_for_complaint,
)
from app.graph.ring_service import run_ring_detection
from app.synthetic.generator import seed_banks, seed_jurisdictions, seed_mule_rings
from tests.conftest import auth_headers, service_token, valid_complaint_payload, valid_transaction_payload

pytestmark = pytest.mark.skipif(
    not check_connectivity(), reason="Neo4j not reachable - skipping real-graph tests"
)


@pytest.fixture(autouse=True)
def _fresh_corridor_model():
    """The trained classifier is cached process-wide (app/graph/corridor.py's
    get_or_train_model), but tests/conftest.py's _clean_database fixture
    resets the SQLite DB before every test - without this, a model trained
    against one test's data would silently serve predictions in the next
    test against a completely different (or empty) dataset."""
    reset_cached_model()
    yield
    reset_cached_model()


@pytest.fixture
def corridor_ground_truth(db):
    """Enough synthetic ground-truth rings (AI_ML_ARCHITECTURE.md §2's
    planted mule rings, app/synthetic/generator.py::seed_mule_rings) for
    train_corridor_classifier's minimum-size/class-diversity checks to
    pass - 15 independently-jittered rings reliably clears both the >=10
    row minimum and the >=2 bearing-bucket diversity minimum."""
    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    seed_mule_rings(db, bank_ids, jurisdiction_ids, ring_count=15)


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


def _build_geolocated_ring(client, db, graph_prefix):
    """A real 3-account mule chain via the real HTTP API, then branch_lat/lon
    backfilled directly - see module docstring for why."""
    a, b, c = f"{graph_prefix}-ca", f"{graph_prefix}-cb", f"{graph_prefix}-cc"
    device = f"{graph_prefix}-corridor-device"
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

    # Backfill geolocation - a clear NE-ish corridor, not random jitter,
    # so a deterministic bearing bucket is knowable for assertions.
    coords = {a: (13.00, 80.00), b: (13.05, 80.05), c: (13.10, 80.10)}
    for account_number, (lat, lon) in coords.items():
        account = db.query(Account).filter(Account.account_hash == hash_pii(account_number)).first()
        assert account is not None
        account.branch_lat, account.branch_lon = lat, lon
    db.commit()

    run_ring_detection(db)
    return complaint_id, (a, b, c), device


def test_corridor_prediction_persists_exit_vector_for_a_real_ring(client, db, graph_prefix, corridor_ground_truth):
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        results = run_corridor_prediction_for_complaint(db, complaint_id)
        assert len(results) >= 1, "expected at least one ring's corridor prediction for this complaint"

        result = results[0]
        exit_vector = result["exit_vector"]
        assert 0.0 <= exit_vector["bearing_deg"] < 360.0
        assert exit_vector["confidence_cone_deg"] in (30.0, 60.0)
        assert len(exit_vector["distance_range_km"]) == 2
        assert exit_vector["exit_channel_type"] in ("atm_cash", "crypto_p2p", "ecommerce_merchant")

        prediction = db.query(Prediction).filter(Prediction.prediction_id == result["prediction_id"]).first()
        assert prediction is not None
        assert prediction.complaint_id == complaint_id
        assert prediction.exit_vector == exit_vector
        assert prediction.ranked_locations is None, "Phase 2D not built - must be explicit null, never fabricated"
        assert prediction.model_version_corridor is not None
        assert prediction.model_version_ring is not None
    finally:
        _cleanup(complaint_id, [a, b, c], device)


def test_corridor_prediction_returns_none_when_geolocation_is_unknown(client, db, graph_prefix):
    """The documented, honest failure mode: a ring with no known branch
    geolocation on any hop produces no prediction at all, not a fabricated
    one - this is the real-ingestion-path default today (see module
    docstring), reproduced here without the geolocation backfill."""
    a, b = f"{graph_prefix}-nga", f"{graph_prefix}-ngb"
    complaint_id = _submit_complaint(client, a)
    client.post(
        "/v1/transactions/ingest",
        json=valid_transaction_payload(complaint_id=complaint_id, from_account_number=a, to_account_number=b),
        headers=auth_headers(service_token()),
    )
    try:
        run_ring_detection(db)
        results = run_corridor_prediction_for_complaint(db, complaint_id)
        assert results == [], "no geolocation anywhere in the ring - no prediction should be fabricated"
    finally:
        _cleanup(complaint_id, [a, b])


def test_get_prediction_for_complaint_returns_the_latest(client, db, graph_prefix, corridor_ground_truth):
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        run_corridor_prediction_for_complaint(db, complaint_id)
        latest = get_prediction_for_complaint(db, complaint_id)
        assert latest is not None
        assert latest.complaint_id == complaint_id

        by_id = get_prediction_for_complaint(db, complaint_id, prediction_id=latest.prediction_id)
        assert by_id is not None
        assert by_id.prediction_id == latest.prediction_id
    finally:
        _cleanup(complaint_id, [a, b, c], device)


def test_get_prediction_for_complaint_returns_none_when_no_prediction_exists(client, graph_prefix):
    a = f"{graph_prefix}-noneA"
    complaint_id = _submit_complaint(client, a)
    try:
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            assert get_prediction_for_complaint(db, complaint_id) is None
        finally:
            db.close()
    finally:
        _cleanup(complaint_id, [a])


def test_prediction_endpoint_returns_404_before_any_prediction_exists(client, graph_prefix):
    from tests.conftest import make_token
    from app.db.models.enums import UserRole

    a = f"{graph_prefix}-epA"
    complaint_id = _submit_complaint(client, a)
    try:
        token = make_token(UserRole.auditor)  # bypasses jurisdiction scoping, isolates the 404 case
        response = client.get(f"/v1/complaints/{complaint_id}/prediction", headers=auth_headers(token))
        assert response.status_code == 404
    finally:
        _cleanup(complaint_id, [a])


def test_prediction_endpoint_returns_exit_vector_and_disclaimer(client, db, graph_prefix, corridor_ground_truth):
    from tests.conftest import make_token
    from app.db.models.enums import UserRole

    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        run_corridor_prediction_for_complaint(db, complaint_id)

        token = make_token(UserRole.auditor)  # auditor sees all jurisdictions, no scoping surprises
        response = client.get(f"/v1/complaints/{complaint_id}/prediction", headers=auth_headers(token))
        assert response.status_code == 200
        body = response.json()

        assert "exit_vector" in body
        assert set(body["exit_vector"].keys()) == {
            "bearing_deg", "distance_range_km", "confidence_cone_deg", "exit_channel_type",
        }
        assert body["ranked_locations"] is None
        assert body["model_versions"]["exit_channel"] is None
        assert body["model_versions"]["time_window"] is None
        assert body["disclaimer"] == (
            "This is an investigative lead based on automated pattern analysis, "
            "not a definitive determination of wrongdoing."
        )
    finally:
        _cleanup(complaint_id, [a, b, c], device)
