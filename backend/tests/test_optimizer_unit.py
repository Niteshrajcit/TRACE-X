"""
Pure/near-pure unit tests for app/graph/optimizer.py -
docs/AI_ML_ARCHITECTURE.md §7, Phase 2G. §7a/§7b's own "HOW EVALUATED" is a
coverage-ratio / expected-value-captured comparison against a naive
baseline - these tests check exactly that (including the PROJECT.md §7.5
"three ATMs on one street, one team suffices" case concretely), never a
fabricated accuracy number.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models.enums import ComplaintStatus, ExitChannelType, FraudType, InstitutionType, InterventionActionType
from app.db.models.exit_channels import ExitChannel
from app.db.models.complaints import Complaint
from app.db.models.predictions import Prediction
from app.graph.optimizer import (
    OptimizerInputError,
    _coverage_ratio,
    _greedy_coverage_selection,
    _hazard_at_request_time,
    _travel_time_min,
    determine_mode,
    optimize_deployment,
    run_coverage_maximization,
    run_resource_allocation,
)


# --- travel time / hazard proxies --------------------------------------------


def test_travel_time_min_uses_configured_speed():
    # settings.team_response_speed_kmh default is 30.0 km/h
    assert _travel_time_min(15.0) == pytest.approx(30.0)


def test_hazard_is_higher_for_a_shorter_window():
    urgent = _hazard_at_request_time([10.0, 20.0])  # midpoint 15
    relaxed = _hazard_at_request_time([100.0, 200.0])  # midpoint 150
    assert urgent > relaxed


def test_hazard_never_divides_by_zero():
    assert _hazard_at_request_time([0.0, 0.0]) == pytest.approx(1.0)  # floored at 1 minute


# --- greedy coverage maximization (§7a) --------------------------------------


def _candidate(exit_channel_id, probability, lat, lon):
    return {
        "exit_channel_id": exit_channel_id,
        "h3_cell": "cell",
        "channel_type": "atm_cash",
        "probability": probability,
        "time_window_min": [10.0, 30.0],
        "confidence_interval": [0.1, 0.9],
        "_lat": lat,
        "_lon": lon,
    }


def test_greedy_coverage_prefers_the_overlap_aware_pick_over_a_pure_probability_pick():
    """PROJECT.md §7.5: 'three adjacent high-risk ATMs... covered by one
    team' - here two candidates (A, B) are close together (one team covers
    both) and a third (C) is far away. Naive top-N-by-probability picks the
    two closest-by-probability (A, B) and wastes the second team on
    overlap; greedy picks A (covering both A and B) then C, covering
    everything."""
    a = _candidate("ch-a", 0.50, 13.00, 80.00)
    b = _candidate("ch-b", 0.45, 13.01, 80.01)  # ~1.4km from a - within the 5km default radius
    c = _candidate("ch-c", 0.40, 13.50, 80.50)  # ~65km away - outside the radius
    candidates = [a, b, c]

    selected_with_gain = _greedy_coverage_selection(candidates, team_count=2, coverage_radius_km=5.0)
    selected_ids = {point["exit_channel_id"] for point, _gain in selected_with_gain}
    assert selected_ids == {"ch-a", "ch-c"}

    greedy_ratio = _coverage_ratio(candidates, [p for p, _ in selected_with_gain], coverage_radius_km=5.0)
    naive_selected = sorted(candidates, key=lambda x: x["probability"], reverse=True)[:2]
    naive_ratio = _coverage_ratio(candidates, naive_selected, coverage_radius_km=5.0)

    assert greedy_ratio == pytest.approx(1.0)
    assert naive_ratio < greedy_ratio
    assert naive_ratio == pytest.approx(0.95 / 1.35, abs=1e-4)


def test_greedy_coverage_marginal_gain_excludes_already_covered_mass():
    a = _candidate("ch-a", 0.50, 13.00, 80.00)
    b = _candidate("ch-b", 0.45, 13.01, 80.01)
    selected_with_gain = _greedy_coverage_selection([a, b], team_count=2, coverage_radius_km=5.0)
    # First pick covers both (0.95); nothing is left uncovered for a second pick.
    assert len(selected_with_gain) == 1
    assert selected_with_gain[0][1] == pytest.approx(0.95)


def test_greedy_coverage_never_selects_more_points_than_team_count():
    candidates = [_candidate(f"ch-{i}", 0.1, 13.0 + i, 80.0 + i) for i in range(5)]
    selected_with_gain = _greedy_coverage_selection(candidates, team_count=2, coverage_radius_km=5.0)
    assert len(selected_with_gain) <= 2


def test_run_coverage_maximization_is_deterministic():
    a = _candidate("ch-a", 0.50, 13.00, 80.00)
    b = _candidate("ch-b", 0.45, 13.01, 80.01)
    ranked = [{k: v for k, v in a.items() if not k.startswith("_")}, {k: v for k, v in b.items() if not k.startswith("_")}]

    class FakeChannel:
        def __init__(self, lat, lon):
            self.geo_lat, self.geo_lon = lat, lon

    channels = {"ch-a": FakeChannel(13.00, 80.00), "ch-b": FakeChannel(13.01, 80.01)}
    team_locations = [{"lat": 13.00, "lon": 80.00}]

    first = run_coverage_maximization(ranked, channels, team_count=1, team_locations=team_locations)
    second = run_coverage_maximization(ranked, channels, team_count=1, team_locations=team_locations)
    assert first == second


def test_run_coverage_maximization_assigns_team_ids_by_input_order():
    a = _candidate("ch-a", 0.50, 13.00, 80.00)
    ranked = [{k: v for k, v in a.items() if not k.startswith("_")}]

    class FakeChannel:
        geo_lat, geo_lon = 13.00, 80.00

    result = run_coverage_maximization(ranked, {"ch-a": FakeChannel()}, team_count=1, team_locations=[{"lat": 12.0, "lon": 79.0}])
    assert result["assignment"][0]["team_id"] == "team-1"


# --- ranked knapsack (§7b) ----------------------------------------------------


def _ranked_entry(exit_channel_id, probability, window):
    return {
        "exit_channel_id": exit_channel_id,
        "h3_cell": "cell",
        "channel_type": "crypto_p2p",
        "probability": probability,
        "time_window_min": window,
        "confidence_interval": [0.1, 0.9],
    }


def test_resource_allocation_picks_by_expected_value_not_raw_probability_alone():
    """A lower-probability but far more urgent (shorter window) candidate
    can out-rank a higher-probability but relaxed one - this is exactly
    what distinguishes the real knapsack from 'the naive top-N by
    probability alone' baseline it's compared against."""
    high_prob_relaxed = _ranked_entry("ch-relaxed", 0.6, [500.0, 600.0])
    lower_prob_urgent = _ranked_entry("ch-urgent", 0.5, [2.0, 4.0])

    result = run_resource_allocation([high_prob_relaxed, lower_prob_urgent], amount_at_risk=100000.0, request_slot_count=1)
    assert result["assignment"][0]["exit_channel_id"] == "ch-urgent"


def test_resource_allocation_priority_rank_is_sequential_from_one():
    entries = [_ranked_entry(f"ch-{i}", 0.9 - i * 0.1, [10.0, 20.0]) for i in range(3)]
    result = run_resource_allocation(entries, amount_at_risk=50000.0, request_slot_count=3)
    assert [a["priority_rank"] for a in result["assignment"]] == [1, 2, 3]


def test_resource_allocation_naive_baseline_can_differ_from_optimized_selection():
    high_prob_relaxed = _ranked_entry("ch-relaxed", 0.6, [500.0, 600.0])
    lower_prob_urgent = _ranked_entry("ch-urgent", 0.5, [2.0, 4.0])
    result = run_resource_allocation([high_prob_relaxed, lower_prob_urgent], amount_at_risk=100000.0, request_slot_count=1)
    # Naive (probability alone) would have captured only the relaxed
    # candidate's share of total value - strictly less than the optimized pick here.
    assert result["naive_baseline_coverage"] < result["expected_coverage_total"]


def test_resource_allocation_is_deterministic():
    entries = [_ranked_entry(f"ch-{i}", 0.9 - i * 0.1, [10.0 * (i + 1), 20.0 * (i + 1)]) for i in range(4)]
    first = run_resource_allocation(entries, amount_at_risk=75000.0, request_slot_count=2)
    second = run_resource_allocation(entries, amount_at_risk=75000.0, request_slot_count=2)
    assert first == second


def test_resource_allocation_handles_empty_candidates_honestly():
    result = run_resource_allocation([], amount_at_risk=100000.0, request_slot_count=3)
    assert result == {"assignment": [], "expected_coverage_total": 0.0, "naive_baseline_coverage": 0.0}


# --- mode determination (DB-backed) ------------------------------------------


def _make_exit_channel(db, action_type):
    channel = ExitChannel(
        channel_type=ExitChannelType.atm_cash,
        external_ref="ATM-TEST",
        geo_lat=13.0,
        geo_lon=80.0,
        h3_cell="cell1",
        intervention_action_type=action_type,
    )
    db.add(channel)
    db.flush()
    return channel


def _make_complaint_and_prediction(db, ranked_locations):
    victim = None
    from app.db.models.accounts import Account

    victim = Account(account_hash=f"opt-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"OPT-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=200000,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Optimizer unit test complaint",
        victim_account_id=victim.account_id,
        status=ComplaintStatus.new,
    )
    db.add(complaint)
    db.flush()
    prediction = Prediction(
        complaint_id=complaint.complaint_id,
        generated_at=datetime.now(timezone.utc),
        ranked_locations=ranked_locations,
    )
    db.add(prediction)
    db.flush()
    return complaint, prediction


def test_determine_mode_maps_physical_team_deployment_to_coverage_maximization(db):
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _complaint, prediction = _make_complaint_and_prediction(
        db, [{"exit_channel_id": channel.channel_id, "probability": 0.5, "h3_cell": "c", "channel_type": "atm_cash", "time_window_min": [10, 20], "confidence_interval": [0.1, 0.9]}]
    )
    mode, top_channel = determine_mode(db, prediction)
    assert mode.value == "coverage_maximization"
    assert top_channel.channel_id == channel.channel_id


def test_determine_mode_maps_exchange_freeze_to_resource_allocation(db):
    channel = _make_exit_channel(db, InterventionActionType.exchange_freeze_request)
    _complaint, prediction = _make_complaint_and_prediction(
        db, [{"exit_channel_id": channel.channel_id, "probability": 0.5, "h3_cell": "c", "channel_type": "crypto_p2p", "time_window_min": [10, 20], "confidence_interval": [0.1, 0.9]}]
    )
    mode, _ = determine_mode(db, prediction)
    assert mode.value == "resource_allocation"


def test_determine_mode_raises_honest_error_when_no_ranked_locations(db):
    _complaint, prediction = _make_complaint_and_prediction(db, None)
    with pytest.raises(OptimizerInputError):
        determine_mode(db, prediction)


def test_optimize_deployment_raises_when_body_does_not_match_detected_mode(db):
    channel = _make_exit_channel(db, InterventionActionType.physical_team_deployment)
    _complaint, prediction = _make_complaint_and_prediction(
        db, [{"exit_channel_id": channel.channel_id, "probability": 0.5, "h3_cell": "c", "channel_type": "atm_cash", "time_window_min": [10, 20], "confidence_interval": [0.1, 0.9]}]
    )
    with pytest.raises(OptimizerInputError):
        optimize_deployment(db, prediction, request_slot_count=3)  # wrong body for coverage_maximization mode
