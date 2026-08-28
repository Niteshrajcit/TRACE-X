"""
Dynamic Risk Field Fusion - docs/AI_ML_ARCHITECTURE.md §5, Phase 2E.

Deliberately NOT a trained model - "Deterministic fusion, not ML" (§5's own
PROCESSING row). No ground truth, no held-out split, no learned parameters;
§5's own HOW EVALUATED row is explicit that only the fusion formula's
behavior is checked (decay curve matches spec, overlap combination is
order-independent), not a statistical metric - see this module's own tests.

    risk(cell, t) = Σ_active_complaints score(cell, complaint) · decay(t - t_generated)

"Active complaint" - Phase 2E Decision Freeze: status is NOT closed and NOT
rejected. No additional status categories invented.

The live field is an in-process, ephemeral cache
(docs/DATA_MODEL.md's `risk_field_cache[jurisdiction_id]` - Redis was
explicitly removed from this architecture, ARCHITECTURE.md §4) - never a
persisted table, never a migration. Historical replay (`?at=`) re-derives
the field from the durable `predictions` table at query time through the
exact same `compute_risk_field` function the live cache uses - one fusion
implementation, not two that could drift apart.
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus
from app.db.models.predictions import Prediction

settings = get_settings()

_INACTIVE_STATUSES = {ComplaintStatus.closed, ComplaintStatus.rejected}


def decay(elapsed_hours: float, half_life_hours: Optional[float] = None) -> float:
    """Exponential half-life decay: decay(0) = 1.0, decay(half_life) = 0.5,
    monotonically decreasing toward 0, never negative or > 1. Negative
    elapsed_hours (a prediction technically "generated after" the query
    instant - a data/ordering artifact, not a real case) is clamped to 0
    rather than producing a decay > 1."""
    half_life = half_life_hours if half_life_hours is not None else settings.risk_field_half_life_hours
    elapsed_hours = max(elapsed_hours, 0.0)
    return 0.5 ** (elapsed_hours / half_life)


def _as_utc(value: datetime) -> datetime:
    """SQLite (dev/test only - Postgres's TIMESTAMPTZ round-trips this
    correctly) drops tzinfo on stored DateTime(timezone=True) values, so a
    freshly-queried Prediction.generated_at can come back naive while `as_of`
    stays aware. The architecture stores everything in UTC, so a naive value
    is assumed to already be UTC rather than treated as a real ambiguity."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def touched_cells(ranked_locations: Optional[list]) -> set[str]:
    """The h3_cells one Prediction's ranked_locations touches - the bounded
    set incremental recomputation updates, never a jurisdiction's entire
    cell set."""
    return {entry["h3_cell"] for entry in (ranked_locations or []) if entry.get("h3_cell")}


def _active_predictions_for_jurisdiction(
    db: Session, jurisdiction_id: str, as_of: datetime
) -> list[Prediction]:
    """Every Prediction belonging to a currently-active complaint in this
    jurisdiction, generated at or before `as_of` - the exact durable data
    both the live cache and historical replay derive from."""
    return (
        db.query(Prediction)
        .join(Complaint, Complaint.complaint_id == Prediction.complaint_id)
        .filter(
            Complaint.jurisdiction_id == jurisdiction_id,
            Complaint.status.notin_(_INACTIVE_STATUSES),
            Prediction.generated_at <= as_of,
            Prediction.ranked_locations.isnot(None),
        )
        .all()
    )


def compute_risk_field(
    db: Session, jurisdiction_id: str, as_of: Optional[datetime] = None, half_life_hours: Optional[float] = None
) -> dict[str, float]:
    """The single source of truth for the fusion formula - used both to
    refresh the live in-process cache (as_of=now) and to serve historical
    replay (as_of=<past timestamp>). Additive across complaints/rings
    (each contributes independently, summed), and order-independent by
    construction (a plain sum has no notion of order)."""
    as_of = _as_utc(as_of or datetime.now(timezone.utc))
    scores: dict[str, float] = defaultdict(float)

    for prediction in _active_predictions_for_jurisdiction(db, jurisdiction_id, as_of):
        elapsed_hours = (as_of - _as_utc(prediction.generated_at)).total_seconds() / 3600.0
        weight = decay(elapsed_hours, half_life_hours)
        for entry in prediction.ranked_locations or []:
            h3_cell = entry.get("h3_cell")
            probability = entry.get("probability")
            if h3_cell is None or probability is None:
                continue
            scores[h3_cell] += float(probability) * weight

    return dict(scores)


# --- In-process ephemeral cache (docs/DATA_MODEL.md: risk_field_cache) ------

_risk_field_cache: dict[str, dict[str, float]] = {}
_risk_field_updated_at: dict[str, datetime] = {}


def get_cached_field(jurisdiction_id: str) -> dict[str, float]:
    return dict(_risk_field_cache.get(jurisdiction_id, {}))


def get_cache_generated_at(jurisdiction_id: str) -> Optional[datetime]:
    return _risk_field_updated_at.get(jurisdiction_id)


def reset_cache() -> None:
    """Test-only escape hatch, mirrors app/graph/corridor.py::reset_cached_model."""
    global _risk_field_cache, _risk_field_updated_at
    _risk_field_cache = {}
    _risk_field_updated_at = {}


def seed_cache_from_scratch(
    db: Session, jurisdiction_id: str, as_of: Optional[datetime] = None
) -> dict[str, float]:
    """Cold-start bootstrap for a jurisdiction the in-process cache has
    never computed anything for yet (e.g. right after a process restart,
    before the next transaction.ingested tick) - computes the full field
    once, since there is nothing cached yet to update incrementally."""
    as_of = as_of or datetime.now(timezone.utc)
    full_field = compute_risk_field(db, jurisdiction_id, as_of)
    _risk_field_cache[jurisdiction_id] = dict(full_field)
    _risk_field_updated_at[jurisdiction_id] = as_of
    return get_cached_field(jurisdiction_id)


def recompute_touched_cells(
    db: Session, jurisdiction_id: str, cells: set[str], as_of: Optional[datetime] = None
) -> dict[str, float]:
    """Incremental update: writes exactly the given cells' current
    (re-summed) values into the cache - every other cell already cached
    for this jurisdiction is left completely untouched, per §5's "only
    recomputed for touched cells." A known, disclosed scope note: deriving
    each touched cell's correct value still means summing every current
    contribution in the jurisdiction (there is no per-cell index over
    predictions.ranked_locations at this prototype's scale) - the
    *cache write* is what's incremental (untouched keys never change),
    not the underlying aggregation cost. See the Phase 2E closure report."""
    as_of = as_of or datetime.now(timezone.utc)
    if not cells:
        return get_cached_field(jurisdiction_id)

    full_field = compute_risk_field(db, jurisdiction_id, as_of)
    cache = _risk_field_cache.setdefault(jurisdiction_id, {})
    for cell in cells:
        if cell in full_field:
            cache[cell] = full_field[cell]
        else:
            cache.pop(cell, None)  # this cell's only contribution decayed out of the active set - remove, not stale
    _risk_field_updated_at[jurisdiction_id] = as_of
    return get_cached_field(jurisdiction_id)
