"""
Pure/near-pure unit tests for app/graph/explainer.py and app/graph/graph_path.py -
docs/AI_ML_ARCHITECTURE.md §6, Phase 2F. Mirrors
tests/test_risk_field_fusion.py's discipline: this stage's own "HOW
EVALUATED" (§6) is a determinism/consistency check, not a held-out metric -
these tests check exactly that (SHAP determinism, direction-sign mapping,
deterministic sentence generation, honest-empty comparable cases), never a
fabricated accuracy number.
"""
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest
from xgboost import XGBClassifier

from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus, FraudType, InstitutionType
from app.db.models.predictions import Prediction
from app.graph.explainer import (
    compute_top_factors,
    direction_from_shap_value,
    find_comparable_cases,
    generate_plain_language,
    reset_shap_explainer_cache,
)
from app.graph.graph_path import build_real_path_graph, compute_graph_path


@pytest.fixture(autouse=True)
def _fresh_shap_cache():
    reset_shap_explainer_cache()
    yield
    reset_shap_explainer_cache()


# --- direction_from_shap_value ------------------------------------------------


def test_direction_positive_value_increases_risk():
    assert direction_from_shap_value(0.42) == "increases_risk"


def test_direction_negative_value_decreases_risk():
    assert direction_from_shap_value(-0.17) == "decreases_risk"


def test_direction_exact_zero_is_neutral():
    assert direction_from_shap_value(0.0) == "neutral"


# --- compute_top_factors (SHAP) ------------------------------------------------


@pytest.fixture(scope="module")
def _fitted_classifier():
    """A small, fast, deterministic real XGBClassifier - not a mock - so
    SHAP's TreeExplainer runs against genuine tree structure, exactly as
    it would against app/graph/exit_scorer.py's real classifier."""
    rng = np.random.RandomState(42)
    X = rng.rand(60, 4)
    y = (X[:, 0] * 2 + X[:, 1] - X[:, 2] > 1.2).astype(int)
    clf = XGBClassifier(n_estimators=15, max_depth=3, random_state=42, eval_metric="logloss")
    clf.fit(X, y)
    return clf


_FEATURE_ORDER = ["alpha", "beta", "gamma", "delta"]


def _feature_dict(alpha=0.9, beta=0.8, gamma=0.1, delta=0.2):
    return {"alpha": alpha, "beta": beta, "gamma": gamma, "delta": delta}


def test_compute_top_factors_returns_requested_count_with_correct_shape(_fitted_classifier):
    factors = compute_top_factors(_fitted_classifier, _feature_dict(), _FEATURE_ORDER, top_n=3)
    assert len(factors) == 3
    for factor in factors:
        assert set(factor.keys()) == {"feature", "weight", "direction"}
        assert factor["feature"] in _FEATURE_ORDER
        assert factor["direction"] in {"increases_risk", "decreases_risk", "neutral"}


def test_compute_top_factors_direction_matches_weight_sign(_fitted_classifier):
    factors = compute_top_factors(_fitted_classifier, _feature_dict(), _FEATURE_ORDER, top_n=4)
    for factor in factors:
        assert factor["direction"] == direction_from_shap_value(factor["weight"])


def test_compute_top_factors_ranked_by_absolute_weight_descending(_fitted_classifier):
    factors = compute_top_factors(_fitted_classifier, _feature_dict(), _FEATURE_ORDER, top_n=4)
    magnitudes = [abs(f["weight"]) for f in factors]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_compute_top_factors_is_deterministic_for_identical_inputs(_fitted_classifier):
    """This stage's actual 'HOW EVALUATED' (§6): same model + same feature
    vector must yield a byte-identical explanation, not an approximately
    similar one - SHAP has no sampling randomness for tree ensembles."""
    first = compute_top_factors(_fitted_classifier, _feature_dict(), _FEATURE_ORDER, top_n=4)
    second = compute_top_factors(_fitted_classifier, _feature_dict(), _FEATURE_ORDER, top_n=4)
    assert first == second


