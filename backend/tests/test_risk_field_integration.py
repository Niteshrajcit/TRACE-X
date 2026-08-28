"""
Integration/idempotency/API tests for Phase 2E's wired pipeline -
docs/AI_ML_ARCHITECTURE.md §5:

    transaction.ingested -> risk-field recomputation -> risk_field.updated
    -> WebSocket jurisdiction-scoped fan-out
    GET /v1/jurisdictions/{jurisdiction_id}/risk-field?at=<timestamp>

These exercise the real, already-registered dispatcher (app/main.py's
startup wires register_risk_field_handlers() onto the same process-wide
singleton the `client` fixture starts) and the real HTTP endpoint - not
hand-simulated calls. No Neo4j involved anywhere in this file: the
decision-frozen trigger is transaction.ingested itself, so these publish
that event directly against a Complaint/Prediction pair already persisted
in Postgres, exactly like app/graph/handlers.py's own
_run_risk_field_recompute_sync reads them.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus, FraudType, InstitutionType, UserRole
from app.db.models.predictions import Prediction
from app.events.dispatcher import dispatcher
from app.events.topics import RISK_FIELD_UPDATED, TRANSACTION_INGESTED
from app.graph.risk_field import decay, get_cached_field, reset_cache
from tests.conftest import auth_headers, make_token


@pytest.fixture(autouse=True)
def _fresh_cache():
    reset_cache()
    yield
    reset_cache()


def _make_complaint(db, jurisdiction_id, status=ComplaintStatus.new):
    victim = Account(account_hash=f"riskfield-int-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"RFI-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=100000,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Risk field integration test complaint",
        victim_account_id=victim.account_id,
        jurisdiction_id=jurisdiction_id,
        status=status,
    )
    db.add(complaint)
    db.flush()
    db.commit()
    return complaint


def _make_prediction(db, complaint_id, ranked_locations, generated_at):
    prediction = Prediction(complaint_id=complaint_id, generated_at=generated_at, ranked_locations=ranked_locations)
    db.add(prediction)
    db.commit()
    return prediction


@pytest.mark.asyncio
async def test_event_pipeline_transaction_ingested_triggers_risk_field_updated(client, db, jurisdiction_a):
    """Publishes TRANSACTION_INGESTED through the real, already-registered
    dispatcher - exercises app/graph/handlers.py's actual
    _on_transaction_ingested_for_risk_field, not a hand-simulated call."""
    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(RISK_FIELD_UPDATED, _probe)
    try:
        complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
        now = datetime.now(timezone.utc)
        _make_prediction(db, complaint.complaint_id, [{"h3_cell": "cellINT", "probability": 0.6}], now)

        await dispatcher.publish(TRANSACTION_INGESTED, {"txn_id": "txn-1", "complaint_id": complaint.complaint_id})

        assert len(calls) == 1
        assert calls[0]["jurisdiction_id"] == jurisdiction_a.jurisdiction_id
        assert calls[0]["changed_cells"] == ["cellINT"]

        cached = get_cached_field(jurisdiction_a.jurisdiction_id)
        assert cached["cellINT"] == pytest.approx(0.6)
    finally:
        dispatcher.unsubscribe(RISK_FIELD_UPDATED, _probe)


@pytest.mark.asyncio
async def test_transaction_ingested_without_a_prediction_yet_publishes_nothing(client, db, jurisdiction_a):
    """[Phase 2E decision freeze] The trigger is transaction.ingested itself
    - most transactions arrive before this complaint has any Prediction with
    ranked_locations yet (ring/corridor/exit-scoring for this specific
    transaction hasn't run). A genuine, disclosed timing characteristic:
    zero touched cells, zero publish, not an error."""
    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(RISK_FIELD_UPDATED, _probe)
    try:
        complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)

        await dispatcher.publish(TRANSACTION_INGESTED, {"txn_id": "txn-2", "complaint_id": complaint.complaint_id})

        assert calls == []
        assert get_cached_field(jurisdiction_a.jurisdiction_id) == {}
    finally:
        dispatcher.unsubscribe(RISK_FIELD_UPDATED, _probe)


@pytest.mark.asyncio
async def test_transaction_ingested_recompute_is_idempotent(client, db, jurisdiction_a):
    """'Idempotent' here means safe to call repeatedly - the cache never
    duplicates or accumulates the same contribution twice, and converges to
    the correct current value each time. It does NOT mean bit-identical
    floats across two calls: each recompute uses wall-clock now() for decay,
    so a few microseconds of real elapsed time between the two publishes
    legitimately changes the decayed value by a negligible amount."""
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    now = datetime.now(timezone.utc)
    _make_prediction(db, complaint.complaint_id, [{"h3_cell": "cellIdem", "probability": 0.4}], now)

    await dispatcher.publish(TRANSACTION_INGESTED, {"txn_id": "txn-3a", "complaint_id": complaint.complaint_id})
    field_after_first = get_cached_field(jurisdiction_a.jurisdiction_id)

    await dispatcher.publish(TRANSACTION_INGESTED, {"txn_id": "txn-3b", "complaint_id": complaint.complaint_id})
    field_after_second = get_cached_field(jurisdiction_a.jurisdiction_id)

    assert field_after_first.keys() == field_after_second.keys()
    assert field_after_second["cellIdem"] == pytest.approx(field_after_first["cellIdem"], rel=1e-4)
    assert field_after_second["cellIdem"] == pytest.approx(0.4, abs=1e-3)  # no duplication/accumulation


def test_risk_field_endpoint_bootstraps_cold_cache_and_matches_direct_computation(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    now = datetime.now(timezone.utc)
    _make_prediction(db, complaint.complaint_id, [{"h3_cell": "cellAPI", "probability": 0.55}], now)

    token = make_token(UserRole.auditor)
    response = client.get(f"/v1/jurisdictions/{jurisdiction_a.jurisdiction_id}/risk-field", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()

    cells = {c["h3_cell"]: c["score"] for c in body["h3_cells"]}
    assert "cellAPI" in cells
    assert cells["cellAPI"] == pytest.approx(0.55, abs=1e-3)
    assert body["generated_for"] is not None


def test_risk_field_endpoint_historical_replay_via_at_param(client, db, jurisdiction_a):
    t0 = datetime.now(timezone.utc) - timedelta(hours=4)
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    _make_prediction(db, complaint.complaint_id, [{"h3_cell": "cellReplay", "probability": 0.8}], t0)

    at = (t0 + timedelta(hours=2)).isoformat()
    token = make_token(UserRole.auditor)
    response = client.get(
        f"/v1/jurisdictions/{jurisdiction_a.jurisdiction_id}/risk-field",
        params={"at": at},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()

    cells = {c["h3_cell"]: c["score"] for c in body["h3_cells"]}
    expected = 0.8 * decay(2.0, 6.0)
    assert cells["cellReplay"] == pytest.approx(expected, abs=1e-3)

    # Replay must never write into the live cache.
    assert get_cached_field(jurisdiction_a.jurisdiction_id) == {}


def test_risk_field_endpoint_denies_cross_jurisdiction_investigator(client, db, jurisdiction_a, jurisdiction_b):
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_b.jurisdiction_id)
    response = client.get(f"/v1/jurisdictions/{jurisdiction_a.jurisdiction_id}/risk-field", headers=auth_headers(token))
    assert response.status_code == 403


def test_risk_field_endpoint_allows_same_jurisdiction_investigator(client, db, jurisdiction_a):
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get(f"/v1/jurisdictions/{jurisdiction_a.jurisdiction_id}/risk-field", headers=auth_headers(token))
    assert response.status_code == 200


def test_risk_field_endpoint_404_for_unknown_jurisdiction(client):
    token = make_token(UserRole.auditor)
    response = client.get(f"/v1/jurisdictions/{uuid.uuid4()}/risk-field", headers=auth_headers(token))
    assert response.status_code == 404


def test_risk_field_endpoint_requires_authentication(client, jurisdiction_a):
    response = client.get(f"/v1/jurisdictions/{jurisdiction_a.jurisdiction_id}/risk-field")
    assert response.status_code == 401
