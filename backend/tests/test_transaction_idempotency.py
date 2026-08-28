"""
docs/API_CONTRACT.md §1a idempotency semantics, and the five automated
cases this phase's brief explicitly asks for: first submission, repeated
submission, conflicting payload using the same key, authorization failure,
validation failure.
"""
from app.db.models.transactions import Transaction
from tests.conftest import auth_headers, service_token, valid_transaction_payload


def _ingest(client, payload):
    return client.post(
        "/v1/transactions/ingest", json=payload, headers=auth_headers(service_token())
    )


def test_first_submission_creates_a_transaction(client, db, submitted_complaint):
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"], idempotency_key="idem-key-001"
    )
    response = _ingest(client, payload)
    assert response.status_code == 202
    assert db.query(Transaction).filter(Transaction.idempotency_key == "idem-key-001").count() == 1


def test_repeated_submission_with_identical_payload_does_not_duplicate(client, db, submitted_complaint):
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"], idempotency_key="idem-key-002"
    )
    first = _ingest(client, payload)
    second = _ingest(client, payload)

    assert first.status_code == 202
    assert second.status_code == 200  # replay, not a new resource
    assert first.json()["txn_id"] == second.json()["txn_id"]
    assert db.query(Transaction).filter(Transaction.idempotency_key == "idem-key-002").count() == 1


def test_conflicting_payload_with_same_key_is_rejected(client, submitted_complaint):
    key = "idem-key-003"
    first_payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"], idempotency_key=key, amount="50000.00"
    )
    conflicting_payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"], idempotency_key=key, amount="99999.00"
    )

    first = _ingest(client, first_payload)
    second = _ingest(client, conflicting_payload)

    assert first.status_code == 202
    assert second.status_code == 409


def test_conflicting_payload_different_accounts_is_rejected(client, submitted_complaint):
    key = "idem-key-004"
    first = _ingest(
        client,
        valid_transaction_payload(
            complaint_id=submitted_complaint["complaint_id"], idempotency_key=key,
            to_account_number="ACCOUNT-A",
        ),
    )
    second = _ingest(
        client,
        valid_transaction_payload(
            complaint_id=submitted_complaint["complaint_id"], idempotency_key=key,
            to_account_number="ACCOUNT-B",
        ),
    )
    assert first.status_code == 202
    assert second.status_code == 409


def test_no_idempotency_key_allows_separate_submissions(client, submitted_complaint):
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    first = _ingest(client, payload)
    second = _ingest(client, payload)
    assert first.json()["txn_id"] != second.json()["txn_id"]


def test_authorization_failure_case(client, submitted_complaint):
    """Required case: authorization failure - no service token."""
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    response = client.post("/v1/transactions/ingest", json=payload)
    assert response.status_code == 401


def test_validation_failure_case(client, submitted_complaint):
    """Required case: validation failure - bad amount."""
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"], amount="not-a-number"
    )
    response = _ingest(client, payload)
    assert response.status_code == 422
