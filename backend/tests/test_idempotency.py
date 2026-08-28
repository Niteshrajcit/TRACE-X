from app.db.models.complaints import Complaint
from tests.conftest import valid_complaint_payload


def test_duplicate_idempotency_key_returns_same_complaint(client, db):
    payload = valid_complaint_payload(idempotency_key="citizen-device-retry-abc123")

    first = client.post("/v1/complaints", json=payload)
    second = client.post("/v1/complaints", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200  # not a new resource
    assert first.json()["complaint_id"] == second.json()["complaint_id"]
    assert first.json()["incident_reference"] == second.json()["incident_reference"]

    count = db.query(Complaint).filter(
        Complaint.idempotency_key == "citizen-device-retry-abc123"
    ).count()
    assert count == 1


def test_different_idempotency_keys_create_different_complaints(client):
    first = client.post(
        "/v1/complaints", json=valid_complaint_payload(idempotency_key="key-one")
    )
    second = client.post(
        "/v1/complaints", json=valid_complaint_payload(idempotency_key="key-two")
    )
    assert first.json()["complaint_id"] != second.json()["complaint_id"]


def test_no_idempotency_key_allows_separate_submissions(client):
    first = client.post("/v1/complaints", json=valid_complaint_payload())
    second = client.post("/v1/complaints", json=valid_complaint_payload())
    assert first.json()["complaint_id"] != second.json()["complaint_id"]
