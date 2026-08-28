"""
Integration/idempotency/API/RBAC/WebSocket tests for Phase 2F's wired
Explainer - docs/AI_ML_ARCHITECTURE.md §6:

    exit_prediction.completed -> Explainer -> predictions.explanation
    -> explanation.generated -> WebSocket jurisdiction-scoped fan-out
    GET /v1/complaints/{complaint_id}/explanation

The Neo4j-backed event-pipeline/graph-path tests reuse
tests/test_exit_scorer_integration.py's own established setup
(`_build_geolocated_ring`) - duplicated here (no cross-test-file import
precedent in this repo) rather than imported. Same geolocation-backfill
disclosure: real ingestion never sets Account.branch_lat/lon, so these
tests backfill it directly after real HTTP submission.

The API/RBAC/idempotency tests construct a Prediction with a hand-built
feature_snapshot directly (mirrors tests/test_risk_field_integration.py's
own pattern) - Neo4j-independent, since the API layer's own correctness
does not depend on a real graph existing (a missing graph correctly yields
an honest, non-fabricated `graph_path.path_complete: False`, exercised by
tests/test_explainer_unit.py already).
"""
import queue
import threading
import uuid
from datetime import datetime, timezone

import pytest

from app.core.security import hash_pii
from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus, FraudType, InstitutionType, UserRole
from app.db.models.predictions import Prediction
from app.db.neo4j_client import check_connectivity, get_driver
from app.events.dispatcher import dispatcher
from app.events.topics import CORRIDOR_PREDICTION_COMPLETED, EXIT_PREDICTION_COMPLETED, EXPLANATION_GENERATED
from app.graph.corridor import reset_cached_model, run_corridor_prediction_for_complaint
from app.graph.exit_scorer import _FEATURE_ORDER, reset_cached_models, run_exit_scoring_for_complaint
from app.graph.explainer import reset_shap_explainer_cache
from app.graph.ring_service import run_ring_detection
from app.synthetic.generator import seed_banks, seed_exit_channels, seed_jurisdictions, seed_mule_rings
from tests.conftest import auth_headers, make_token, service_token, valid_complaint_payload, valid_transaction_payload

neo4j_required = pytest.mark.skipif(not check_connectivity(), reason="Neo4j not reachable - skipping real-graph tests")


@pytest.fixture(autouse=True)
def _fresh_models():
    reset_cached_model()
    reset_cached_models()
    reset_shap_explainer_cache()
    yield
    reset_cached_model()
    reset_cached_models()
    reset_shap_explainer_cache()


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
    a, b, c = f"{graph_prefix}-expa", f"{graph_prefix}-expb", f"{graph_prefix}-expc"
    device = f"{graph_prefix}-explainer-device"
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
    run_corridor_prediction_for_complaint(db, complaint_id)
    return complaint_id, (a, b, c), device


@neo4j_required
def test_exit_scoring_now_persists_a_real_feature_snapshot(client, db, graph_prefix, exit_scorer_ground_truth):
    """[Decision freeze #1] Confirms app/graph/exit_scorer.py's additive
    change actually persists real per-candidate feature vectors, and that
    Phase 2D's own output (ranked_locations/exit_vector) is unaffected."""
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        results = run_exit_scoring_for_complaint(db, complaint_id)
        assert len(results) >= 1

        prediction = db.query(Prediction).filter(Prediction.complaint_id == complaint_id).first()
        assert prediction is not None
        assert prediction.ranked_locations is not None  # Phase 2D output unchanged

        snapshot = prediction.feature_snapshot
        assert snapshot["feature_order"]
        assert snapshot["ring_id"]
        assert snapshot["by_exit_channel_id"]
        top_channel_id = prediction.ranked_locations[0]["exit_channel_id"]
        assert top_channel_id in snapshot["by_exit_channel_id"]
    finally:
        _cleanup(complaint_id, [a, b, c], device)


