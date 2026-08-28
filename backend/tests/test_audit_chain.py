"""
docs/SECURITY_AND_GOVERNANCE.md §4: every complaint creation appends a
hash-chained audit event, and tampering is detectable by recomputation.
Not exposed as an API endpoint in Phase 1 (out of this phase's minimal
endpoint list) - exercised directly against the service function instead.
"""
from app.audit.service import verify_chain
from app.db.models.audit import AuditEvent
from tests.conftest import valid_complaint_payload


def test_complaint_creation_appends_an_audit_event(client, db):
    response = client.post("/v1/complaints", json=valid_complaint_payload())
    complaint_id = response.json()["complaint_id"]

    event = (
        db.query(AuditEvent)
        .filter(AuditEvent.subject_id == complaint_id, AuditEvent.event_type == "complaint.created")
        .first()
    )
    assert event is not None
    assert event.this_hash is not None
    assert event.seq_no >= 1


def test_audit_chain_is_valid_after_several_events(client, db):
    for _ in range(4):
        client.post("/v1/complaints", json=valid_complaint_payload())

    valid, broken_at = verify_chain(db)
    assert valid is True
    assert broken_at is None


def test_audit_chain_detects_tampering(client, db):
    for _ in range(3):
        client.post("/v1/complaints", json=valid_complaint_payload())

    first_event = db.query(AuditEvent).order_by(AuditEvent.seq_no.asc()).first()
    first_event.payload = {**first_event.payload, "incident_reference": "TAMPERED"}
    db.add(first_event)
    db.commit()

    valid, broken_at = verify_chain(db)
    assert valid is False
    assert broken_at == first_event.seq_no
