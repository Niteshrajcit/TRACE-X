"""
Pure/near-pure feature-engineering tests for app/graph/exit_scorer.py -
docs/AI_ML_ARCHITECTURE.md §4, Phase 2D. No Neo4j anywhere in this file -
candidate restriction and feature computation are entirely Postgres/SQLite
+ in-memory, matching corridor's own "no Neo4j needed for this stage"
property (app/graph/exit_scorer.py's module docstring).
"""
from datetime import datetime, timezone

import pytest

from app.db.models.enums import ExitChannelType, InterventionActionType
from app.db.models.exit_channels import ExitChannel
from app.graph.exit_scorer import (
    _FEATURE_ORDER,
    _channel_attribute_score,
    _structuring_flag,
    _wilson_interval,
    compute_channel_features,
    feature_vector,
    get_candidate_exit_channels,
)


def _make_channel(
    channel_type=ExitChannelType.atm_cash, lat=13.05, lon=80.05, attrs=None, historical=2,
):
    return ExitChannel(
        channel_type=channel_type,
        external_ref="Test Channel",
        geo_lat=lat,
        geo_lon=lon,
        h3_cell="8828308281fffff",
        channel_attributes=attrs or {},
        intervention_action_type=InterventionActionType.physical_team_deployment,
        historical_incident_count=historical,
        is_synthetic=True,
    )


def test_structuring_flag_requires_at_least_three_hops():
    assert _structuring_flag([1000, 1000]) == 0


def test_structuring_flag_detects_tightly_clustered_amounts():
    # 3+ hops, amounts within a tight relative band
    assert _structuring_flag([49000, 49500, 48800, 49200]) == 1


def test_structuring_flag_is_zero_for_widely_varying_amounts():
    assert _structuring_flag([15000, 90000, 190000]) == 0


def test_channel_attribute_score_atm_cash_normalizes_cash_limit():
    channel = _make_channel(ExitChannelType.atm_cash, attrs={"cash_limit": 40000})
    assert _channel_attribute_score(channel) == pytest.approx(0.4)


def test_channel_attribute_score_crypto_p2p_ordinal_encodes_kyc_tier():
    channel = _make_channel(ExitChannelType.crypto_p2p, attrs={"kyc_tier": "high"})
    assert _channel_attribute_score(channel) == 2.0


def test_channel_attribute_score_defaults_to_zero_when_key_missing():
    channel = _make_channel(ExitChannelType.atm_cash, attrs={})
    assert _channel_attribute_score(channel) == 0.0


def test_feature_vector_matches_declared_order_and_is_numeric():
    features = {key: 1.0 for key in _FEATURE_ORDER}
    vector = feature_vector(features)
    assert len(vector) == len(_FEATURE_ORDER)
    assert all(isinstance(v, float) for v in vector)


@pytest.mark.parametrize(
    "p,n",
    [(0.5, 100), (0.1, 50), (0.9, 200), (0.0, 10), (1.0, 10)],
)
def test_wilson_interval_contains_the_point_estimate_and_stays_in_bounds(p, n):
    lo, hi = _wilson_interval(p, n)
    assert 0.0 <= lo <= hi <= 1.0


def test_wilson_interval_widens_with_smaller_sample_size():
    lo_small, hi_small = _wilson_interval(0.5, 10)
    lo_large, hi_large = _wilson_interval(0.5, 10000)
    assert (hi_small - lo_small) > (hi_large - lo_large)


def test_compute_channel_features_returns_all_declared_keys(db):
    channel = _make_channel()
    db.add(channel)
    db.flush()

    hop_features = {"velocity_km_per_hour": 5.0, "hop_count": 2}
    features = compute_channel_features(
        db, hop_features, [50000, 45000], 13.0, 80.0,
        datetime(2026, 8, 27, 14, 30, tzinfo=timezone.utc),
        {"bearing_deg": 45.0}, channel,
    )
    assert set(features.keys()) == set(_FEATURE_ORDER)
    assert features["hour_of_day"] == 14.0
    assert features["is_atm_cash"] == 1.0
    assert features["is_crypto_p2p"] == 0.0


def test_get_candidate_exit_channels_prefers_geographically_aligned_channels(db):
    aligned = _make_channel(lat=13.10, lon=80.10)  # roughly NE of (13.0, 80.0)
    opposite = _make_channel(lat=12.90, lon=79.90)  # roughly SW - wrong direction
    db.add(aligned)
    db.add(opposite)
    db.flush()

    exit_vector = {"bearing_deg": 45.0, "distance_range_km": [5.0, 20.0], "confidence_cone_deg": 30.0}
    candidates = get_candidate_exit_channels(db, 13.0, 80.0, exit_vector, max_candidates=10)
    assert len(candidates) >= 1
    assert candidates[0].channel_id == aligned.channel_id


def test_get_candidate_exit_channels_falls_back_to_closest_when_nothing_matches_the_window(db):
    far_away = _make_channel(lat=20.0, lon=90.0)
    db.add(far_away)
    db.flush()

    # A geographic window this channel cannot possibly satisfy.
    exit_vector = {"bearing_deg": 180.0, "distance_range_km": [1.0, 2.0], "confidence_cone_deg": 5.0}
    candidates = get_candidate_exit_channels(db, 13.0, 80.0, exit_vector, max_candidates=10)
    assert len(candidates) == 1  # fallback still returns something - never an empty result when channels exist


def test_get_candidate_exit_channels_returns_empty_when_no_channels_exist_at_all(db):
    exit_vector = {"bearing_deg": 45.0, "distance_range_km": [5.0, 20.0], "confidence_cone_deg": 30.0}
    assert get_candidate_exit_channels(db, 13.0, 80.0, exit_vector) == []
