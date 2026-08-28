"""
Ground-truth generation, XGBoost/Cox training, determinism, and evaluation
tests for Phase 2D - docs/AI_ML_ARCHITECTURE.md §4. No Neo4j anywhere in
this file: ground-truth planting (seed_mule_rings), training, and
evaluation are entirely Postgres/SQLite, exactly like Corridor's own
training/evaluation tests.
"""
import pytest

from app.db.models.accounts import Account
from app.db.models.exit_channels import ExitChannel
from app.db.models.transactions import Transaction
from app.graph.exit_scorer import (
    build_training_dataset,
    evaluate_exit_scorer,
    reset_cached_models,
    train_exit_channel_classifier,
    train_time_window_model,
)
from app.synthetic.generator import seed_banks, seed_exit_channels, seed_jurisdictions, seed_mule_rings


@pytest.fixture(autouse=True)
def _fresh_models():
    reset_cached_models()
    yield
    reset_cached_models()


@pytest.fixture
def seeded_ground_truth(db):
    """Exit channels seeded BEFORE mule rings - the order this phase's
    ground-truth extension requires to plant a real exit_channel_id
    (app/synthetic/generator.py::seed_mule_rings's Phase 2D addition)."""
    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    seed_exit_channels(db, jurisdiction_ids)
    rings = seed_mule_rings(db, bank_ids, jurisdiction_ids, ring_count=15)
    return rings


def test_seed_mule_rings_plants_a_real_exit_channel_and_timing(db, seeded_ground_truth):
    """The core ground-truth claim: every ring's summary reports a real,
    existing exit_channel_id, and that exact value is independently
    findable on the ring's own last Transaction row - not just returned in
    a dict, genuinely persisted and queryable, the same way accounts.ring_id
    already is ground truth for Ring Detection."""
    for ring in seeded_ground_truth:
        assert ring["true_exit_channel_id"] is not None
        channel = db.query(ExitChannel).filter(ExitChannel.channel_id == ring["true_exit_channel_id"]).first()
        assert channel is not None

        account_ids = [ring["victim_account_id"]] + ring["mule_account_ids"]
        true_txn = (
            db.query(Transaction)
            .filter(
                Transaction.from_account_id.in_(account_ids),
                Transaction.to_account_id.in_(account_ids),
                Transaction.exit_channel_id == ring["true_exit_channel_id"],
            )
            .first()
        )
        assert true_txn is not None, "the planted exit_channel_id must be on a real transaction, not just returned"
        assert true_txn.hop_index == max(
            t.hop_index
            for t in db.query(Transaction)
            .filter(Transaction.from_account_id.in_(account_ids), Transaction.to_account_id.in_(account_ids))
            .all()
        ), "the exit channel must be planted on the chain's FINAL hop"


def test_seed_mule_rings_is_backward_compatible_without_exit_channels(db):
    """Existing callers (e.g. tests/test_ring_detection_integration.py) call
    seed_mule_rings without seeding exit channels first - must not error,
    must leave true_exit_channel_id as None, exactly as before this
    Phase 2D change."""
    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    rings = seed_mule_rings(db, bank_ids, jurisdiction_ids, ring_count=2)
    for ring in rings:
        assert ring["true_exit_channel_id"] is None


def test_build_training_dataset_produces_one_positive_row_per_ring(db, seeded_ground_truth):
    X, y, durations, events, channel_types, ring_ids = build_training_dataset(db)
    assert len(X) > 0
    assert len(X) == len(y) == len(durations) == len(events) == len(channel_types) == len(ring_ids)
    # exactly one positive (true channel) candidate row per ring
    positives_per_ring: dict[str, int] = {}
    for label, ring_id in zip(y, ring_ids):
        if label == 1:
            positives_per_ring[ring_id] = positives_per_ring.get(ring_id, 0) + 1
    assert all(count == 1 for count in positives_per_ring.values())


def test_train_exit_channel_classifier_raises_on_insufficient_data(db):
    with pytest.raises(ValueError, match="insufficient"):
        train_exit_channel_classifier(db)


def test_train_exit_channel_classifier_succeeds_and_is_deterministic(db, seeded_ground_truth):
    model_a, metrics_a = train_exit_channel_classifier(db, random_state=42)
    model_b, metrics_b = train_exit_channel_classifier(db, random_state=42)

    X, y, _durations, _events, _channel_types, _ring_ids = build_training_dataset(db)
    sample = X[0]
    assert model_a.score(sample) == pytest.approx(model_b.score(sample))
    assert metrics_a["train_rows"] == metrics_b["train_rows"]


def test_train_time_window_model_raises_on_insufficient_events(db):
    with pytest.raises(ValueError, match="insufficient"):
        train_time_window_model(db)


def test_train_time_window_model_succeeds_and_produces_a_positive_window(db, seeded_ground_truth):
    model, metrics = train_time_window_model(db, random_state=42)
    assert metrics["events_observed"] >= 2

    X, _y, _durations, _events, _channel_types, _ring_ids = build_training_dataset(db)
    lo, hi = model.predict_time_window_minutes(X[0])
    assert 0 < lo <= hi


def test_evaluate_exit_scorer_raises_on_insufficient_data(db):
    with pytest.raises(ValueError, match="insufficient"):
        evaluate_exit_scorer(db)


def test_evaluate_exit_scorer_reports_real_metrics(db, seeded_ground_truth):
    result = evaluate_exit_scorer(db, random_state=42)
    assert result["test_rings"] > 0
    assert 0.0 <= result["top5_hit_rate"] <= 1.0
    assert 0.0 <= result["top10_hit_rate"] <= 1.0
    assert result["top5_hit_rate"] <= result["top10_hit_rate"]  # top-10 can only be >= top-5
    assert result["brier_score"] is not None
    assert 0.0 <= result["brier_score"] <= 1.0
