"""
docs/PRODUCT.md §5 / docs/DEMO_ARCHITECTURE.md §2: every generated record
must retain the required synthetic provenance, and it must never be
settable through the public request schema.
"""
from app.db.models.complaints import Complaint
from app.modules.complaints.schemas import ComplaintCreateRequest
from app.modules.complaints.service import create_complaint
from tests.conftest import valid_complaint_payload


def test_public_endpoint_complaints_are_never_marked_as_demo_data(client, db):
    response = client.post("/v1/complaints", json=valid_complaint_payload())
    row = db.query(Complaint).filter(Complaint.complaint_id == response.json()["complaint_id"]).first()
    assert row.is_demo_data is False


def test_public_request_schema_has_no_is_demo_data_field():
    # Structural guarantee, not just a runtime check: nobody can smuggle
    # is_demo_data through the public JSON body, because the field does not
    # exist on the schema bound to POST /v1/complaints.
    assert "is_demo_data" not in ComplaintCreateRequest.model_fields


def test_service_layer_can_mark_demo_data_for_internal_seeding_callers(db):
    request = ComplaintCreateRequest(**valid_complaint_payload())
    complaint, created = create_complaint(db, request, is_demo_data=True)
    assert created is True
    assert complaint.is_demo_data is True


def test_synthetic_generator_accounts_are_flagged(db):
    from app.synthetic.generator import seed_banks, seed_jurisdictions, seed_mule_rings
    from app.db.models.accounts import Account

    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    seed_mule_rings(db, bank_ids, jurisdiction_ids, ring_count=1)

    synthetic_accounts = db.query(Account).filter(Account.is_synthetic.is_(True)).all()
    assert len(synthetic_accounts) > 0
    assert all(a.ring_id is not None for a in synthetic_accounts)


def test_synthetic_generator_transactions_are_flagged(db):
    from app.synthetic.generator import seed_banks, seed_jurisdictions, seed_mule_rings
    from app.db.models.transactions import Transaction

    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    seed_mule_rings(db, bank_ids, jurisdiction_ids, ring_count=1)

    transactions = db.query(Transaction).all()
    assert len(transactions) > 0
    assert all(t.is_synthetic is True for t in transactions)
