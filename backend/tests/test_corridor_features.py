"""
Pure unit tests for app/graph/corridor.py's feature engineering and bucket
math - docs/AI_ML_ARCHITECTURE.md §3, Phase 2C. No DB, no Neo4j - these
exercise compute_hop_features/feature_vector/bucket_for_bearing directly
against hand-built hop sequences, matching tests/test_community_detection.py's
pattern for the Ring Detector's own pure-logic coverage.
"""
import pytest
from datetime import datetime, timezone

from app.graph.corridor import (
    BEARING_BUCKETS,
    _circular_diff_deg,
    bucket_center_deg,
    bucket_for_bearing,
    compute_hop_features,
    feature_vector,
)


def _hop(from_lat, from_lon, to_lat, to_lon, channel="upi", occurred_at="2026-08-27T09:00:00+00:00"):
    return {
        "from_lat": from_lat, "from_lon": from_lon,
        "to_lat": to_lat, "to_lon": to_lon,
        "channel": channel,
        "occurred_at": datetime.fromisoformat(occurred_at),
    }


def test_compute_hop_features_requires_at_least_one_hop():
    with pytest.raises(ValueError):
        compute_hop_features([])


def test_single_hop_due_north_has_zero_bearing_and_no_velocity_without_span():
    # Same lat delta, zero lon delta - due north bearing is exactly 0.
    hop = _hop(13.0, 80.0, 13.1, 80.0, occurred_at="2026-08-27T09:00:00+00:00")
    hop["occurred_at"] = datetime.fromisoformat("2026-08-27T09:00:00+00:00")
    features = compute_hop_features([hop])
    assert features["net_bearing_deg"] == pytest.approx(0.0, abs=1.0)
    assert features["hop_count"] == 1
    # A single hop has no "span" (start == end instant assumed identical
    # here) - velocity must be null-safe, not a divide-by-zero crash.
    assert features["velocity_km_per_hour"] is None


def test_two_hops_net_displacement_uses_first_origin_and_last_destination():
    # a -> b -> c: net displacement must be measured a -> c, not per-hop.
    hops = [
        _hop(13.0, 80.0, 13.0, 80.1, occurred_at="2026-08-27T09:00:00+00:00"),
        _hop(13.0, 80.1, 13.1, 80.1, occurred_at="2026-08-27T10:00:00+00:00"),
    ]
    features = compute_hop_features(hops)
    assert features["hop_count"] == 2
    assert features["net_distance_km"] > features["distances_km"][0]
    assert features["net_distance_km"] > features["distances_km"][1]
    # 2 hops over 1 elapsed hour -> velocity is a real, positive number.
    assert features["velocity_km_per_hour"] > 0


def test_channel_switch_ratio_reflects_actual_switches():
    hops = [
        _hop(13.0, 80.0, 13.01, 80.0, channel="upi", occurred_at="2026-08-27T09:00:00+00:00"),
        _hop(13.01, 80.0, 13.02, 80.0, channel="upi", occurred_at="2026-08-27T09:10:00+00:00"),
        _hop(13.02, 80.0, 13.03, 80.0, channel="imps", occurred_at="2026-08-27T09:20:00+00:00"),
    ]
    features = compute_hop_features(hops)
    # 2 consecutive-pairs, 1 switch (upi->upi, upi->imps) = 0.5
    assert features["channel_switch_ratio"] == pytest.approx(0.5)


def test_channel_switch_ratio_is_zero_for_a_single_hop():
    features = compute_hop_features([_hop(13.0, 80.0, 13.01, 80.0)])
    assert features["channel_switch_ratio"] == 0.0


@pytest.mark.parametrize(
    "bearing,expected_bucket",
    [
        (0.0, "N"), (20.0, "N"), (46.0, "NE"), (90.0, "E"),
        (135.0, "SE"), (180.0, "S"), (225.0, "SW"), (270.0, "W"),
        (315.0, "NW"), (359.0, "N"), (360.0, "N"),
    ],
)
def test_bucket_for_bearing_covers_all_eight_compass_points(bearing, expected_bucket):
    assert bucket_for_bearing(bearing) == expected_bucket


def test_bucket_center_deg_round_trips_for_every_bucket():
    for bucket in BEARING_BUCKETS:
        center = bucket_center_deg(bucket)
        assert bucket_for_bearing(center) == bucket


def test_feature_vector_is_fixed_length_and_numeric():
    features = compute_hop_features([_hop(13.0, 80.0, 13.01, 80.0)])
    vector = feature_vector(features)
    assert len(vector) == 7
    assert all(isinstance(v, float) for v in vector)


def test_feature_vector_imputes_null_velocity_to_zero_not_none():
    features = compute_hop_features([_hop(13.0, 80.0, 13.01, 80.0)])
    assert features["velocity_km_per_hour"] is None
    vector = feature_vector(features)
    # velocity is the 6th element (index 5) per feature_vector's fixed order
    assert vector[5] == 0.0


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (0.0, 0.0, 0.0),
        (0.0, 30.0, 30.0),
        (350.0, 10.0, 20.0),  # wraparound: 20deg apart, not 340
        (10.0, 350.0, 20.0),  # symmetric
        (0.0, 180.0, 180.0),  # antipodal, the maximum possible distance
        (359.0, 1.0, 2.0),
    ],
)
def test_circular_diff_deg_handles_wraparound(a, b, expected):
    assert _circular_diff_deg(a, b) == pytest.approx(expected)