def test_compute_top_factors_different_feature_vectors_can_differ(_fitted_classifier):
    a = compute_top_factors(_fitted_classifier, _feature_dict(alpha=0.9, beta=0.9), _FEATURE_ORDER, top_n=1)
    b = compute_top_factors(_fitted_classifier, _feature_dict(alpha=0.05, beta=0.05), _FEATURE_ORDER, top_n=1)
    assert a[0]["weight"] != b[0]["weight"]


# --- generate_plain_language ---------------------------------------------------


def test_plain_language_names_the_leading_factor():
    top_factors = [
        {"feature": "hop_count", "weight": 0.5, "direction": "increases_risk"},
        {"feature": "distance_km", "weight": -0.2, "direction": "decreases_risk"},
    ]
    graph_path = {"real_path": ["v", "a", "b"], "path_complete": True, "predicted_exit_channel_id": "ch1"}
    sentence = generate_plain_language(top_factors, graph_path)
    assert "hop_count" in sentence
    assert "increases risk" in sentence


def test_plain_language_mentions_real_hop_count_when_path_complete():
    top_factors = [{"feature": "velocity_km_per_hour", "weight": 0.3, "direction": "increases_risk"}]
    graph_path = {"real_path": ["v", "a", "b", "c"], "path_complete": True, "predicted_exit_channel_id": "ch1"}
    sentence = generate_plain_language(top_factors, graph_path)
    assert "3-hop" in sentence


def test_plain_language_never_claims_a_hop_chain_when_path_is_incomplete():
    top_factors = [{"feature": "velocity_km_per_hour", "weight": 0.3, "direction": "increases_risk"}]
    graph_path = {"real_path": [], "path_complete": False, "predicted_exit_channel_id": "ch1"}
    sentence = generate_plain_language(top_factors, graph_path)
    assert "hop" not in sentence


def test_plain_language_is_deterministic():
    top_factors = [{"feature": "hop_count", "weight": 0.5, "direction": "increases_risk"}]
    graph_path = {"real_path": ["v", "a"], "path_complete": True, "predicted_exit_channel_id": "ch1"}
    assert generate_plain_language(top_factors, graph_path) == generate_plain_language(top_factors, graph_path)


def test_plain_language_handles_empty_top_factors_honestly():
    sentence = generate_plain_language([], {"real_path": [], "path_complete": False, "predicted_exit_channel_id": None})
    assert "no individual contributing factor" in sentence


# --- graph-path assembly (isolated/fake graph data, no Neo4j) ------------------


def test_build_real_path_graph_creates_edges_from_chain_rows():
    chains = [
        {"chain_hashes": ["victim", "mule_a", "mule_b"], "depth": 2},
        {"chain_hashes": ["victim", "mule_c"], "depth": 1},
    ]
    graph = build_real_path_graph(chains)
    assert graph.has_edge("victim", "mule_a")
    assert graph.has_edge("mule_a", "mule_b")
    assert graph.has_edge("victim", "mule_c")
    assert not graph.has_edge("mule_b", "mule_c")


def test_build_real_path_graph_ignores_null_chains():
    chains = [{"chain_hashes": None, "depth": None}, {"chain_hashes": ["victim", "mule_a"], "depth": 1}]
    graph = build_real_path_graph(chains)
    assert graph.number_of_edges() == 1


def test_compute_graph_path_returns_incomplete_and_never_fabricates_when_accounts_unresolved(db):
    """No victim/last-known account can be resolved for a nonexistent
    complaint_id/member set - must return an honest incomplete result, no
    invented path, no exception."""
    result = compute_graph_path(db, complaint_id=str(uuid.uuid4()), member_account_ids=[], predicted_exit_channel_id="ch1")
    assert result["real_path"] == []
    assert result["path_complete"] is False
    assert result["predicted_exit_channel_id"] == "ch1"  # kept, even though the real path is empty


