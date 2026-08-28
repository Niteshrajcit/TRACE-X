"""
Explainer - AI_ML_ARCHITECTURE.md §6, Phase 2F.

Deliberately NOT a trained model of its own - §11's own summary table is
explicit: "Explainability | No (derives from stage 4's model) | Tracks
stage 4's version." This module only computes `shap.TreeExplainer`'s exact
(not approximated) Shapley values against the already-trained Phase 2D
XGBoost classifier and the exact feature vector persisted at scoring time
(app/graph/exit_scorer.py) - never a freshly-recomputed, possibly-drifted
approximation of that vector, and never a fabricated one when no snapshot
was ever persisted for a given prediction (see `ExplanationUnavailable`).

[Phase 2F decision freeze #1] Exact per-candidate feature vectors are only
persisted going forward (app/graph/exit_scorer.py's additive
`feature_snapshot` write) - a Prediction made before that change has no
snapshot and is honestly reported unavailable for exact explanation here,
never silently reconstructed from a freshly-recomputed vector that could
differ from what was actually scored.

[Phase 2F decision freeze #3] `top_factors` is `[{feature, weight,
direction}]` - `direction` derived deterministically from the SHAP value's
sign. No `evidence_ref` field (no evidence-reference contract has been
defined anywhere in this project yet).
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import shap
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus
from app.db.models.predictions import Prediction
from app.graph.exit_scorer import get_or_train_classifier
from app.graph.graph_path import compute_graph_path

logger = get_logger(__name__)

_INACTIVE_STATUSES = {ComplaintStatus.closed, ComplaintStatus.rejected}
_TOP_N_FACTORS = 3
_TOP_N_COMPARABLE_CASES = 3


class ExplanationUnavailable(Exception):
    """Raised - never silently swallowed into a fabricated result - when a
    real explanation genuinely cannot be produced: no persisted feature
    snapshot for the requested (prediction_id, exit_channel_id) pair."""


# --- SHAP -> top_factors (STEP 1) --------------------------------------------


def direction_from_shap_value(value: float) -> str:
    """Deterministic sign mapping - decision freeze #3. A SHAP value pushes
    the model's raw margin output up (toward predicting "exits here") or
    down; there is no third case worth a special label at floating-point
    scale, but an exact zero (a feature that provably contributed nothing
    for this specific prediction) is reported as such rather than
    arbitrarily bucketed into a direction it didn't actually have."""
    if value > 0:
        return "increases_risk"
    if value < 0:
        return "decreases_risk"
    return "neutral"


_shap_explainer_cache: dict[int, "shap.TreeExplainer"] = {}


def _get_tree_explainer(classifier) -> "shap.TreeExplainer":
    """Cached per fitted classifier instance (id()) - mirrors
    app/graph/exit_scorer.py's own in-process model caching philosophy.
    Building a TreeExplainer re-walks the whole tree ensemble; there is
    exactly one active classifier per process between retrains, so this
    cache never grows unbounded within a process lifetime."""
    key = id(classifier)
    explainer = _shap_explainer_cache.get(key)
    if explainer is None:
        explainer = shap.TreeExplainer(classifier)
        _shap_explainer_cache[key] = explainer
    return explainer


def reset_shap_explainer_cache() -> None:
    """Test-only escape hatch, mirrors app/graph/exit_scorer.py::reset_cached_models."""
    _shap_explainer_cache.clear()


