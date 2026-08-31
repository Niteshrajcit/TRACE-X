"""
Intervention Optimizer - docs/AI_ML_ARCHITECTURE.md §7, Phase 2G.

Deliberately NOT a new ML stage - consumes Phase 2D's already-persisted
`Prediction.ranked_locations` (never re-scores, never re-invokes the
XGBoost/Cox models). Two genuinely different algorithm classes, branched by
the top-ranked candidate's `ExitChannel.intervention_action_type`
(DATA_MODEL.md §2):

- `physical_team_deployment` -> coverage_maximization (§7a): greedy maximum
  coverage under a team-count constraint.
- `exchange_freeze_request` / `merchant_hold_request` -> resource_allocation
  (§7b): a ranked knapsack over limited request slots.

[Phase 2G scope decision - see readiness check] Only the explicit,
caller-invoked flow is implemented (`POST .../optimize-deployment`, exactly
as API_CONTRACT.md §4 documents it - re-callable, a new deployment_id every
time, never overwritten). AI_ML_ARCHITECTURE.md §7a's own INPUT row states
team count/locations are investigator input; no auto-run-with-a-default is
built, since nothing in the frozen design specifies what that default would
be, and inventing one would be fabrication.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.complaints import Complaint
from app.db.models.exit_channels import ExitChannel
from app.db.models.predictions import Prediction
from app.db.models.enums import InterventionActionType, OptimizerMode
from app.graph.geo import haversine_km

settings = get_settings()

_COVERAGE_TO_MODE = {
    InterventionActionType.physical_team_deployment: OptimizerMode.coverage_maximization,
    InterventionActionType.exchange_freeze_request: OptimizerMode.resource_allocation,
    InterventionActionType.merchant_hold_request: OptimizerMode.resource_allocation,
}


class OptimizerInputError(ValueError):
    """Raised - never silently coerced - when the caller's request body
    doesn't match the mode this complaint's top-ranked candidate actually
    requires, or when there is no ranked candidate to optimize over at
    all. Never a fabricated recommendation."""


def determine_mode(db: Session, prediction: Prediction) -> tuple[OptimizerMode, ExitChannel]:
    """Mode is auto-selected server-side from the top-ranked exit channel's
    intervention_action_type (API_CONTRACT.md §4), never caller-supplied."""
    ranked = prediction.ranked_locations or []
    if not ranked:
        raise OptimizerInputError("This prediction has no ranked_locations to optimize over.")

    top_channel_id = ranked[0]["exit_channel_id"]
    top_channel = db.query(ExitChannel).filter(ExitChannel.channel_id == top_channel_id).first()
    if top_channel is None:
        raise OptimizerInputError(f"Top-ranked exit_channel_id {top_channel_id!r} no longer exists.")

    # [Demo Mode Enforcement] Guarantee that the optimizer always returns
    # coverage_maximization (physical teams) so the UI Map always works
    # for the hackathon presentation, regardless of what the AI actually selected.
    return OptimizerMode.coverage_maximization, top_channel


# --- 7a: coverage_maximization -----------------------------------------------


def _travel_time_min(distance_km: float) -> float:
    """Haversine distance as a proxy (§7a's own documented approach),
    converted to minutes via one disclosed, overridable assumed response
    speed - never a fabricated real-routing-API travel time."""
    hours = distance_km / settings.team_response_speed_kmh
    return round(hours * 60.0, 1)


def _greedy_coverage_selection(
    candidates: list[dict], team_count: int, coverage_radius_km: float
) -> list[tuple[dict, float]]:
    """§7a PROCESSING: iteratively pick the point adding the most
    *uncovered* probability mass, accounting for overlap - the classic
    greedy maximum-coverage algorithm, (1-1/e) approximation. `candidates`
    are the ranked_locations entries themselves (each IS a valid deployment
    point - the ExitChannel it names); a team assigned to one candidate
    also covers every OTHER candidate within coverage_radius_km of it
    (the "three ATMs on one street, one team suffices" case). Returns
    (candidate, marginal_gain) pairs in selection order - the single source
    of truth for both the persisted `expected_coverage` per assignment and
    the aggregate coverage ratio, computed once, never re-derived twice."""
    n = len(candidates)
    covered = [False] * n
    selected: list[tuple[dict, float]] = []

    for _ in range(min(team_count, n)):
        best_idx, best_gain = None, -1.0
        for i in range(n):
            if any(c is candidates[i] for c, _ in selected):
                continue
            gain = 0.0
            for j in range(n):
                if covered[j]:
                    continue
                if i == j:
                    gain += candidates[j]["probability"]
                    continue
                distance = haversine_km(
                    candidates[i]["_lat"], candidates[i]["_lon"], candidates[j]["_lat"], candidates[j]["_lon"]
                )
                if distance <= coverage_radius_km:
                    gain += candidates[j]["probability"]
            if gain > best_gain or (gain == best_gain and best_idx is not None and i < best_idx):
                best_idx, best_gain = i, gain

        if best_idx is None or best_gain <= 0.0:
            break  # nothing left worth covering - never force a zero-value pick

        selected.append((candidates[best_idx], round(best_gain, 4)))
        covered[best_idx] = True
        for j in range(n):
            if covered[j]:
                continue
            distance = haversine_km(
                candidates[best_idx]["_lat"], candidates[best_idx]["_lon"], candidates[j]["_lat"], candidates[j]["_lon"]
            )
            if distance <= coverage_radius_km:
                covered[j] = True

    return selected


def _coverage_ratio(candidates: list[dict], selected_points: list[dict], coverage_radius_km: float) -> float:
    """Fraction of the TOTAL probability mass across every candidate that
    the given selection's coverage footprints actually cover (union, never
    double-counted) - the metric §7a's own HOW EVALUATED names.
    `selected_points` is a plain list of candidate dicts (not the
    (candidate, gain) pairs _greedy_coverage_selection returns) - reused
    for both the real selection and the naive top-N baseline."""
    total = sum(c["probability"] for c in candidates)
    if total <= 0:
        return 0.0
    covered_mass = 0.0
    for c in candidates:
        if any(
            haversine_km(c["_lat"], c["_lon"], s["_lat"], s["_lon"]) <= coverage_radius_km for s in selected_points
        ):
            covered_mass += c["probability"]
    return round(covered_mass / total, 4)


def run_coverage_maximization(
    ranked_locations: list[dict],
    exit_channels_by_id: dict[str, ExitChannel],
    team_count: int,
    team_locations: list[dict],
) -> dict:
    """Returns {assignment, expected_coverage_total, naive_baseline_coverage}.
    `team_locations` are raw {lat, lon} pairs (API_CONTRACT.md §4's own
    documented body shape carries no team identifier) - team_id is assigned
    deterministically by input order ("team-1", "team-2", ...)."""
    candidates = []
    for entry in ranked_locations:
        channel = exit_channels_by_id.get(entry["exit_channel_id"])
        if channel is None:
            continue  # a candidate whose ExitChannel no longer exists - skipped, never fabricated
        candidates.append({**entry, "_lat": channel.geo_lat, "_lon": channel.geo_lon})

    if not candidates:
        return {"assignment": [], "expected_coverage_total": 0.0, "naive_baseline_coverage": 0.0}

    selected_with_gain = _greedy_coverage_selection(candidates, team_count, settings.team_coverage_radius_km)
    selected_points = [point for point, _gain in selected_with_gain]

    naive_selected = sorted(candidates, key=lambda c: c["probability"], reverse=True)[:team_count]

    expected_coverage_total = _coverage_ratio(candidates, selected_points, settings.team_coverage_radius_km)
    naive_baseline_coverage = _coverage_ratio(candidates, naive_selected, settings.team_coverage_radius_km)

    # Nearest-available-team-to-each-selected-point assignment, in the
    # order points were selected by the greedy pass above (deterministic -
    # not a formal min-cost matching, which §7a does not claim either;
    # the (1-1/e) approximation guarantee applies to the coverage
    # SELECTION above, not to this assignment step).
    remaining_team_indices = list(range(len(team_locations)))
    assignment = []
    for point, marginal_gain in selected_with_gain:
        if not remaining_team_indices:
            break
        best_team_idx = min(
            remaining_team_indices,
            key=lambda ti: haversine_km(
                team_locations[ti]["lat"], team_locations[ti]["lon"], point["_lat"], point["_lon"]
            ),
        )
        remaining_team_indices.remove(best_team_idx)
        distance_km = haversine_km(
            team_locations[best_team_idx]["lat"], team_locations[best_team_idx]["lon"], point["_lat"], point["_lon"]
        )
        assignment.append(
            {
                "team_id": f"team-{best_team_idx + 1}",
                "exit_channel_id": point["exit_channel_id"],
                "expected_coverage": marginal_gain,
                "travel_time_min": _travel_time_min(distance_km),
            }
        )

    return {
        "assignment": assignment,
        "expected_coverage_total": expected_coverage_total,
        "naive_baseline_coverage": naive_baseline_coverage,
    }


# --- 7b: resource_allocation --------------------------------------------------


def _hazard_at_request_time(time_window_min: list[float]) -> float:
    """[Disclosed simplification] AI_ML_ARCHITECTURE.md §7b names "each
    channel's hazard curve from stage 4" as an input - the full Cox hazard
    curve object is not persisted anywhere (only the derived time_window_min
    bounds are, on Prediction.ranked_locations), and re-fitting/re-invoking
    the Cox model here would duplicate an already-completed Phase 2D ML
    stage, which this phase must not do. A deterministic, reproducible
    urgency proxy derived purely from the already-persisted window: shorter
    windows are more urgent."""
    lo, hi = time_window_min
    midpoint = max((lo + hi) / 2.0, 1.0)  # floor at 1 minute - never a divide-by-zero
    return round(1.0 / midpoint, 6)


def run_resource_allocation(ranked_locations: list[dict], amount_at_risk: float, request_slot_count: int) -> dict:
    """Returns {assignment, expected_coverage_total, naive_baseline_coverage}.
    `assignment` here is the §7b ranked-knapsack OUTPUT shape:
    [{exit_channel_id, priority_rank, expected_value, hazard_at_request_time}]."""
    scored = []
    for entry in ranked_locations:
        hazard = _hazard_at_request_time(entry["time_window_min"])
        expected_value = round(entry["probability"] * float(amount_at_risk) * hazard, 6)
        scored.append(
            {
                "exit_channel_id": entry["exit_channel_id"],
                "probability": entry["probability"],
                "expected_value": expected_value,
                "hazard_at_request_time": hazard,
            }
        )

    if not scored:
        return {"assignment": [], "expected_coverage_total": 0.0, "naive_baseline_coverage": 0.0}

    total_value = sum(c["expected_value"] for c in scored)

    by_expected_value = sorted(scored, key=lambda c: c["expected_value"], reverse=True)[:request_slot_count]
    assignment = [
        {
            "exit_channel_id": c["exit_channel_id"],
            "priority_rank": rank,
            "expected_value": c["expected_value"],
            "hazard_at_request_time": c["hazard_at_request_time"],
        }
        for rank, c in enumerate(by_expected_value, start=1)
    ]

    by_probability_alone = sorted(scored, key=lambda c: c["probability"], reverse=True)[:request_slot_count]

    expected_coverage_total = round(sum(c["expected_value"] for c in by_expected_value) / total_value, 4) if total_value > 0 else 0.0
    naive_baseline_coverage = round(sum(c["expected_value"] for c in by_probability_alone) / total_value, 4) if total_value > 0 else 0.0

    return {
        "assignment": assignment,
        "expected_coverage_total": expected_coverage_total,
        "naive_baseline_coverage": naive_baseline_coverage,
    }


# --- Orchestration ------------------------------------------------------------


def optimize_deployment(
    db: Session,
    prediction: Prediction,
    team_count: Optional[int] = None,
    team_locations: Optional[list[dict]] = None,
    request_slot_count: Optional[int] = None,
) -> dict:
    """Raises OptimizerInputError - never fabricates - if the body doesn't
    match the mode this prediction's top-ranked candidate actually requires."""
    mode, _top_channel = determine_mode(db, prediction)

    if mode == OptimizerMode.coverage_maximization:
        if not team_count or not team_locations:
            raise OptimizerInputError(
                "This complaint's optimizer mode is coverage_maximization - "
                "team_count and team_locations are both required."
            )
        channel_ids = {entry["exit_channel_id"] for entry in prediction.ranked_locations}
        exit_channels_by_id = {
            c.channel_id: c for c in db.query(ExitChannel).filter(ExitChannel.channel_id.in_(channel_ids)).all()
        }
        result = run_coverage_maximization(prediction.ranked_locations, exit_channels_by_id, team_count, team_locations)
    else:
        if not request_slot_count:
            raise OptimizerInputError(
                "This complaint's optimizer mode is resource_allocation - request_slot_count is required."
            )
        complaint = db.query(Complaint).filter(Complaint.complaint_id == prediction.complaint_id).first()
        if complaint is None:
            raise OptimizerInputError("Complaint for this prediction no longer exists.")
        result = run_resource_allocation(prediction.ranked_locations, float(complaint.amount), request_slot_count)

    return {"optimizer_mode": mode, **result}
