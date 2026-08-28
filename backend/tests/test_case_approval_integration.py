"""
Integration/API/RBAC/idempotency/audit/event/WebSocket tests for the Case &
Approval stage - docs/API_CONTRACT.md §2/§4:

    POST /v1/complaints/{complaint_id}/assign
    POST /v1/complaints/{complaint_id}/close
    GET  /v1/complaints?status=&assigned_to_me=
    GET  /v1/complaints/{complaint_id}  (case-detail aggregate fields)
    POST /v1/deployments/{deployment_id}/decision
      -> intervention.approved | intervention.rejected -> WebSocket

Neo4j-independent throughout (pure Postgres/RBAC/event-dispatcher work).
"""
import queue
import threading
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models.accounts import Account
from app.db.models.audit import AuditEvent
from app.db.models.complaints import Complaint
from app.db.models.enums import (
    ComplaintStatus,
    DeploymentStatus,
    ExitChannelType,
    FraudType,
    InstitutionType,
    InterventionActionType,
    OptimizerMode,
    UserRole,
)
from app.db.models.exit_channels import ExitChannel
from app.db.models.predictions import Prediction, RecommendedDeployment
from app.db.models.users import User
from app.events.dispatcher import dispatcher
from app.events.topics import APPROVAL_REQUIRED, INTERVENTION_APPROVED, INTERVENTION_REJECTED
from tests.conftest import auth_headers, make_token


def _make_user(db, role, jurisdiction_id):
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="not-a-real-hash",
        role=role,
        jurisdiction_id=jurisdiction_id,
    )
    db.add(user)
    db.commit()
    return user


def _make_complaint(db, jurisdiction_id, status=ComplaintStatus.new):
    victim = Account(account_hash=f"case-api-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"CASEAPI-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=100000,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Case & Approval API test complaint",
        victim_account_id=victim.account_id,
        jurisdiction_id=jurisdiction_id,
        status=status,
    )
    db.add(complaint)
    db.commit()
    return complaint


def _make_deployment(db, complaint_id, status=DeploymentStatus.proposed):
    channel = ExitChannel(
        channel_type=ExitChannelType.atm_cash,
        external_ref="ATM-CASE-TEST",
        geo_lat=13.0,
        geo_lon=80.0,
        h3_cell="cell1",
        intervention_action_type=InterventionActionType.physical_team_deployment,
    )
    db.add(channel)
    db.flush()
    prediction = Prediction(
        complaint_id=complaint_id,
        generated_at=datetime.now(timezone.utc),
        ranked_locations=[
            {
                "exit_channel_id": channel.channel_id,
                "h3_cell": "cell1",
                "channel_type": "atm_cash",
                "probability": 0.6,
                "time_window_min": [10.0, 30.0],
                "confidence_interval": [0.4, 0.7],
            }
        ],
    )
    db.add(prediction)
    db.flush()
    deployment = RecommendedDeployment(
        prediction_id=prediction.prediction_id,
        optimizer_mode=OptimizerMode.coverage_maximization,
        team_count=1,
        assignment=[{"team_id": "team-1", "exit_channel_id": channel.channel_id, "expected_coverage": 1.0, "travel_time_min": 10.0}],
        expected_coverage_total=1.0,
        naive_baseline_coverage=1.0,
        status=status,
    )
    db.add(deployment)
    db.commit()
    return deployment


# --- assign ---------------------------------------------------------------------


