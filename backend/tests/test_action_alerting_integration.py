"""
Integration/RBAC/event/WebSocket tests for Action & Alerting's real
event-driven flow:

    POST /v1/deployments/{id}/decision (approved)
    -> intervention.approved -> app/action/handlers.py -> real dispatch
    -> action.dispatched -> WebSocket

and outcome recording:

    POST /v1/deployments/{id}/outcome -> outcome.recorded / feedback.created

Neo4j-independent throughout.
"""
import asyncio
import queue
import threading
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import (
    ComplaintStatus,
    DeploymentStatus,
    ExitChannelType,
    FraudType,
    InstitutionType,
    InterventionActionType,
    OptimizerMode,
    OutcomeResult,
    UserRole,
)
from app.db.models.exit_channels import ExitChannel
from app.db.models.ml_ops import FeatureSnapshot
from app.db.models.predictions import Alert, InterventionOutcome, Prediction, RecommendedDeployment
from app.db.models.audit import AuditEvent
from app.events.dispatcher import dispatcher
from app.events.topics import ACTION_DISPATCHED, FEEDBACK_CREATED, OUTCOME_RECORDED
from tests.conftest import auth_headers, make_token


def _make_complaint(db, jurisdiction_id):
    victim = Account(account_hash=f"action-api-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"ACTAPI-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=140000,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Action & Alerting API test complaint",
        victim_account_id=victim.account_id,
        jurisdiction_id=jurisdiction_id,
        status=ComplaintStatus.new,
    )
    db.add(complaint)
    db.commit()
    return complaint


def _make_deployment_with_snapshot(db, complaint_id, status=DeploymentStatus.proposed):
    """Includes a real feature_snapshot (Phase 2F/2G shape) so outcome
    recording's FeatureSnapshot-writing path is genuinely exercised."""
    channel = ExitChannel(
        channel_type=ExitChannelType.atm_cash,
        external_ref="ATM-ACTAPI-TEST",
        geo_lat=13.0,
        geo_lon=80.0,
        h3_cell="cell1",
        intervention_action_type=InterventionActionType.physical_team_deployment,
    )
    db.add(channel)
    db.flush()
    feature_order = ["total_amount", "hop_count", "distance_km"]
    prediction = Prediction(
        complaint_id=complaint_id,
        generated_at=datetime.now(timezone.utc),
        ranked_locations=[
            {
                "exit_channel_id": channel.channel_id,
                "h3_cell": "cell1",
                "channel_type": "atm_cash",
                "probability": 0.65,
                "time_window_min": [15.0, 40.0],
                "confidence_interval": [0.4, 0.8],
            }
        ],
        feature_snapshot={
            "feature_order": feature_order,
            "ring_id": None,
            "by_exit_channel_id": {channel.channel_id: {"total_amount": 140000.0, "hop_count": 2.0, "distance_km": 3.0}},
        },
    )
    db.add(prediction)
    db.flush()
    deployment = RecommendedDeployment(
        prediction_id=prediction.prediction_id,
        optimizer_mode=OptimizerMode.coverage_maximization,
        assignment=[{"team_id": "team-1", "exit_channel_id": channel.channel_id, "expected_coverage": 1.0, "travel_time_min": 5.0}],
        expected_coverage_total=1.0,
        naive_baseline_coverage=1.0,
        status=status,
    )
    db.add(deployment)
    db.commit()
    return deployment


# --- decision -> dispatch (event-driven) --------------------------------------


