"""
The Phase 1 end-to-end test required by the implementation brief:

    submit complaint -> verify database record -> verify event
    -> verify investigator receives event

This is deliberately the one test that walks the entire vertical slice in a
single pass, mirroring the Phase 1 exit criterion's browser-A/browser-B
walkthrough as closely as an automated test can.
"""
import queue
import threading

from app.db.models.audit import AuditEvent
from app.db.models.complaints import Complaint
from app.db.models.enums import UserRole
from tests.conftest import make_token, valid_complaint_payload


def _receive_with_timeout(websocket, timeout=2.0):
    """See tests/test_events_and_websocket.py's identical helper for why
    this uses a daemon thread + queue rather than a ThreadPoolExecutor
    context manager (which would deadlock the test process on shutdown)."""
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


def test_end_to_end_complaint_to_investigator_live_delivery(client, db, jurisdiction_a):
    investigator_token = make_token(
        UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id
    )

    # Step 0: investigator's Command Center is already open (WebSocket connected)
    # before the citizen ever submits anything - this is the "browser B open,
    # no refresh needed" precondition from the Phase 1 exit criterion.
    with client.websocket_connect(f"/v1/ws?token={investigator_token}") as websocket:

        # Step 1: citizen submits a complaint through the public portal API.
        submit_response = client.post(
            "/v1/complaints",
            json=valid_complaint_payload(jurisdiction_hint="Chennai"),
        )
        assert submit_response.status_code == 201
        body = submit_response.json()
        assert body["incident_reference"].startswith("TX-")
        complaint_id = body["complaint_id"]

        # Step 2: verify the PostgreSQL (SQLite-in-test) record exists and is correct.
        row = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
        assert row is not None
        assert row.status.value == "new"
        assert row.jurisdiction_id == jurisdiction_a.jurisdiction_id

        # Step 3: verify the complaint.created audit trail was written -
        # proof the event fired through the real service path, not just that
        # the HTTP response looked right.
        audit_row = (
            db.query(AuditEvent)
            .filter(AuditEvent.subject_id == complaint_id, AuditEvent.event_type == "complaint.created")
            .first()
        )
        assert audit_row is not None

        # Step 4: verify the investigator's already-open connection receives
        # the live push, without having refreshed or reconnected.
        message = _receive_with_timeout(websocket)
        assert message is not None, "investigator's WebSocket never received the live push"
        assert message["type"] == "complaint.created"
        assert message["complaint_id"] == complaint_id
        assert message["incident_reference"] == body["incident_reference"]

    # Step 5: investigator opens the incident and sees the stored complaint,
    # exactly as the Command Center UI would via GET /v1/complaints/{id}.
    detail_response = client.get(
        f"/v1/complaints/{complaint_id}",
        headers={"Authorization": f"Bearer {investigator_token}"},
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["incident_reference"] == body["incident_reference"]
    assert detail["status"] == "new"
    assert detail["institution_name"] == "Northbridge Bank"