def test_assign_case_via_api(client, db, jurisdiction_a):
    investigator = _make_user(db, UserRole.investigator, jurisdiction_a.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)

    token = make_token(UserRole.supervisor, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/assign",
        json={"investigator_id": investigator.user_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["assigned_investigator_id"] == investigator.user_id

    db.refresh(complaint)
    assert complaint.assigned_investigator_id == investigator.user_id


def test_assign_case_rejects_wrong_jurisdiction_target(client, db, jurisdiction_a, jurisdiction_b):
    investigator = _make_user(db, UserRole.investigator, jurisdiction_b.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)

    token = make_token(UserRole.supervisor, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/assign",
        json={"investigator_id": investigator.user_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 400


def test_assign_case_auditor_forbidden(client, db, jurisdiction_a):
    investigator = _make_user(db, UserRole.investigator, jurisdiction_a.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)

    token = make_token(UserRole.auditor)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/assign",
        json={"investigator_id": investigator.user_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


def test_assign_case_cross_jurisdiction_caller_forbidden(client, db, jurisdiction_a, jurisdiction_b):
    investigator = _make_user(db, UserRole.investigator, jurisdiction_a.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_b.jurisdiction_id)
    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/assign",
        json={"investigator_id": investigator.user_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


def test_assign_case_appends_audit_event(client, db, jurisdiction_a):
    investigator = _make_user(db, UserRole.investigator, jurisdiction_a.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)

    token = make_token(UserRole.supervisor, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    client.post(
        f"/v1/complaints/{complaint.complaint_id}/assign",
        json={"investigator_id": investigator.user_id},
        headers=auth_headers(token),
    )

    event = db.query(AuditEvent).filter(AuditEvent.event_type == "case.assigned", AuditEvent.subject_id == complaint.complaint_id).first()
    assert event is not None
    assert event.payload["investigator_id"] == investigator.user_id


# --- close ------------------------------------------------------------------------


def test_close_case_via_api(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)

    response = client.post(
        f"/v1/complaints/{complaint.complaint_id}/close",
        json={"reason": "Determined not to be actionable fraud."},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "closed"


def test_close_case_twice_is_a_conflict(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)

    client.post(f"/v1/complaints/{complaint.complaint_id}/close", json={"reason": "First close."}, headers=auth_headers(token))
    second = client.post(f"/v1/complaints/{complaint.complaint_id}/close", json={"reason": "Second close."}, headers=auth_headers(token))
    assert second.status_code == 409


def test_close_case_auditor_forbidden(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    token = make_token(UserRole.auditor)
    response = client.post(f"/v1/complaints/{complaint.complaint_id}/close", json={"reason": "Trying as auditor."}, headers=auth_headers(token))
    assert response.status_code == 403


# --- list/detail filters -----------------------------------------------------------


def test_list_complaints_filters_by_status(client, db, jurisdiction_a):
    open_complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id, status=ComplaintStatus.new)
    closed_complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id, status=ComplaintStatus.closed)

    token = make_token(UserRole.auditor)
    response = client.get("/v1/complaints", params={"status": "closed"}, headers=auth_headers(token))
    assert response.status_code == 200
    ids = {c["complaint_id"] for c in response.json()}
    assert closed_complaint.complaint_id in ids
    assert open_complaint.complaint_id not in ids


def test_list_complaints_assigned_to_me_filter(client, db, jurisdiction_a):
    investigator = _make_user(db, UserRole.investigator, jurisdiction_a.jurisdiction_id)
    mine = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    mine.assigned_investigator_id = investigator.user_id
    db.commit()
    not_mine = _make_complaint(db, jurisdiction_a.jurisdiction_id)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id, sub=investigator.user_id)
    response = client.get("/v1/complaints", params={"assigned_to_me": True}, headers=auth_headers(token))
    ids = {c["complaint_id"] for c in response.json()}
    assert mine.complaint_id in ids
    assert not_mine.complaint_id not in ids


def test_case_detail_includes_deployment_history(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    token = make_token(UserRole.auditor)
    response = client.get(f"/v1/complaints/{complaint.complaint_id}", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["graph_summary"] == {"ring_count": 0, "total_members": 0}
    deployment_ids = {d["deployment_id"] for d in body["deployment_history"]}
    assert deployment.deployment_id in deployment_ids


# --- decision (approve/reject) ------------------------------------------------------


def test_decision_approve_via_api(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/decision",
        json={"decision": "approved", "justification": "Coverage looks solid, approving deployment."},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["decided_by"] is not None
    assert body["decided_at"] is not None

    db.refresh(deployment)
    assert deployment.status == DeploymentStatus.approved


def test_decision_reject_via_api(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    token = make_token(UserRole.supervisor, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/decision",
        json={"decision": "rejected", "justification": "Insufficient evidence to deploy a team."},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_decision_cannot_be_changed_once_made(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)

    first = client.post(
        f"/v1/deployments/{deployment.deployment_id}/decision",
        json={"decision": "approved", "justification": "First decision."},
        headers=auth_headers(token),
    )
    assert first.status_code == 200

    second = client.post(
        f"/v1/deployments/{deployment.deployment_id}/decision",
        json={"decision": "rejected", "justification": "Trying to change my mind."},
        headers=auth_headers(token),
    )
    assert second.status_code == 409

    db.refresh(deployment)
    assert deployment.status == DeploymentStatus.approved  # unchanged - never silently overwritten


def test_decision_forbidden_for_auditor_and_admin(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    for role in (UserRole.auditor, UserRole.admin):
        token = make_token(role)
        response = client.post(
            f"/v1/deployments/{deployment.deployment_id}/decision",
            json={"decision": "approved", "justification": "Should not be allowed."},
            headers=auth_headers(token),
        )
        assert response.status_code == 403, f"role {role} should not be able to decide"


def test_decision_cross_jurisdiction_investigator_forbidden(client, db, jurisdiction_a, jurisdiction_b):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_b.jurisdiction_id)
    response = client.post(
        f"/v1/deployments/{deployment.deployment_id}/decision",
        json={"decision": "approved", "justification": "Should not be allowed cross-jurisdiction."},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


def test_decision_404_for_unknown_deployment(client):
    token = make_token(UserRole.investigator)
    response = client.post(
        f"/v1/deployments/{uuid.uuid4()}/decision",
        json={"decision": "approved", "justification": "Does not exist."},
        headers=auth_headers(token),
    )
    assert response.status_code == 404


def test_decision_appends_audit_event(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)

    client.post(
        f"/v1/deployments/{deployment.deployment_id}/decision",
        json={"decision": "approved", "justification": "Audit trail check."},
        headers=auth_headers(token),
    )

    event = db.query(AuditEvent).filter(AuditEvent.event_type == "intervention.approved", AuditEvent.subject_id == deployment.deployment_id).first()
    assert event is not None
    assert event.payload["justification"] == "Audit trail check."


# --- events / WebSocket --------------------------------------------------------------


@pytest.mark.asyncio
async def test_decision_publishes_intervention_approved(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(INTERVENTION_APPROVED, _probe)
    try:
        token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
        client.post(
            f"/v1/deployments/{deployment.deployment_id}/decision",
            json={"decision": "approved", "justification": "Event check."},
            headers=auth_headers(token),
        )
        assert len(calls) == 1
        assert calls[0]["complaint_id"] == complaint.complaint_id
        assert calls[0]["deployment_id"] == deployment.deployment_id
        assert calls[0]["decision"] == "approved"
    finally:
        dispatcher.unsubscribe(INTERVENTION_APPROVED, _probe)


@pytest.mark.asyncio
async def test_decision_publishes_intervention_rejected(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(INTERVENTION_REJECTED, _probe)
    try:
        token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
        client.post(
            f"/v1/deployments/{deployment.deployment_id}/decision",
            json={"decision": "rejected", "justification": "Event check reject."},
            headers=auth_headers(token),
        )
        assert len(calls) == 1
        assert calls[0]["decision"] == "rejected"
    finally:
        dispatcher.unsubscribe(INTERVENTION_REJECTED, _probe)


@pytest.mark.asyncio
async def test_optimize_deployment_publishes_approval_required(client, db, jurisdiction_a):
    """[Additive Phase 2G touch] Confirms the one new line added to the
    existing optimize-deployment endpoint - never that endpoint's own
    already-verified response/persistence behavior, which is untouched."""
    channel = ExitChannel(
        channel_type=ExitChannelType.atm_cash,
        external_ref="ATM-APR-TEST",
        geo_lat=13.0,
        geo_lon=80.0,
        h3_cell="cell1",
        intervention_action_type=InterventionActionType.physical_team_deployment,
    )
    db.add(channel)
    db.flush()
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    prediction = Prediction(
        complaint_id=complaint.complaint_id,
        generated_at=datetime.now(timezone.utc),
        ranked_locations=[
            {"exit_channel_id": channel.channel_id, "h3_cell": "cell1", "channel_type": "atm_cash", "probability": 0.6, "time_window_min": [10.0, 30.0], "confidence_interval": [0.4, 0.7]}
        ],
    )
    db.add(prediction)
    db.commit()

    calls = []

    async def _probe(payload: dict) -> None:
        calls.append(payload)

    dispatcher.subscribe(APPROVAL_REQUIRED, _probe)
    try:
        token = make_token(UserRole.auditor)
        response = client.post(
            f"/v1/complaints/{complaint.complaint_id}/optimize-deployment",
            json={"team_count": 1, "team_locations": [{"lat": 13.0, "lon": 80.0}]},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert len(calls) == 1
        assert calls[0]["deployment_id"] == response.json()["deployment_id"]
    finally:
        dispatcher.unsubscribe(APPROVAL_REQUIRED, _probe)


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


def test_investigator_receives_intervention_approved_over_websocket(client, db, jurisdiction_a):
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    watcher_token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    with client.websocket_connect(f"/v1/ws?token={watcher_token}") as websocket:
        decider_token = make_token(UserRole.supervisor, jurisdiction_id=jurisdiction_a.jurisdiction_id)
        client.post(
            f"/v1/deployments/{deployment.deployment_id}/decision",
            json={"decision": "approved", "justification": "WS delivery check."},
            headers=auth_headers(decider_token),
        )

        message = _receive_with_timeout(websocket)
        assert message is not None, "investigator did not receive the intervention.approved push"
        assert message["type"] == "intervention.approved"
        assert message["deployment_id"] == deployment.deployment_id
