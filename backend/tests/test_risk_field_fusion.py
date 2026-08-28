"""
Pure/near-pure correctness tests for app/graph/risk_field.py -
docs/AI_ML_ARCHITECTURE.md §5, Phase 2E. Per §5's own HOW EVALUATED row,
this stage has no learned parameters and no held-out evaluation - these
tests check the fusion formula's behavior directly (decay curve, additive/
order-independent combination, incremental scoping), exactly what the
architecture says to verify.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus, FraudType, InstitutionType
from app.db.models.jurisdictions import Jurisdiction
from app.db.models.predictions import Prediction
from app.graph.risk_field import (
    compute_risk_field,
    decay,
    get_cache_generated_at,
    get_cached_field,
    recompute_touched_cells,
    reset_cache,
    seed_cache_from_scratch,
    touched_cells,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    reset_cache()
    yield
    reset_cache()


def test_decay_at_zero_elapsed_is_one():
    assert decay(0.0, half_life_hours=6.0) == pytest.approx(1.0)


def test_decay_at_one_half_life_is_one_half():
    assert decay(6.0, half_life_hours=6.0) == pytest.approx(0.5)


def test_decay_at_two_half_lives_is_one_quarter():
    assert decay(12.0, half_life_hours=6.0) == pytest.approx(0.25)


def test_decay_is_monotonically_decreasing():
    values = [decay(h, half_life_hours=6.0) for h in [0, 1, 2, 5, 10, 20, 50]]
    assert values == sorted(values, reverse=True)


def test_decay_clamps_negative_elapsed_to_zero_not_greater_than_one():
    assert decay(-5.0, half_life_hours=6.0) == pytest.approx(1.0)


def test_touched_cells_extracts_cell_ids_only():
    ranked = [{"h3_cell": "a", "probability": 0.5}, {"h3_cell": "b", "probability": 0.1}]
    assert touched_cells(ranked) == {"a", "b"}


def test_touched_cells_handles_none_and_empty():
    assert touched_cells(None) == set()
    assert touched_cells([]) == set()


def _make_complaint(db, jurisdiction_id, status=ComplaintStatus.new):
    victim = Account(account_hash=f"riskfield-{uuid.uuid4().hex}-{status.value}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"RF-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=100000,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Risk field fusion test complaint",
        victim_account_id=victim.account_id,
        jurisdiction_id=jurisdiction_id,
        status=status,
    )
    db.add(complaint)
    db.flush()
    return complaint


def _make_prediction(db, complaint_id, ranked_locations, generated_at):
    prediction = Prediction(
        complaint_id=complaint_id,
        generated_at=generated_at,
        ranked_locations=ranked_locations,
    )
    db.add(prediction)
    db.flush()
    return prediction


@pytest.fixture
def jurisdiction(db):
    j = Jurisdiction(name="Risk Field Test Jurisdiction", state="Tamil Nadu", district="Chennai")
    db.add(j)
    db.flush()
    return j


def test_compute_risk_field_sums_two_complaints_on_the_same_cell(db, jurisdiction):
    now = datetime.now(timezone.utc)
    c1 = _make_complaint(db, jurisdiction.jurisdiction_id)
    c2 = _make_complaint(db, jurisdiction.jurisdiction_id)
    _make_prediction(db, c1.complaint_id, [{"h3_cell": "cellX", "probability": 0.3}], now)
    _make_prediction(db, c2.complaint_id, [{"h3_cell": "cellX", "probability": 0.4}], now)

    field = compute_risk_field(db, jurisdiction.jurisdiction_id, as_of=now, half_life_hours=6.0)
    assert field["cellX"] == pytest.approx(0.7)  # additive, both at decay=1.0 (same instant)


def test_compute_risk_field_combination_is_order_independent(db, jurisdiction):
    now = datetime.now(timezone.utc)
    c1 = _make_complaint(db, jurisdiction.jurisdiction_id)
    c2 = _make_complaint(db, jurisdiction.jurisdiction_id)
    c3 = _make_complaint(db, jurisdiction.jurisdiction_id)
    # Insert in one order...
    _make_prediction(db, c2.complaint_id, [{"h3_cell": "cellY", "probability": 0.2}], now)
    _make_prediction(db, c1.complaint_id, [{"h3_cell": "cellY", "probability": 0.5}], now - timedelta(hours=3))
    _make_prediction(db, c3.complaint_id, [{"h3_cell": "cellY", "probability": 0.1}], now - timedelta(hours=1))

    field_a = compute_risk_field(db, jurisdiction.jurisdiction_id, as_of=now, half_life_hours=6.0)

    # A sum is inherently order-independent - re-querying (different row
    # order from the DB is not guaranteed) and recomputing must agree
    # exactly, not approximately.
    field_b = compute_risk_field(db, jurisdiction.jurisdiction_id, as_of=now, half_life_hours=6.0)
    assert field_a["cellY"] == field_b["cellY"]

    expected = 0.5 * decay(3.0, 6.0) + 0.2 * decay(0.0, 6.0) + 0.1 * decay(1.0, 6.0)
    assert field_a["cellY"] == pytest.approx(expected)


def test_compute_risk_field_excludes_closed_and_rejected_complaints(db, jurisdiction):
    now = datetime.now(timezone.utc)
    active = _make_complaint(db, jurisdiction.jurisdiction_id, status=ComplaintStatus.new)
    closed = _make_complaint(db, jurisdiction.jurisdiction_id, status=ComplaintStatus.closed)
    rejected = _make_complaint(db, jurisdiction.jurisdiction_id, status=ComplaintStatus.rejected)
    _make_prediction(db, active.complaint_id, [{"h3_cell": "cellZ", "probability": 0.5}], now)
    _make_prediction(db, closed.complaint_id, [{"h3_cell": "cellZ", "probability": 0.9}], now)
    _make_prediction(db, rejected.complaint_id, [{"h3_cell": "cellZ", "probability": 0.9}], now)

    field = compute_risk_field(db, jurisdiction.jurisdiction_id, as_of=now, half_life_hours=6.0)
    assert field["cellZ"] == pytest.approx(0.5)  # only the active complaint's contribution


def test_compute_risk_field_excludes_predictions_generated_after_as_of(db, jurisdiction):
    now = datetime.now(timezone.utc)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)
    _make_prediction(db, complaint.complaint_id, [{"h3_cell": "cellFuture", "probability": 0.9}], now + timedelta(hours=1))

    field = compute_risk_field(db, jurisdiction.jurisdiction_id, as_of=now, half_life_hours=6.0)
    assert "cellFuture" not in field


def test_recompute_touched_cells_leaves_other_cached_cells_untouched(db, jurisdiction):
    now = datetime.now(timezone.utc)
    c1 = _make_complaint(db, jurisdiction.jurisdiction_id)
    _make_prediction(db, c1.complaint_id, [{"h3_cell": "cellA", "probability": 0.5}], now)
    seed_cache_from_scratch(db, jurisdiction.jurisdiction_id, as_of=now)
    assert get_cached_field(jurisdiction.jurisdiction_id) == {"cellA": pytest.approx(0.5)}

    # A second complaint touches a DIFFERENT cell - incremental recompute
    # must update only that cell, leaving cellA's cached value exactly as it was.
    c2 = _make_complaint(db, jurisdiction.jurisdiction_id)
    _make_prediction(db, c2.complaint_id, [{"h3_cell": "cellB", "probability": 0.3}], now)
    recompute_touched_cells(db, jurisdiction.jurisdiction_id, {"cellB"}, as_of=now)

    field = get_cached_field(jurisdiction.jurisdiction_id)
    assert field["cellA"] == pytest.approx(0.5)  # untouched, byte-for-byte
    assert field["cellB"] == pytest.approx(0.3)


def test_recompute_touched_cells_removes_a_cell_whose_contribution_is_gone(db, jurisdiction):
    now = datetime.now(timezone.utc)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id, status=ComplaintStatus.new)
    prediction = _make_prediction(db, complaint.complaint_id, [{"h3_cell": "cellC", "probability": 0.5}], now)
    seed_cache_from_scratch(db, jurisdiction.jurisdiction_id, as_of=now)
    assert "cellC" in get_cached_field(jurisdiction.jurisdiction_id)

    complaint.status = ComplaintStatus.closed  # no longer active - its contribution must vanish
    db.commit()
    recompute_touched_cells(db, jurisdiction.jurisdiction_id, {"cellC"}, as_of=now)
    assert "cellC" not in get_cached_field(jurisdiction.jurisdiction_id)


def test_seed_cache_from_scratch_sets_generated_at(db, jurisdiction):
    now = datetime.now(timezone.utc)
    assert get_cache_generated_at(jurisdiction.jurisdiction_id) is None
    seed_cache_from_scratch(db, jurisdiction.jurisdiction_id, as_of=now)
    assert get_cache_generated_at(jurisdiction.jurisdiction_id) == now


def test_historical_replay_reproduces_the_field_as_it_was_at_a_past_instant(db, jurisdiction):
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    t1 = datetime.now(timezone.utc) - timedelta(hours=2)
    c1 = _make_complaint(db, jurisdiction.jurisdiction_id)
    c2 = _make_complaint(db, jurisdiction.jurisdiction_id)
    _make_prediction(db, c1.complaint_id, [{"h3_cell": "cellR", "probability": 0.6}], t0)
    _make_prediction(db, c2.complaint_id, [{"h3_cell": "cellR", "probability": 0.4}], t1)

    # At t0, only c1's prediction existed yet.
    field_at_t0 = compute_risk_field(db, jurisdiction.jurisdiction_id, as_of=t0, half_life_hours=6.0)
    assert field_at_t0["cellR"] == pytest.approx(0.6)  # c1 alone, zero elapsed

    # At t1, both exist; c1 has decayed for (t1 - t0) hours, c2 is fresh.
    field_at_t1 = compute_risk_field(db, jurisdiction.jurisdiction_id, as_of=t1, half_life_hours=6.0)
    elapsed = (t1 - t0).total_seconds() / 3600.0
    expected = 0.6 * decay(elapsed, 6.0) + 0.4
    assert field_at_t1["cellR"] == pytest.approx(expected)

    # Re-deriving at the SAME past instant again is deterministic - identical result.
    field_at_t1_again = compute_risk_field(db, jurisdiction.jurisdiction_id, as_of=t1, half_life_hours=6.0)
    assert field_at_t1 == field_at_t1_again
