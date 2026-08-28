import h3

from app.db.models.exit_channels import ExitChannel
from app.db.models.jurisdictions import Bank, Jurisdiction
from app.db.models.response_units import ResponseUnit
from app.db.models.users import User
from app.synthetic.generator import (
    run_full_seed,
    seed_banks,
    seed_exit_channels,
    seed_jurisdictions,
    seed_response_units,
    seed_users,
)


def test_reference_data_seeding_is_idempotent(db):
    """Jurisdictions/banks/users/exit-channels/response-units are reference
    data - re-running the seed must not duplicate them. (Mule rings and
    historical incidents are intentionally additive each run, since they
    represent new synthetic cases, not fixed reference data - not asserted
    here as idempotent.)"""
    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    seed_users(db, jurisdiction_ids, bank_ids)
    seed_response_units(db, jurisdiction_ids)
    seed_exit_channels(db, jurisdiction_ids)

    jurisdiction_count_1 = db.query(Jurisdiction).count()
    bank_count_1 = db.query(Bank).count()
    user_count_1 = db.query(User).count()
    unit_count_1 = db.query(ResponseUnit).count()
    channel_count_1 = db.query(ExitChannel).count()

    # Re-run the exact same batch-mode seed functions against the same DB.
    jurisdiction_ids_2 = seed_jurisdictions(db)
    bank_ids_2 = seed_banks(db)
    seed_users(db, jurisdiction_ids_2, bank_ids_2)
    seed_response_units(db, jurisdiction_ids_2)
    seed_exit_channels(db, jurisdiction_ids_2)

    assert db.query(Jurisdiction).count() == jurisdiction_count_1
    assert db.query(Bank).count() == bank_count_1
    assert db.query(User).count() == user_count_1
    assert db.query(ResponseUnit).count() == unit_count_1
    assert db.query(ExitChannel).count() == channel_count_1


def test_full_seed_produces_expected_shape(db):
    summary = run_full_seed(db)
    assert summary["jurisdictions"] == 5  # 4 real + 1 fallback queue
    assert summary["banks"] == 4
    assert summary["exit_channels"] > 0
    assert summary["mule_rings"] == 6


def test_exit_channels_have_valid_h3_cells(db):
    run_full_seed(db)
    channels = db.query(ExitChannel).all()
    assert len(channels) > 0
    for channel in channels:
        assert h3.is_valid_cell(channel.h3_cell)


def test_response_units_seeded_per_jurisdiction(db):
    run_full_seed(db)
    real_jurisdictions = db.query(Jurisdiction).filter(Jurisdiction.name != "Unassigned Queue").all()
    for jurisdiction in real_jurisdictions:
        count = (
            db.query(ResponseUnit)
            .filter(ResponseUnit.jurisdiction_id == jurisdiction.jurisdiction_id)
            .count()
        )
        assert count >= 1
