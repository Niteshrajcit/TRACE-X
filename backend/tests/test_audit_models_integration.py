"""
Integration/RBAC/jurisdiction tests for the Audit & Model registry read
surfaces - docs/API_CONTRACT.md §5:

    GET /v1/audit/events?subject_id=&subject_type=&from=&to=
    GET /v1/audit/verify-chain?from_seq=&to_seq=
    GET /v1/models
"""
import uuid
from datetime import datetime, timezone

from app.db.models.audit import AuditEvent
from app.db.models.enums import ModelStage, UserRole
from app.db.models.ml_ops import ModelRegistryEntry
from tests.conftest import auth_headers, make_token, valid_complaint_payload


def _make_complaint(client, jurisdiction_a):
    """Submits through the real POST /v1/complaints endpoint (rather than
    constructing a Complaint row directly) specifically because this test
    file needs a REAL complaint.created audit event to exist - a direct
    ORM insert never calls append_audit_event."""
    response = client.post(
        "/v1/complaints",
        json=valid_complaint_payload(jurisdiction_hint="Chennai", victim_account_number=f"AUDIT-{uuid.uuid4().hex[:10]}"),
    )
    assert response.status_code == 201
    complaint_id = response.json()["complaint_id"]
    return complaint_id, jurisdiction_a.jurisdiction_id


# --- GET /v1/audit/events -----------------------------------------------------------


def test_auditor_can_list_all_events_without_a_subject_filter(client, db, jurisdiction_a):
    _make_complaint(client, jurisdiction_a)
    token = make_token(UserRole.auditor)
    response = client.get("/v1/audit/events", headers=auth_headers(token))
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_investigator_requires_subject_id_and_type(client, db, jurisdiction_a):
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get("/v1/audit/events", headers=auth_headers(token))
    assert response.status_code == 400


def test_investigator_can_view_audit_for_own_jurisdiction_complaint(client, db, jurisdiction_a):
    complaint_id, _ = _make_complaint(client, jurisdiction_a)
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get(
        "/v1/audit/events",
        params={"subject_id": complaint_id, "subject_type": "complaint"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    events = response.json()
    assert any(e["subject_id"] == complaint_id for e in events)


def test_investigator_denied_audit_for_cross_jurisdiction_complaint(client, db, jurisdiction_a, jurisdiction_b):
    complaint_id, _ = _make_complaint(client, jurisdiction_a)
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_b.jurisdiction_id)
    response = client.get(
        "/v1/audit/events",
        params={"subject_id": complaint_id, "subject_type": "complaint"},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


def test_audit_events_requires_authentication(client):
    response = client.get("/v1/audit/events")
    assert response.status_code == 401


def test_audit_events_filters_by_subject_id(client, db, jurisdiction_a):
    complaint_a_id, _ = _make_complaint(client, jurisdiction_a)
    complaint_b_id, _ = _make_complaint(client, jurisdiction_a)

    token = make_token(UserRole.auditor)
    response = client.get("/v1/audit/events", params={"subject_id": complaint_a_id}, headers=auth_headers(token))
    events = response.json()
    assert all(e["subject_id"] == complaint_a_id for e in events)
    assert len(events) >= 1
    assert not any(e["subject_id"] == complaint_b_id for e in events)


# --- GET /v1/audit/verify-chain -------------------------------------------------------


def test_verify_chain_reports_valid_for_an_untampered_chain(client, db, jurisdiction_a):
    _make_complaint(client, jurisdiction_a)
    token = make_token(UserRole.auditor)
    response = client.get("/v1/audit/verify-chain", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["broken_at_seq"] is None


def test_verify_chain_detects_tampering(client, db, jurisdiction_a):
    _make_complaint(client, jurisdiction_a)
    event = db.query(AuditEvent).order_by(AuditEvent.seq_no.asc()).first()
    event.payload = {**event.payload, "tampered": True}
    db.commit()

    token = make_token(UserRole.auditor)
    response = client.get("/v1/audit/verify-chain", headers=auth_headers(token))
    body = response.json()
    assert body["valid"] is False
    assert body["broken_at_seq"] == event.seq_no


def test_verify_chain_forbidden_for_investigator(client, db, jurisdiction_a):
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get("/v1/audit/verify-chain", headers=auth_headers(token))
    assert response.status_code == 403


def test_verify_chain_supports_a_partial_range(client, db, jurisdiction_a):
    for _ in range(3):
        _make_complaint(client, jurisdiction_a)
    all_events = db.query(AuditEvent).order_by(AuditEvent.seq_no.asc()).all()
    assert len(all_events) >= 3
    mid_seq = all_events[1].seq_no

    token = make_token(UserRole.auditor)
    response = client.get("/v1/audit/verify-chain", params={"from_seq": mid_seq}, headers=auth_headers(token))
    assert response.status_code == 200
    assert response.json()["valid"] is True


# --- GET /v1/models --------------------------------------------------------------------


def test_list_models_returns_empty_list_honestly_when_none_registered(client):
    token = make_token(UserRole.auditor)
    response = client.get("/v1/models", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.json() == []


def test_list_models_returns_real_registered_entries(client, db):
    entry = ModelRegistryEntry(
        stage=ModelStage.corridor_predictor,
        version="corridor_gbc-sklearn-1.9.0",
        trained_at=datetime.now(timezone.utc),
        metrics={"hit_rate_30deg": 0.62},
        is_active=True,
    )
    db.add(entry)
    db.commit()

    token = make_token(UserRole.admin)
    response = client.get("/v1/models", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["stage"] == "corridor_predictor"
    assert body[0]["metrics"] == {"hit_rate_30deg": 0.62}


def test_list_models_forbidden_for_investigator(client, db, jurisdiction_a):
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get("/v1/models", headers=auth_headers(token))
    assert response.status_code == 403


def test_list_models_forbidden_for_supervisor(client, db, jurisdiction_a):
    token = make_token(UserRole.supervisor, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get("/v1/models", headers=auth_headers(token))
    assert response.status_code == 403