def compute_top_factors(classifier, feature_dict: dict, feature_order: list[str], top_n: int = _TOP_N_FACTORS) -> list[dict]:
    """Exact SHAP attribution for one specific feature vector against one
    specific fitted classifier - deterministic given both (TreeExplainer
    has no sampling/randomness for tree ensembles, unlike KernelExplainer).
    Ranked by absolute contribution, ties broken by feature_order's own
    stable order (Python's sort is stable) so output is byte-identical
    across repeated calls with unchanged inputs."""
    x = np.array([[feature_dict[key] for key in feature_order]])
    explainer = _get_tree_explainer(classifier)
    raw = explainer.shap_values(x)

    if isinstance(raw, list):
        # Older/alternate SHAP return shape: one array per class - the
        # positive class (index 1) is "P(exit at this channel)", the one
        # this model and every caller of it cares about.
        values = raw[1][0] if len(raw) > 1 else raw[0][0]
    else:
        values = raw[0]

    ranked = sorted(
        range(len(feature_order)),
        key=lambda i: (-abs(float(values[i])), feature_order[i]),
    )
    return [
        {
            "feature": feature_order[i],
            "weight": round(float(values[i]), 6),
            "direction": direction_from_shap_value(float(values[i])),
        }
        for i in ranked[:top_n]
    ]


# --- Plain-language template (STEP 2) ----------------------------------------


def generate_plain_language(top_factors: list[dict], graph_path: dict) -> str:
    """Deterministic, built only from real computed values - never the
    fabricated example wording in PROJECT.md §7.4 (which references
    HISTORICALLY_EXITED_VIA cross-ring data no phase has ever built - see
    the Phase 2F readiness report). Every clause here traces to an actual
    field: top_factors' own feature names, and the real (never
    fabricated) graph path's hop count."""
    if not top_factors:
        return "Ranked based on the model's output; no individual contributing factor was strong enough to report."

    leading = top_factors[0]
    leading_phrase = f"'{leading['feature']}' ({leading['direction'].replace('_', ' ')}, weight {leading['weight']})"

    if len(top_factors) > 1:
        second = top_factors[1]
        leading_phrase += f" and '{second['feature']}' ({second['direction'].replace('_', ' ')}, weight {second['weight']})"

    hop_clause = ""
    real_path = graph_path.get("real_path") or []
    if graph_path.get("path_complete") and len(real_path) > 1:
        hop_clause = f", following a real {len(real_path) - 1}-hop transfer chain from the victim account"

    return f"Ranked based on {leading_phrase}{hop_clause}."


# --- Comparable historical cases (STEP 3) ------------------------------------


def _euclidean_distance(a: list[float], b: list[float]) -> float:
    return float(np.linalg.norm(np.array(a) - np.array(b)))


def find_comparable_cases(
    db: Session, feature_dict: dict, feature_order: list[str], exclude_complaint_id: str, top_n: int = _TOP_N_COMPARABLE_CASES
) -> list[dict]:
    """Nearest neighbors, by Euclidean distance in the same feature space,
    among resolved (closed/rejected) complaints' OWN persisted feature
    snapshots. Returns [] - honestly, never a fabricated placeholder -
    when no other resolved complaint has ever had a feature snapshot
    persisted for it (the real, current state of most of this dataset,
    per the Phase 2F readiness report's disclosed data gap)."""
    x = [feature_dict[key] for key in feature_order]

    resolved_complaint_ids = {
        row[0]
        for row in db.query(Complaint.complaint_id)
        .filter(Complaint.status.in_(_INACTIVE_STATUSES), Complaint.complaint_id != exclude_complaint_id)
        .all()
    }
    if not resolved_complaint_ids:
        return []

    candidates: list[tuple[float, str, str]] = []  # (distance, complaint_id, exit_channel_id)
    predictions = db.query(Prediction).filter(Prediction.complaint_id.in_(resolved_complaint_ids)).all()
    for prediction in predictions:
        snapshot = prediction.feature_snapshot or {}
        candidate_order = snapshot.get("feature_order")
        by_channel = snapshot.get("by_exit_channel_id") or {}
        if not candidate_order or not by_channel:
            continue  # no real snapshot persisted for this resolved complaint - never compared against
        if candidate_order != feature_order:
            # A different feature schema than the one being explained (e.g.
            # persisted before a future feature-set change) - never compared
            # against as if compatible, silently skipped rather than
            # producing a meaningless distance.
            continue
        for exit_channel_id, candidate_features in by_channel.items():
            try:
                candidate_x = [candidate_features[key] for key in candidate_order]
            except KeyError:
                continue
            candidates.append((_euclidean_distance(x, candidate_x), prediction.complaint_id, exit_channel_id))

    if not candidates:
        return []

    candidates.sort(key=lambda c: (c[0], c[1], c[2]))

    complaints_by_id = {
        c.complaint_id: c
        for c in db.query(Complaint).filter(Complaint.complaint_id.in_({c[1] for c in candidates[:top_n]})).all()
    }

    results = []
    for distance, complaint_id, _exit_channel_id in candidates[:top_n]:
        complaint = complaints_by_id.get(complaint_id)
        if complaint is None:
            continue
        results.append(
            {
                "complaint_id": complaint_id,
                "similarity_score": round(1.0 / (1.0 + distance), 4),
                "summary": f"{complaint.fraud_type.value} complaint, amount {complaint.amount}",
            }
        )
    return results


