"""
Integration/idempotency/API/RBAC/WebSocket tests for Phase 2G's Intervention
Optimizer - docs/AI_ML_ARCHITECTURE.md §7:

    POST /v1/complaints/{complaint_id}/optimize-deployment
    -> persists recommended_deployments row -> intervention.recommended
    -> WebSocket jurisdiction-scoped fan-out

This endpoint is caller-invoked (like complaint creation / transaction
ingestion), not a downstream pipeline-event reaction - so, unlike
2D/2E/2F's tests, there is no upstream event to publish through the real
dispatcher; the call itself IS the trigger. Neo4j-independent throughout:
the optimizer consumes only Prediction.ranked_locations and ExitChannel
rows, never touches the graph.
"""
import queue
import threading
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import (
    ComplaintStatus,
    ExitChannelType,
    FraudType,
    InstitutionType,
    InterventionActionType,
    UserRole,
)
from app.db.models.exit_channels import ExitChannel
from app.db.models.predictions import Prediction, RecommendedDeployment
from app.events.dispatcher import dispatcher
from app.events.topics import INTERVENTION_RECOMMENDED
from tests.conftest import auth_headers, make_token


def _make_complaint(db, jurisdiction_id, amount=200000):
    victim = Account(account_hash=f"opt-api-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"OPTAPI-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=amount,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Optimizer API test complaint",
        victim_account_id=victim.account_id,
        jurisdiction_id=jurisdiction_id,
        status=ComplaintStatus.new,
    )
    db.add(complaint)
    db.commit()
    return complaint


def _make_exit_channel(db, action_type, channel_type=ExitChannelType.atm_cash, lat=13.00, lon=80.00):
    channel = ExitChannel(
        channel_type=channel_type,
        external_ref="ATM-OPT-TEST",
        geo_lat=lat,
        geo_lon=lon,
        h3_cell="cell1",
        intervention_action_type=action_type,
    )
    db.add(channel)
    db.commit()
    return channel


def _make_prediction(db, complaint_id, ranked_locations):
    prediction = Prediction(
        complaint_id=complaint_id,
        generated_at=datetime.now(timezone.utc),
        ranked_locations=ranked_locations,
    )
    db.add(prediction)
    db.commit()
    return prediction


def _ranked(channel_id, probability, window=(10.0, 30.0)):
    return {
        "exit_channel_id": channel_id,
        "h3_cell": "cell1",
        "channel_type": "atm_cash",
        "probability": probability,
        "time_window_min": list(window),
        "confidence_interval": [max(0.0, probability - 0.1), min(1.0, probability + 0.1)],
    }


# --- coverage_maximization mode -----------------------------------------------


def test_optimize_deployment_coverage_maximization_end_to_end(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.7)])

    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
        json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()

    assert body["optimizer_mode"] == "coverage_maximization"
    assert len(body["assignment"]) == 1
    assert body["assignment"][0]["exit_channel_id"] == channel.channel_id
    assert body["assignment"][0]["team_id"] == "team-1"
    assert 0.0 <= body["expected_coverage_total"] <= 1.0

    deployment = db.query(RecommendedDeployment).filter(RecommendedDeployment.deployment_id == body["deployment_id"]).first()
    assert deployment is not None
    assert deployment.prediction_id is not None
    assert deployment.optimizer_mode.value == "coverage_maximization"
    assert deployment.status.value == "proposed"


def test_optimize_deployment_rejects_wrong_body_for_coverage_mode(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.7)])

    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
        json={"request_slot_count": 3},
        headers=auth_headers(token),
    )
    assert response.status_code == 400


# --- resource_allocation mode --------------------------------------------------


def test_optimize_deployment_resource_allocation_end_to_end(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id, amount=150000)
    channel_a = _make_exit_channel(db, InterventionActionType.exchange_freeze_request, ExitChannelType.crypto_p2p)
    channel_b = _make_exit_channel(db, InterventionActionType.exchange_freeze_request, ExitChannelType.crypto_p2p)
    _make_prediction(
        db,
        complaint.complaint_id,
        [_ranked(channel_a.channel_id, 0.6, window=(500.0, 600.0)), _ranked(channel_b.channel_id, 0.5, window=(2.0, 4.0))],
    )

    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
        json={"request_slot_count": 1},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()

    assert body["optimizer_mode"] == "resource_allocation"
    assert len(body["assignment"]) == 1
    assert body["assignment"][0]["priority_rank"] == 1
    assert body["assignment"][0]["exit_channel_id"] == channel_b.channel_id  # more urgent wins despite lower probability