def test_compute_graph_path_never_puts_the_predicted_channel_inside_real_path(db):
    result = compute_graph_path(db, complaint_id=str(uuid.uuid4()), member_account_ids=[], predicted_exit_channel_id="predicted-ch-99")
    assert "predicted-ch-99" not in result["real_path"]


# --- find_comparable_cases (DB-backed, no Neo4j) -------------------------------


def _make_complaint(db, status=ComplaintStatus.new, fraud_type=FraudType.upi_fraud, amount=100000):
    victim = Account(account_hash=f"explainer-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"EXP-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=fraud_type,
        amount=amount,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Explainer unit test complaint",
        victim_account_id=victim.account_id,
        status=status,
    )
    db.add(complaint)
    db.flush()
    return complaint


def _make_prediction_with_snapshot(db, complaint_id, feature_order, by_exit_channel_id, ring_id=None):
    prediction = Prediction(
        complaint_id=complaint_id,
        generated_at=datetime.now(timezone.utc),
        feature_snapshot={"feature_order": feature_order, "ring_id": ring_id, "by_exit_channel_id": by_exit_channel_id},
    )
    db.add(prediction)
    db.flush()
    return prediction


def test_find_comparable_cases_returns_empty_when_no_resolved_complaints_exist(db):
    active = _make_complaint(db, status=ComplaintStatus.new)
    result = find_comparable_cases(db, _feature_dict(), _FEATURE_ORDER, exclude_complaint_id=active.complaint_id)
    assert result == []


def test_find_comparable_cases_returns_empty_when_resolved_complaints_have_no_snapshot(db):
    closed = _make_complaint(db, status=ComplaintStatus.closed)
    _make_prediction_with_snapshot(db, closed.complaint_id, _FEATURE_ORDER, {})  # empty - no real snapshot
    other = _make_complaint(db, status=ComplaintStatus.new)
    result = find_comparable_cases(db, _feature_dict(), _FEATURE_ORDER, exclude_complaint_id=other.complaint_id)
    assert result == []


def test_find_comparable_cases_finds_a_real_resolved_case_with_a_snapshot(db):
    closed = _make_complaint(db, status=ComplaintStatus.closed, fraud_type=FraudType.phishing, amount=55000)
    _make_prediction_with_snapshot(
        db, closed.complaint_id, _FEATURE_ORDER, {"ch1": _feature_dict(alpha=0.9, beta=0.8, gamma=0.1, delta=0.2)}
    )
    current = _make_complaint(db, status=ComplaintStatus.new)

    result = find_comparable_cases(
        db, _feature_dict(alpha=0.91, beta=0.79, gamma=0.11, delta=0.19), _FEATURE_ORDER, exclude_complaint_id=current.complaint_id
    )
    assert len(result) == 1
    assert result[0]["complaint_id"] == closed.complaint_id
    assert result[0]["summary"] == "phishing complaint, amount 55000"
    assert 0.0 < result[0]["similarity_score"] <= 1.0


def test_find_comparable_cases_never_compares_against_a_different_feature_schema(db):
    closed = _make_complaint(db, status=ComplaintStatus.closed)
    _make_prediction_with_snapshot(db, closed.complaint_id, ["different", "schema"], {"ch1": {"different": 1.0, "schema": 2.0}})
    current = _make_complaint(db, status=ComplaintStatus.new)

    result = find_comparable_cases(db, _feature_dict(), _FEATURE_ORDER, exclude_complaint_id=current.complaint_id)
    assert result == []


def test_find_comparable_cases_excludes_the_current_complaint_itself(db):
    closed = _make_complaint(db, status=ComplaintStatus.closed)
    _make_prediction_with_snapshot(db, closed.complaint_id, _FEATURE_ORDER, {"ch1": _feature_dict()})

    result = find_comparable_cases(db, _feature_dict(), _FEATURE_ORDER, exclude_complaint_id=closed.complaint_id)
    assert result == []