@neo4j_required
@pytest.mark.asyncio
async def test_event_pipeline_exit_prediction_to_explanation_generated(client, db, graph_prefix, exit_scorer_ground_truth):
    """Publishes EXIT_PREDICTION_COMPLETED through the real,
    already-registered dispatcher - exercises the actual Explainer handler,
    not a hand-simulated call, and confirms it persists predictions.explanation
    and republishes EXPLANATION_GENERATED."""
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(EXPLANATION_GENERATED, _probe)
    try:
        results = run_exit_scoring_for_complaint(db, complaint_id)
        assert len(results) >= 1
        result = results[0]

        await dispatcher.publish(
            EXIT_PREDICTION_COMPLETED,
            {
                "complaint_id": complaint_id,
                "ring_id": result["ring_id"],
                "prediction_id": result["prediction_id"],
                "ranked_locations": result["ranked_locations"],
                "model_version_location": result["model_version_location"],
                "model_version_time": result["model_version_time"],
            },
        )

        assert len(calls) == 1
        assert calls[0]["complaint_id"] == complaint_id
        assert calls[0]["prediction_id"] == result["prediction_id"]
        assert calls[0]["jurisdiction_id"] is not None

        db.expire_all()
        prediction = db.query(Prediction).filter(Prediction.prediction_id == result["prediction_id"]).first()
        assert prediction.explanation
        assert prediction.explanation["top_factors"]
        assert prediction.explanation["plain_language"]
        assert isinstance(prediction.explanation["comparable_cases"], list)
        assert prediction.explanation["graph_path"]["path_complete"] is True
        assert prediction.explanation["graph_path"]["real_path"][0] == hash_pii(a)
    finally:
        dispatcher.unsubscribe(EXPLANATION_GENERATED, _probe)
        _cleanup(complaint_id, [a, b, c], device)


@neo4j_required
@pytest.mark.asyncio
async def test_repeated_exit_prediction_completed_events_are_idempotent(client, db, graph_prefix, exit_scorer_ground_truth):
    """Unlike Phase 2E's decay-based recompute, nothing in this
    computation depends on wall-clock time - the SAME feature snapshot
    against the SAME cached classifier must produce a byte-identical
    explanation, not merely an approximately-similar one."""
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        results = run_exit_scoring_for_complaint(db, complaint_id)
        result = results[0]
        payload = {
            "complaint_id": complaint_id,
            "ring_id": result["ring_id"],
            "prediction_id": result["prediction_id"],
            "ranked_locations": result["ranked_locations"],
            "model_version_location": result["model_version_location"],
            "model_version_time": result["model_version_time"],
        }

        await dispatcher.publish(EXIT_PREDICTION_COMPLETED, payload)
        prediction = db.query(Prediction).filter(Prediction.prediction_id == result["prediction_id"]).first()
        first_explanation = dict(prediction.explanation)

        await dispatcher.publish(EXIT_PREDICTION_COMPLETED, payload)
        db.expire_all()
        prediction = db.query(Prediction).filter(Prediction.prediction_id == result["prediction_id"]).first()
        second_explanation = dict(prediction.explanation)

        assert first_explanation == second_explanation
    finally:
        _cleanup(complaint_id, [a, b, c], device)


def _receive_with_timeout(websocket, timeout=2.0):
    result_queue: "queue.Queue" = queue.Queue(maxsize=1)

    def _worker():
        try:
            result_queue.put(("ok", websocket.receive_json()))
        except Exception as exc:
            result_queue.put(("error", exc))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    try:
        status, value = result_queue.get(timeout=timeout)
    except queue.Empty:
        return None
    if status == "error":
        raise value
    return value


