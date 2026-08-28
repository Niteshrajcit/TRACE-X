from app.core.security import hash_pii
from app.db.models.accounts import Account, LinkedEntity
from app.db.models.enums import LinkedEntityType
from app.db.models.transactions import Transaction
from tests.conftest import auth_headers, service_token, valid_transaction_payload


def _ingest(client, payload):
    return client.post(
        "/v1/transactions/ingest", json=payload, headers=auth_headers(service_token())
    )


def test_transaction_persisted_in_database(client, db, submitted_complaint):
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"],
        from_account_number="9999000011",
        to_account_number="9999000022",
    )
    response = _ingest(client, payload)
    txn_id = response.json()["txn_id"]

    row = db.query(Transaction).filter(Transaction.txn_id == txn_id).first()
    assert row is not None
    assert row.complaint_id == submitted_complaint["complaint_id"]
    assert row.channel.value == "upi"
    assert str(row.amount) == "50000.00"
    assert row.is_synthetic is True


def test_account_numbers_are_hashed_not_stored_in_the_clear(client, db, submitted_complaint):
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"],
        from_account_number="RAW-FROM-ACCT",
        to_account_number="RAW-TO-ACCT",
    )
    _ingest(client, payload)

    from_account = db.query(Account).filter(Account.account_hash == hash_pii("RAW-FROM-ACCT")).first()
    to_account = db.query(Account).filter(Account.account_hash == hash_pii("RAW-TO-ACCT")).first()
    assert from_account is not None
    assert to_account is not None
    assert "RAW-FROM-ACCT" not in from_account.account_hash
    assert "RAW-TO-ACCT" not in to_account.account_hash


def test_new_accounts_created_via_ingestion_are_marked_synthetic(client, db, submitted_complaint):
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"],
        from_account_number="NEW-MULE-0001",
        to_account_number="NEW-MULE-0002",
    )
    _ingest(client, payload)

    account = db.query(Account).filter(Account.account_hash == hash_pii("NEW-MULE-0001")).first()
    assert account.is_synthetic is True


def test_device_ip_phone_vpa_are_hashed_and_linked_to_from_account(client, db, submitted_complaint):
    payload = valid_transaction_payload(
        complaint_id=submitted_complaint["complaint_id"],
        from_account_number="DEVICE-TEST-ACCT",
        device_id="device-raw-123",
        ip_address="203.0.113.42",
        originator_phone="+91-90000-99999",
        originator_vpa="fraudster@upi",
    )
    _ingest(client, payload)

    account = db.query(Account).filter(Account.account_hash == hash_pii("DEVICE-TEST-ACCT")).first()
    entities = db.query(LinkedEntity).filter(LinkedEntity.account_id == account.account_id).all()
    by_type = {e.entity_type: e.entity_hash for e in entities}

    assert by_type[LinkedEntityType.device] == hash_pii("device-raw-123")
    assert by_type[LinkedEntityType.ip] == hash_pii("203.0.113.42")
    assert by_type[LinkedEntityType.phone] == hash_pii("+91-90000-99999")
    assert by_type[LinkedEntityType.vpa] == hash_pii("fraudster@upi")
    # Raw values never appear anywhere in the persisted rows.
    for raw in ("device-raw-123", "203.0.113.42", "+91-90000-99999", "fraudster@upi"):
        assert raw not in by_type.values()


def test_hop_index_increments_along_a_chain(client, submitted_complaint):
    victim_number = "VICTIM-0001"  # matches submitted_complaint fixture's victim account
    mule_1, mule_2, mule_3 = "MULE-CHAIN-1", "MULE-CHAIN-2", "MULE-CHAIN-3"

    r1 = _ingest(
        client,
        valid_transaction_payload(
            complaint_id=submitted_complaint["complaint_id"],
            from_account_number=victim_number,
            to_account_number=mule_1,
        ),
    )
    r2 = _ingest(
        client,
        valid_transaction_payload(
            complaint_id=submitted_complaint["complaint_id"],
            from_account_number=mule_1,
            to_account_number=mule_2,
        ),
    )
    r3 = _ingest(
        client,
        valid_transaction_payload(
            complaint_id=submitted_complaint["complaint_id"],
            from_account_number=mule_2,
            to_account_number=mule_3,
        ),
    )

    assert r1.json()["hop_index"] == 1
    assert r2.json()["hop_index"] == 2
    assert r3.json()["hop_index"] == 3


def test_hop_index_is_capped_at_max_hop_depth(client, submitted_complaint):
    from app.core.config import get_settings

    max_depth = get_settings().max_hop_depth
    accounts = ["VICTIM-0001"] + [f"DEEP-MULE-{i}" for i in range(max_depth + 3)]

    last_hop_index = None
    for src, dst in zip(accounts, accounts[1:]):
        response = _ingest(
            client,
            valid_transaction_payload(
                complaint_id=submitted_complaint["complaint_id"],
                from_account_number=src,
                to_account_number=dst,
            ),
        )
        last_hop_index = response.json()["hop_index"]

    assert last_hop_index == max_depth


def test_unrelated_account_joining_an_existing_chain_is_capped_not_unbounded(client, submitted_complaint):
    """An account that never received funds within this complaint's chain
    must not be able to claim hop_index 1 just by being named as a
    from_account - docs/API_CONTRACT.md §1a's bounded-traversal rule."""
    _ingest(
        client,
        valid_transaction_payload(
            complaint_id=submitted_complaint["complaint_id"],
            from_account_number="VICTIM-0001",
            to_account_number="CHAIN-MULE-1",
        ),
    )
    from app.core.config import get_settings

    response = _ingest(
        client,
        valid_transaction_payload(
            complaint_id=submitted_complaint["complaint_id"],
            from_account_number="NEVER-SEEN-BEFORE",
            to_account_number="CHAIN-MULE-2",
        ),
    )
    assert response.json()["hop_index"] == get_settings().max_hop_depth
