from decimal import Decimal

from app.db.models.complaints import Complaint
from tests.conftest import valid_complaint_payload


def test_complaint_persisted_in_database(client, db):
    response = client.post("/v1/complaints", json=valid_complaint_payload())
    complaint_id = response.json()["complaint_id"]

    row = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
    assert row is not None
    assert row.incident_reference == response.json()["incident_reference"]
    assert row.fraud_type.value == "upi_fraud"
    assert row.amount == Decimal("200000.00")
    assert row.location_text == "T. Nagar, Chennai"
    assert row.institution_name == "Northbridge Bank"
    assert row.description.startswith("Received a phishing call")
    assert row.evidence_notes == ["Screenshot of the debit SMS"]
    assert row.status.value == "new"


def test_complaint_jurisdiction_resolved_from_hint(client, db, jurisdiction_a):
    response = client.post("/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai"))
    row = db.query(Complaint).filter(Complaint.complaint_id == response.json()["complaint_id"]).first()
    assert row.jurisdiction_id == jurisdiction_a.jurisdiction_id


def test_complaint_falls_back_to_unassigned_queue_when_hint_matches_nothing(client, db):
    response = client.post(
        "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Nowhere Land")
    )
    row = db.query(Complaint).filter(Complaint.complaint_id == response.json()["complaint_id"]).first()
    assert row.jurisdiction_id is not None  # landed in the seeded "Unassigned Queue", not NULL


def test_victim_account_number_is_not_stored_in_the_clear(client, db):
    response = client.post("/v1/complaints", json=valid_complaint_payload(victim_account_number="9999888877"))
    complaint_id = response.json()["complaint_id"]
    row = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
    assert row.victim_account_id is not None

    from app.db.models.accounts import Account

    account = db.query(Account).filter(Account.account_id == row.victim_account_id).first()
    assert account is not None
    assert "9999888877" not in account.account_hash
    assert len(account.account_hash) == 64  # sha256 hex digest