@neo4j_required
def test_investigator_receives_explanation_generated_over_websocket(client, db, graph_prefix, exit_scorer_ground_truth):
    complaint_id, (a, b, c), device = _build_geolocated_ring(client, db, graph_prefix)
    try:
        results = run_exit_scoring_for_complaint(db, complaint_id)
        result = results[0]

        complaint = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
        token = make_token(UserRole.investigator, jurisdiction_id=complaint.jurisdiction_id)

        with client.websocket_connect(f"/v1/ws?token={token}") as websocket:
            import asyncio

            asyncio.run(
                dispatcher.publish(
                    EXIT_PREDICTION_COMPLETED,
                    {
                        "complaint_id": complaint_id,
                        "ring_id": result["ring_id"],
                        "prediction_id": result["prediction_id"],
                        "ranked_locations": result["ranked_locations"],
                        "model_version_location": result["model_version_location"],
                        "model_version_time": result["model_version_time"],
                    },
                )
            )

            message = _receive_with_timeout(websocket)
            assert message is not None, "investigator did not receive the explanation.generated push"
            assert message["type"] == "explanation.generated"
            assert message["complaint_id"] == complaint_id
            assert message["prediction_id"] == result["prediction_id"]
    finally:
        _cleanup(complaint_id, [a, b, c], device)


# --- API / RBAC (Neo4j-independent: a missing graph honestly yields path_complete=False) --


@pytest.fixture
def classifier_ground_truth(db):
    """Postgres-only synthetic ground truth (no Neo4j involved) so
    app/graph/exit_scorer.py::get_or_train_classifier can actually train
    (>=20 candidate rows required) - the API tests below need a real
    classifier to call shap.TreeExplainer against, not a fabricated one."""
    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    seed_exit_channels(db, jurisdiction_ids)
    seed_mule_rings(db, bank_ids, jurisdiction_ids, ring_count=15)


def _make_resolved_complaint(db, jurisdiction_id, status=ComplaintStatus.new):
    victim = Account(account_hash=f"explainer-api-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"EXPAPI-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=100000,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Explainer API test complaint",
        victim_account_id=victim.account_id,
        jurisdiction_id=jurisdiction_id,
        status=status,
    )
    db.add(complaint)
    db.flush()
    db.commit()
    return complaint


def _make_scored_prediction(db, complaint_id, exit_channel_ids=("ch-1", "ch-2")):
    # Must match app/graph/exit_scorer.py's real _FEATURE_ORDER exactly - this
    # is explained against the real, currently-cached XGBClassifier (trained
    # by the classifier_ground_truth fixture), which expects exactly this
    # many/these named features, not an arbitrary test-only schema.
    feature_order = list(_FEATURE_ORDER)
    by_channel = {
        cid: {
            "total_amount": 100000.0 + i * 1000,
            "velocity_km_per_hour": 5.0,
            "hop_count": 2.0,
            "structuring_flag": 0.0,
            "historical_incident_count": 1.0,
            "past_exits_via_channel": 0.0,
            "distance_km": 5.0 + i,
            "corridor_alignment_deg": 10.0,
            "hour_of_day": 14.0,
            "day_of_week": 2.0,
            "is_atm_cash": 1.0,
            "is_crypto_p2p": 0.0,
            "is_ecommerce_merchant": 0.0,
            "channel_attribute_score": 0.5,
        }
        for i, cid in enumerate(exit_channel_ids)
    }
    prediction = Prediction(
        complaint_id=complaint_id,
        generated_at=datetime.now(timezone.utc),
        exit_vector={"bearing_deg": 90.0, "distance_range_km": [1.0, 5.0], "confidence_cone_deg": 30.0, "exit_channel_type": "atm_cash"},
        ranked_locations=[
            {
                "exit_channel_id": cid,
                "h3_cell": "cell1",
                "channel_type": "atm_cash",
                "probability": 0.5,
                "time_window_min": [10.0, 30.0],
                "confidence_interval": [0.4, 0.6],
            }
            for cid in exit_channel_ids
        ],
        model_version_location="exit_channel_xgb-xgboost-test",
        feature_snapshot={"feature_order": feature_order, "ring_id": None, "by_exit_channel_id": by_channel},
    )
    db.add(prediction)
    db.commit()
    return prediction