def test_approving_a_deployment_real_dispatches_and_persists_an_alert(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/decision",
        json={"decision": "approved", "justification": "Dispatch integration check."},
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    alert = db.query(Alert).filter(Alert.prediction_id == deployment.prediction_id).first()
    assert alert is not None
    assert alert.delivered_at is not None
    assert alert.payload["deployment_id"] == deployment.deployment_id

    audit_event = db.query(AuditEvent).filter(AuditEvent.event_type == "action.dispatched", AuditEvent.subject_id == alert.alert_id).first()
    assert audit_event is not None


def test_rejecting_a_deployment_never_dispatches(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    client.post(
        f"/v1/deployments/{deployment.deployment_id}/decision",
        json={"decision": "rejected", "justification": "No dispatch should follow this."},
        headers=auth_headers(token),
    )

    assert db.query(Alert).filter(Alert.prediction_id == deployment.prediction_id).count() == 0


@pytest.mark.asyncio
async def test_approval_publishes_action_dispatched(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id)

    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(ACTION_DISPATCHED, _probe)
    try:
        token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
        response = client.post(
            f"/v1/deployments/{deployment.deployment_id}/decision",
            json={"decision": "approved", "justification": "Event check."},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert len(calls) == 1
        assert calls[0]["complaint_id"] == complaint.complaint_id
        assert calls[0]["deployment_id"] == deployment.deployment_id
        assert calls[0]["delivered"] is True
        assert calls[0]["jurisdiction_id"] == jurisdiction_a.jurisdiction_id
    finally:
        dispatcher.unsubscribe(ACTION_DISPATCHED, _probe)


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
        status_, value = result_queue.get(timeout=timeout)
    except queue.Empty:
        return None
    if status_ == "error":
        raise value
    return value


def test_investigator_receives_action_dispatched_over_websocket(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id)

    watcher_token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    with client.websocket_connect(f"/v1/ws?token={watcher_token}") as websocket:
        decider_token = make_token(UserRole.supervisor, jurisdiction_id=jurisdiction_a.jurisdiction_id)
        client.post(
            f"/v1/deployments/{deployment.deployment_id}/decision",
            json={"decision": "approved", "justification": "WS delivery check."},
            headers=auth_headers(decider_token),
        )

        # Decision and dispatch both fire within the same request cycle
        # (intervention.approved, then action.dispatched) - drain messages
        # until the one this test cares about, rather than assuming it's
        # the very first push.
        found = None
        for _ in range(5):
            message = _receive_with_timeout(websocket)
            if message is None:
                break
            if message["type"] == "action.dispatched":
                found = message
                break
        assert found is not None, "investigator did not receive the action.dispatched push"
        assert found["deployment_id"] == deployment.deployment_id


# --- outcome ------------------------------------------------------------------------


def test_record_outcome_requires_approved_deployment(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id, status=DeploymentStatus.proposed)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/outcome",
        json={"result": "cash_out_prevented", "notes": "Should not be allowed - not approved."},
        headers=auth_headers(token),
    )
    assert response.status_code == 409


def test_record_outcome_success_writes_outcome_and_feature_snapshot(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id, status=DeploymentStatus.approved)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/outcome",
        json={"result": "cash_out_prevented", "notes": "Team arrived in time."},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "cash_out_prevented"
    assert body["feature_snapshot_id"] is not None

    outcome = db.query(InterventionOutcome).filter(InterventionOutcome.deployment_id == deployment.deployment_id).first()
    assert outcome is not None
    assert outcome.result == OutcomeResult.cash_out_prevented

    snapshot = db.query(FeatureSnapshot).filter(FeatureSnapshot.snapshot_id == body["feature_snapshot_id"]).first()
    assert snapshot is not None
    assert snapshot.feature_vector == {"total_amount": 140000.0, "hop_count": 2.0, "distance_km": 3.0}
    assert snapshot.label["result"] == "cash_out_prevented"


def test_record_outcome_twice_is_a_conflict(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id, status=DeploymentStatus.approved)
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)

    first = client.post(
        f"/v1/deployments/{deployment.deployment_id}/outcome",
        json={"result": "cash_out_prevented"},
        headers=auth_headers(token),
    )
    assert first.status_code == 200
    second = client.post(
        f"/v1/deployments/{deployment.deployment_id}/outcome",
        json={"result": "no_activity"},
        headers=auth_headers(token),
    )
    assert second.status_code == 409


def test_record_outcome_auditor_forbidden(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id, status=DeploymentStatus.approved)
    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/outcome",
        json={"result": "cash_out_prevented"},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


def test_record_outcome_cross_jurisdiction_forbidden(client, db, jurisdiction_a, jurisdiction_b):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id, status=DeploymentStatus.approved)
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_b.jurisdiction_id)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/outcome",
        json={"result": "cash_out_prevented"},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_outcome_publishes_outcome_recorded_and_feedback_created(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment_with_snapshot(db, complaint.complaint_id, status=DeploymentStatus.approved)

    outcome_calls, feedback_calls = [], []

    async def _outcome_probe(payload: dict) -> None:
        outcome_calls.append(payload)

    async def _feedback_probe(payload: dict) -> None:
        feedback_calls.append(payload)

    dispatcher.subscribe(OUTCOME_RECORDED, _outcome_probe)
    dispatcher.subscribe(FEEDBACK_CREATED, _feedback_probe)
    try:
        token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
        client.post(
            f"/v1/deployments/{deployment.deployment_id}/outcome",
            json={"result": "funds_recovered_full"},
            headers=auth_headers(token),
        )
        assert len(outcome_calls) == 1
        assert outcome_calls[0]["result"] == "funds_recovered_full"
        assert len(feedback_calls) == 1
        assert feedback_calls[0]["complaint_id"] == complaint.complaint_id
    finally:
        dispatcher.unsubscribe(OUTCOME_RECORDED, _outcome_probe)
        dispatcher.unsubscribe(FEEDBACK_CREATED, _feedback_probe)


def test_outcome_honestly_omits_feature_snapshot_when_none_persisted(client, db, jurisdiction_a):
    """A deployment predating Phase 2F's feature-snapshot persistence -
    outcome recording must still succeed, just without a fabricated
    feature_snapshot_id."""
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    channel = ExitChannel(
        channel_type=ExitChannelType.atm_cash,
        external_ref="ATM-NO-SNAPSHOT",
        geo_lat=13.0, geo_lon=80.0, h3_cell="cell1",
        intervention_action_type=InterventionActionType.physical_team_deployment,
    )
    db.add(channel)
    db.flush()
    prediction = Prediction(
        complaint_id=complaint.complaint_id,
        generated_at=datetime.now(timezone.utc),
        ranked_locations=[{"exit_channel_id": channel.channel_id, "h3_cell": "cell1", "channel_type": "atm_cash", "probability": 0.5, "time_window_min": [10, 20], "confidence_interval": [0.3, 0.7]}],
    )
    db.add(prediction)
    db.flush()
    deployment = RecommendedDeployment(
        prediction_id=prediction.prediction_id,
        optimizer_mode=OptimizerMode.coverage_maximization,
        assignment=[{"team_id": "team-1", "exit_channel_id": channel.channel_id, "expected_coverage": 1.0, "travel_time_min": 5.0}],
        expected_coverage_total=1.0, naive_baseline_coverage=1.0,
        status=DeploymentStatus.approved,
    )
    db.add(deployment)
    db.commit()

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/outcome",
        json={"result": "no_activity"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["feature_snapshot_id"] is None
