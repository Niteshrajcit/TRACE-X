"""
Integration tests for the Phase 2D exit-channel + time-window scoring
pipeline - docs/AI_ML_ARCHITECTURE.md §4, wired
CORRIDOR_PREDICTION_COMPLETED -> exit scorer -> update Prediction ->
EXIT_PREDICTION_COMPLETED (app/graph/handlers.py).

Same geolocation-backfill disclosure as
tests/test_corridor_prediction_integration.py: real ingestion never sets
Account.branch_lat/lon, so these tests backfill it directly after real
HTTP submission - disclosed as exactly that, not a claim about real
ingestion behavior.
"""
import pytest

from app.core.security import hash_pii
from app.db.models.accounts import Account
from app.db.models.predictions import Prediction
from app.db.neo4j_client import check_connectivity, get_driver
from app.events.dispatcher import dispatcher
from app.events.topics import CORRIDOR_PREDICTION_COMPLETED, EXIT_PREDICTION_COMPLETED
from app.graph.corridor import reset_cached_model, run_corridor_prediction_for_complaint
from app.graph.exit_scorer import reset_cached_models, run_exit_scoring_for_complaint
from app.graph.ring_service import run_ring_detection
from app.synthetic.generator import seed_banks, seed_exit_channels, seed_jurisdictions, seed_mule_rings
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


@pytest.fixture(autouse=True)
def _fresh_models():
    reset_cached_model()
    reset_cached_models()
    yield
    reset_cached_model()
    reset_cached_models()


@pytest.fixture
def exit_scorer_ground_truth(db):
    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    seed_exit_channels(db, jurisdiction_ids)
    seed_mule_rings(db, bank_ids, jurisdiction_ids, ring_count=15)


def _submit_complaint(client, victim_account_number):
    response = client.post(
        "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai", victim_account_number=victim_account_number)
    )
    assert response.status_code == 201
    return response.json()["complaint_id"]


def _build_geolocated_ring(client, db, graph_prefix):
    a, b, c = f"{graph_prefix}-esa", f"{graph_prefix}-esb", f"{graph_prefix}-esc"
    device = f"{graph_prefix}-exit-scorer-device"
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

    coords = {a: (13.00, 80.00), b: (13.05, 80.05), c: (13.10, 80.10)}
    for account_number, (lat, lon) in coords.items():
        account = db.query(Account).filter(Account.account_hash == hash_pii(account_number)).first()
        assert account is not None
        account.branch_lat, account.branch_lon = lat, lon
    db.commit()

    run_ring_detection(db)
    # Both direct calls, not through the event dispatcher (the automatic
    # HTTP-triggered chain already ran once, before geolocation existed,
    # and correctly produced nothing) - mirrors
    # tests/test_corridor_prediction_integration.py's own pattern, one
    # level further down the pipeline since exit-scoring needs a real
    # corridor Prediction row to already exist.
    run_corridor_prediction_for_complaint(db, complaint_id)
    return complaint_id, (a, b, c), device


def test_exit_scoring_persists_ranked_locations_and_preserves_corridor_exit_vector(
    client, db, graph_prefix, exit_scorer_ground_truth
):
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        prediction_before = db.query(Prediction).filter(Prediction.complaint_id == complaint_id).first()
        assert prediction_before is not None
        assert prediction_before.exit_vector is not None
        original_exit_vector = dict(prediction_before.exit_vector)
        assert prediction_before.ranked_locations is None

        results = run_exit_scoring_for_complaint(db, complaint_id)
        assert len(results) >= 1

        db.refresh(prediction_before)
        assert prediction_before.exit_vector == original_exit_vector, "Phase 2C's exit_vector must be preserved untouched"
        assert prediction_before.ranked_locations is not None
        assert len(prediction_before.ranked_locations) >= 1
        for entry in prediction_before.ranked_locations:
            assert set(entry.keys()) == {
                "exit_channel_id", "h3_cell", "channel_type", "probability", "time_window_min", "confidence_interval",
            }
            assert 0.0 <= entry["probability"] <= 1.0
        assert prediction_before.model_version_location is not None
        assert prediction_before.model_version_time is not None
    finally:
        _cleanup(complaint_id, [a, b, c], device)


def test_idempotent_rescoring_updates_the_same_row_without_duplication(
    client, db, graph_prefix, exit_scorer_ground_truth
):
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        run_exit_scoring_for_complaint(db, complaint_id)
        predictions_after_first = db.query(Prediction).filter(Prediction.complaint_id == complaint_id).all()
        prediction_id = predictions_after_first[0].prediction_id
        first_ranked = predictions_after_first[0].ranked_locations

        run_exit_scoring_for_complaint(db, complaint_id)
        predictions_after_second = db.query(Prediction).filter(Prediction.complaint_id == complaint_id).all()

        assert len(predictions_after_second) == len(predictions_after_first), "re-scoring must never create a new row"
        assert predictions_after_second[0].prediction_id == prediction_id
        # Deterministic given unchanged data/models - same ranking both times.
        assert predictions_after_second[0].ranked_locations == first_ranked
    finally:
        _cleanup(complaint_id, [a, b, c], device)


@pytest.mark.asyncio
async def test_event_pipeline_corridor_to_exit_prediction_completed(client, db, graph_prefix, exit_scorer_ground_truth):
    """Publishes CORRIDOR_PREDICTION_COMPLETED through the real,
    already-registered dispatcher (app/main.py's startup wires
    register_exit_scoring_handlers() onto this same process-wide
    singleton) - exercises the actual handler, not a hand-simulated call,
    and confirms it republishes EXIT_PREDICTION_COMPLETED with the
    scored result."""
    from sqlalchemy import text

    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(EXIT_PREDICTION_COMPLETED, _probe)
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        prediction = db.query(Prediction).filter(Prediction.complaint_id == complaint_id).first()
        assert prediction is not None and prediction.exit_vector is not None

        ring_row = db.execute(
            text("SELECT ring_id FROM detected_ring_complaints WHERE complaint_id = :cid"), {"cid": complaint_id}
        ).first()
        assert ring_row is not None
        ring_id = ring_row[0]

        await dispatcher.publish(
            CORRIDOR_PREDICTION_COMPLETED,
            {
                "complaint_id": complaint_id,
                "ring_id": ring_id,
                "prediction_id": prediction.prediction_id,
                "exit_vector": prediction.exit_vector,
            },
        )

        assert len(calls) == 1
        assert calls[0]["complaint_id"] == complaint_id
        assert calls[0]["prediction_id"] == prediction.prediction_id
        assert calls[0]["ranked_locations"]
    finally:
        dispatcher.unsubscribe(EXIT_PREDICTION_COMPLETED, _probe)
        _cleanup(complaint_id, [a, b, c], device)


def test_prediction_endpoint_returns_populated_ranked_locations(client, db, graph_prefix, exit_scorer_ground_truth):
    from tests.conftest import make_token
    from app.db.models.enums import UserRole

    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        run_exit_scoring_for_complaint(db, complaint_id)

        token = make_token(UserRole.auditor)
        response = client.get(f"/v1/complaints/{complaint_id}/prediction", headers=auth_headers(token))
        assert response.status_code == 200
        body = response.json()

        assert body["ranked_locations"] is not None
        assert len(body["ranked_locations"]) >= 1
        assert body["model_versions"]["exit_channel"] is not None
        assert body["model_versions"]["time_window"] is not None
        # Corridor's own fields must still be present, unaffected.
        assert body["exit_vector"] is not None
        assert body["model_versions"]["corridor"] is not None
    finally:
        _cleanup(complaint_id, [a, b, c], device)