# --- Orchestration (STEP 4) ---------------------------------------------------


@dataclass
class ExplanationResult:
    top_factors: list[dict]
    graph_path: dict
    comparable_cases: list[dict]
    plain_language: str
    exit_channel_id: str
    prediction_id: str
    complaint_id: str = field(default="")


def explain_prediction(db: Session, prediction: Prediction, exit_channel_id: Optional[str] = None) -> ExplanationResult:
    """Computes a full explanation for one (prediction, exit_channel)
    pair. Raises ExplanationUnavailable - never fabricates - if this
    Prediction has no persisted feature_snapshot, or the requested
    exit_channel_id isn't among the ones that were actually scored and
    snapshotted for it."""
    snapshot = prediction.feature_snapshot or {}
    feature_order = snapshot.get("feature_order")
    by_channel = snapshot.get("by_exit_channel_id") or {}
    ring_id = snapshot.get("ring_id")

    if not feature_order or not by_channel:
        raise ExplanationUnavailable(
            "No feature snapshot was persisted for this prediction - it was generated before Phase 2F's "
            "feature-vector persistence, or scoring produced no ranked candidates. Not fabricated, not "
            "recomputed from a possibly-drifted approximation."
        )

    if exit_channel_id is None:
        ranked = prediction.ranked_locations or []
        if not ranked:
            raise ExplanationUnavailable("This prediction has no ranked_locations to explain.")
        exit_channel_id = ranked[0]["exit_channel_id"]

    feature_dict = by_channel.get(exit_channel_id)
    if feature_dict is None:
        raise ExplanationUnavailable(
            f"exit_channel_id {exit_channel_id!r} was not among the candidates scored and snapshotted for this prediction."
        )

    classifier = get_or_train_classifier(db).classifier
    top_factors = compute_top_factors(classifier, feature_dict, feature_order)

    member_account_ids: list[str] = []
    if ring_id:
        from app.db.models.rings import DetectedRingMember

        member_account_ids = [
            row[0] for row in db.query(DetectedRingMember.account_id).filter(DetectedRingMember.ring_id == ring_id).all()
        ]

    if member_account_ids:
        graph_path = compute_graph_path(db, prediction.complaint_id, member_account_ids, exit_channel_id)
    else:
        # No ring_id on this snapshot (pre-Phase-2F prediction whose
        # feature_snapshot somehow lacks it) - never a fabricated path.
        graph_path = {"real_path": [], "predicted_exit_channel_id": exit_channel_id, "path_complete": False}

    comparable_cases = find_comparable_cases(db, feature_dict, feature_order, exclude_complaint_id=prediction.complaint_id)
    plain_language = generate_plain_language(top_factors, graph_path)

    return ExplanationResult(
        top_factors=top_factors,
        graph_path=graph_path,
        comparable_cases=comparable_cases,
        plain_language=plain_language,
        exit_channel_id=exit_channel_id,
        prediction_id=prediction.prediction_id,
        complaint_id=prediction.complaint_id,
    )
