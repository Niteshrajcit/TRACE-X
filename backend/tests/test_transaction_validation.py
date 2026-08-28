from tests.conftest import service_token, valid_transaction_payload, auth_headers


def _ingest(client, payload):
    return client.post(
        "/v1/transactions/ingest", json=payload, headers=auth_headers(service_token())
    )


def test_valid_transaction_is_accepted(client, submitted_complaint):
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    response = _ingest(client, payload)
    assert response.status_code == 202
    body = response.json()
    assert "txn_id" in body
    assert body["hop_index"] == 1


def test_rejects_missing_complaint_id(client):
    payload = valid_transaction_payload()
    del payload["complaint_id"]
    response = _ingest(client, payload)
    assert response.status_code == 422


def test_rejects_zero_amount(client, submitted_complaint):
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"], amount="0")
    assert _ingest(client, payload).status_code == 422


def test_rejects_negative_amount(client, submitted_complaint):
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"], amount="-100")
    assert _ingest(client, payload).status_code == 422


def test_rejects_invalid_channel(client, submitted_complaint):
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"], channel="bitcoin"
    )
    assert _ingest(client, payload).status_code == 422


def test_rejects_missing_from_account(client, submitted_complaint):
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    del payload["from_account_number"]
    assert _ingest(client, payload).status_code == 422


def test_rejects_missing_occurred_at(client, submitted_complaint):
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    del payload["occurred_at"]
    assert _ingest(client, payload).status_code == 422


def test_rejects_unknown_complaint_id(client):
    payload = valid_transaction_payload(complaint_id="00000000-0000-0000-0000-000000000000")
    response = _ingest(client, payload)
    assert response.status_code == 404


def test_rejects_unknown_exit_channel_id(client, submitted_complaint):
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"],
        exit_channel_id="00000000-0000-0000-0000-000000000000",
    )
    response = _ingest(client, payload)
    assert response.status_code == 404


def test_hop_index_is_never_accepted_from_the_client(client, submitted_complaint):
    """hop_index must not even be a settable field - confirms the schema
    itself has no such field, not just that the server overwrites it."""
    from app.modules.transactions.schemas import TransactionIngestRequest

    assert "hop_index" not in TransactionIngestRequest.model_fields


def test_no_field_accepts_a_pre_hashed_identifier(client, submitted_complaint):
    """Structural guarantee: the request schema has raw-value field names
    only, never a `*_hash` field a caller could pass a precomputed hash
    into."""
    from app.modules.transactions.schemas import TransactionIngestRequest

    for field_name in TransactionIngestRequest.model_fields:
        assert not field_name.endswith("_hash"), field_name