def test_explanation_endpoint_returns_top_ranked_explanation_by_default(client, db, jurisdiction_a, classifier_ground_truth):
    complaint = _make_resolved_complaint(db, jurisdiction_a.jurisdiction_id)
    prediction = _make_scored_prediction(db, complaint.complaint_id)

    token = make_token(UserRole.auditor)
    response = client.get(f"/v1/complaints/{complaint.complaint_id}/explanation", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()

    assert body["available"] is True
    assert body["exit_channel_id"] == "ch-1"  # first in ranked_locations
    assert len(body["top_factors"]) > 0
    for factor in body["top_factors"]:
        assert set(factor.keys()) == {"feature", "weight", "direction"}
    assert body["plain_language"]
    assert body["graph_path"] is not None
    assert isinstance(body["comparable_cases"], list)


def test_explanation_endpoint_supports_explicit_exit_channel_id(client, db, jurisdiction_a, classifier_ground_truth):
    complaint = _make_resolved_complaint(db, jurisdiction_a.jurisdiction_id)
    prediction = _make_scored_prediction(db, complaint.complaint_id)

    token = make_token(UserRole.auditor)
    response = client.get(
        f"/v1/complaints/{complaint.complaint_id}/explanation",
        params={"exit_channel_id": "ch-2"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["exit_channel_id"] == "ch-2"


def test_explanation_endpoint_supports_explicit_prediction_id(client, db, jurisdiction_a, classifier_ground_truth):
    complaint = _make_resolved_complaint(db, jurisdiction_a.jurisdiction_id)
    prediction = _make_scored_prediction(db, complaint.complaint_id)

    token = make_token(UserRole.auditor)
    response = client.get(
        f"/v1/complaints/{complaint.complaint_id}/explanation",
        params={"prediction_id": prediction.prediction_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["available"] is True


def test_explanation_endpoint_honestly_unavailable_when_no_feature_snapshot(client, db, jurisdiction_a):
    complaint = _make_resolved_complaint(db, jurisdiction_a.jurisdiction_id)
    prediction = Prediction(
        complaint_id=complaint.complaint_id,
        generated_at=datetime.now(timezone.utc),
        ranked_locations=[{"exit_channel_id": "ch-1", "h3_cell": "cell1", "channel_type": "atm_cash", "probability": 0.5, "time_window_min": [1, 2], "confidence_interval": [0.1, 0.9]}],
    )
    db.add(prediction)
    db.commit()

    token = make_token(UserRole.auditor)
    response = client.get(f"/v1/complaints/{complaint.complaint_id}/explanation", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"]
    assert body["top_factors"] == []


def test_explanation_endpoint_404_when_no_prediction_exists(client, db, jurisdiction_a):
    complaint = _make_resolved_complaint(db, jurisdiction_a.jurisdiction_id)
    token = make_token(UserRole.auditor)
    response = client.get(f"/v1/complaints/{complaint.complaint_id}/explanation", headers=auth_headers(token))
    assert response.status_code == 404


def test_explanation_endpoint_requires_authentication(client, db, jurisdiction_a):
    complaint = _make_resolved_complaint(db, jurisdiction_a.jurisdiction_id)
    _make_scored_prediction(db, complaint.complaint_id)
    response = client.get(f"/v1/complaints/{complaint.complaint_id}/explanation")
    assert response.status_code == 401


def test_explanation_endpoint_denies_cross_jurisdiction_investigator(client, db, jurisdiction_a, jurisdiction_b):
    complaint = _make_resolved_complaint(db, jurisdiction_a.jurisdiction_id)
    _make_scored_prediction(db, complaint.complaint_id)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_b.jurisdiction_id)
    response = client.get(f"/v1/complaints/{complaint.complaint_id}/explanation", headers=auth_headers(token))
    assert response.status_code == 403


def test_explanation_endpoint_allows_same_jurisdiction_investigator(client, db, jurisdiction_a, classifier_ground_truth):
    complaint = _make_resolved_complaint(db, jurisdiction_a.jurisdiction_id)
    _make_scored_prediction(db, complaint.complaint_id)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get(f"/v1/complaints/{complaint.complaint_id}/explanation", headers=auth_headers(token))
    assert response.status_code == 200


def test_explanation_endpoint_404_for_unknown_complaint(client):
    token = make_token(UserRole.auditor)
    response = client.get(f"/v1/complaints/{uuid.uuid4()}/explanation", headers=auth_headers(token))
    assert response.status_code == 404