def test_optimize_deployment_rejects_wrong_body_for_resource_allocation_mode(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.merchant_hold_request, ExitChannelType.ecommerce_merchant)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.5)])

    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
        json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
        headers=auth_headers(token),
    )
    assert response.status_code == 400


# --- idempotency / re-callability -----------------------------------------------


def test_repeated_calls_are_re_callable_and_produce_deterministic_values(client, db, jurisdiction_a):
    """API_CONTRACT.md §4: 're-callable with a different constraint; each
    call is a new deployment_id (never overwritten)'. Idempotent here means
    identical inputs -> identical computed values, not a deduplicated row."""
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.7)])

    token = make_token(UserRole.auditor)
    body_payload = {"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]}

    first = client.post(f"/v1/complaints/{complaint.complaint_id}/optimize-deployment", json=body_payload, headers=auth_headers(token))
    second = client.post(f"/v1/complaints/{complaint.complaint_id}/optimize-deployment", json=body_payload, headers=auth_headers(token))

    assert first.json()["deployment_id"] != second.json()["deployment_id"]
    assert first.json()["assignment"] == second.json()["assignment"]
    assert first.json()["expected_coverage_total"] == second.json()["expected_coverage_total"]
    assert first.json()["naive_baseline_coverage"] == second.json()["naive_baseline_coverage"]

    count = db.query(RecommendedDeployment).filter(RecommendedDeployment.prediction_id.isnot(None)).count()
    assert count >= 2  # both calls persisted their own row, never overwritten


# --- audit ----------------------------------------------------------------------


def test_optimize_deployment_appends_an_audit_event(client, db, jurisdiction_a):
    from app.db.models.audit import AuditEvent

    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.7)])

    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
        json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
        headers=auth_headers(token),
    )
    deployment_id = response.json()["deployment_id"]

    event = db.query(AuditEvent).filter(AuditEvent.event_type == "deployment.recommended", AuditEvent.subject_id == deployment_id).first()
    assert event is not None
    assert event.payload["complaint_id"] == complaint.complaint_id


# --- 404 / RBAC -------------------------------------------------------------------


def test_optimize_deployment_404_when_no_prediction_exists(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
        json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
        headers=auth_headers(token),
    )
    assert response.status_code == 404


def test_optimize_deployment_requires_authentication(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    response = client.post(f"/v1/complaints/{complaint.complaint_id}/optimize-deployment", json={"team_count": 1})
    assert response.status_code == 401


def test_optimize_deployment_denies_cross_jurisdiction_investigator(client, db, jurisdiction_a, jurisdiction_b):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.7)])

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_b.jurisdiction_id)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
        json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


def test_optimize_deployment_allows_same_jurisdiction_investigator(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.7)])

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
        json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
        headers=auth_headers(token),
    )
    assert response.status_code == 200


def test_optimize_deployment_404_for_unknown_complaint(client):
    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/complaints/{uuid.uuid4()}/optimize-deployment",
        json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
        headers=auth_headers(token),
    )
    assert response.status_code == 404


# --- event / WebSocket -----------------------------------------------------------


@pytest.mark.asyncio
async def test_optimize_deployment_publishes_intervention_recommended(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.7)])

    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(INTERVENTION_RECOMMENDED, _probe)
    try:
        token = make_token(UserRole.auditor)
        response = client.post(
            f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
            json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
            headers=auth_headers(token),
        )
        deployment_id = response.json()["deployment_id"]

        assert len(calls) == 1
        assert calls[0]["complaint_id"] == complaint.complaint_id
        assert calls[0]["deployment_id"] == deployment_id
        assert calls[0]["jurisdiction_id"] == jurisdiction_a.jurisdiction_id
    finally:
        dispatcher.unsubscribe(INTERVENTION_RECOMMENDED, _probe)


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


def test_investigator_receives_intervention_recommended_over_websocket(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _make_prediction(db, complaint.complaint_id, [_ranked(channel.channel_id, 0.7)])

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)

    with client.websocket_connect(f"/v1/ws?token={token}") as websocket:
        service_token_for_post = make_token(UserRole.auditor)
        response = client.post(
            f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
            json={"team_count": 1, "team_locations": [{"lat": 12.9, "lon": 79.9}]},
            headers=auth_headers(service_token_for_post),
        )
        deployment_id = response.json()["deployment_id"]

        message = _receive_with_timeout(websocket)
        assert message is not None, "investigator did not receive the intervention.recommended push"
        assert message["type"] == "intervention.recommended"
        assert message["complaint_id"] == complaint.complaint_id
        assert message["deployment_id"] == deployment_id
