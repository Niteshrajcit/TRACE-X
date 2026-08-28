"""
Wires ring detection, corridor prediction, exit-channel/time-window scoring,
and risk-field fusion into the existing in-process event dispatcher
(docs/AI_ML_ARCHITECTURE.md §2/§3/§4/§5, this phase's event-pipeline
requirement):

    transaction.ingested -> graph.updated -> intelligence.started
    -> ring detection -> ring.detected
    -> corridor prediction -> corridor_prediction.completed
    -> exit-channel + time-window scoring -> exit_prediction.completed

    transaction.ingested -> risk-field recomputation -> risk_field.updated
    [Phase 2E, decision-frozen trigger - see _on_transaction_ingested_for_risk_field]

    exit_prediction.completed -> Explainer -> explanation.generated
    [Phase 2F]

No Redis, no second event system - the same dispatcher app/events/dispatcher.py
already provides, exactly as every other stage in this codebase uses it.
"""
from typing import Optional

from starlette.concurrency import run_in_threadpool

from app.audit.service import append_audit_event
from app.core.logging_config import get_logger
from app.db.models.complaints import Complaint
from app.db.models.predictions import Prediction
from app.db.session import SessionLocal
from app.events.dispatcher import dispatcher
from app.events.topics import (
    CORRIDOR_PREDICTION_COMPLETED,
    EXIT_PREDICTION_COMPLETED,
    EXPLANATION_GENERATED,
    GRAPH_UPDATED,
    INTELLIGENCE_STARTED,
    RING_DETECTED,
    RISK_FIELD_UPDATED,
    TRANSACTION_INGESTED,
)
from app.graph.corridor import run_corridor_prediction_for_complaint
from app.graph.exit_scorer import run_exit_scoring_for_ring
from app.graph.explainer import ExplanationUnavailable, explain_prediction
from app.graph.ring_service import run_ring_detection
from app.graph.risk_field import recompute_touched_cells, touched_cells

logger = get_logger(__name__)


def _run_detection_sync() -> dict:
    db = SessionLocal()
    try:
        return run_ring_detection(db)
    finally:
        db.close()


async def _on_graph_updated(payload: dict) -> None:
    complaint_id = payload.get("complaint_id")

    await dispatcher.publish(INTELLIGENCE_STARTED, {"complaint_id": complaint_id, "stage": "ring_detection"})

    try:
        summary = await run_in_threadpool(_run_detection_sync)
    except Exception as exc:  # Neo4j unreachable, etc. - never let this break the ingestion path
        logger.warning("ring_detection.failed", extra={"extra_fields": {"error": str(exc)}})
        return

    await dispatcher.publish(
        RING_DETECTED,
        {
            "complaint_id": complaint_id,
            "communities_detected": summary["communities_detected"],
            "graph_nodes": summary["graph_nodes"],
            "graph_edges": summary["graph_edges"],
            "modularity": summary["modularity"],
            "algorithm": summary["algorithm"],
        },
    )


def _run_corridor_prediction_sync(complaint_id: str) -> list[dict]:
    db = SessionLocal()
    try:
        return run_corridor_prediction_for_complaint(db, complaint_id)
    finally:
        db.close()


async def _on_ring_detected(payload: dict) -> None:
    """[Phase 2C] Re-reads Postgres by complaint_id (detected_ring_complaints)
    rather than requiring RING_DETECTED's payload to carry per-ring
    identifying data it doesn't have - keeps Phase 2B's already-verified
    event contract untouched. Pure Postgres work throughout (no Neo4j
    involved in corridor prediction at all), so a failure here can never
    affect the graph/ring pipeline that already completed successfully."""
    complaint_id = payload.get("complaint_id")
    if complaint_id is None:
        return

    try:
        results = await run_in_threadpool(_run_corridor_prediction_sync, complaint_id)
    except Exception as exc:  # insufficient ground truth, etc. - never break the ring pipeline
        logger.warning("corridor_prediction.failed", extra={"extra_fields": {"complaint_id": complaint_id, "error": str(exc)}})
        return

    for result in results:
        await dispatcher.publish(
            CORRIDOR_PREDICTION_COMPLETED,
            {
                "complaint_id": complaint_id,
                "ring_id": result["ring_id"],
                "prediction_id": result["prediction_id"],
                "exit_vector": result["exit_vector"],
                "model_version_corridor": result["model_version_corridor"],
            },
        )


def _run_exit_scoring_sync(complaint_id: str, ring_id: str, prediction_id: str, exit_vector: dict) -> Optional[dict]:
    db = SessionLocal()
    try:
        return run_exit_scoring_for_ring(db, complaint_id, ring_id, prediction_id, exit_vector)
    finally:
        db.close()


async def _on_corridor_prediction_completed(payload: dict) -> None:
    """[Phase 2D] CORRIDOR_PREDICTION_COMPLETED already carries prediction_id
    and exit_vector directly (Phase 2C's event, unmodified) - this handler
    never needs to guess which Prediction row to update. Pure Postgres
    work (candidate exit channels, XGBoost, Cox), no Neo4j involved, so a
    failure here can never affect the ring/corridor pipeline that already
    completed successfully."""
    complaint_id = payload.get("complaint_id")
    ring_id = payload.get("ring_id")
    prediction_id = payload.get("prediction_id")
    exit_vector = payload.get("exit_vector")
    if not (complaint_id and ring_id and prediction_id and exit_vector):
        return

    try:
        result = await run_in_threadpool(
            _run_exit_scoring_sync, complaint_id, ring_id, prediction_id, exit_vector
        )
    except Exception as exc:  # insufficient ground truth, etc. - never break the corridor pipeline
        logger.warning(
            "exit_scoring.failed",
            extra={"extra_fields": {"complaint_id": complaint_id, "ring_id": ring_id, "error": str(exc)}},
        )
        return
    if result is None:
        return

    await dispatcher.publish(
        EXIT_PREDICTION_COMPLETED,
        {
            "complaint_id": complaint_id,
            "ring_id": ring_id,
            "prediction_id": result["prediction_id"],
            "ranked_locations": result["ranked_locations"],
            "model_version_location": result["model_version_location"],
            "model_version_time": result["model_version_time"],
        },
    )


def _run_risk_field_recompute_sync(complaint_id: str) -> Optional[dict]:
    """[Phase 2E] Decision-frozen trigger is transaction.ingested itself, not
    a later pipeline stage - so on most transactions this complaint will not
    yet have a Prediction with ranked_locations (ring/corridor/exit-scoring
    for THIS transaction hasn't run yet, since transaction.ingested fires
    before graph.updated). That is a genuine, disclosed timing characteristic
    of the frozen design, not a bug: it means most transaction.ingested ticks
    find zero touched cells and correctly do nothing, while a fused field
    still forms once a complaint's prediction is (re)computed after enough
    hops accumulate and a later transaction.ingested tick fires."""
    db = SessionLocal()
    try:
        complaint = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
        if complaint is None or complaint.jurisdiction_id is None:
            return None

        prediction = db.query(Prediction).filter(Prediction.complaint_id == complaint_id).first()
        if prediction is None or prediction.ranked_locations is None:
            return None

        cells = touched_cells(prediction.ranked_locations)
        if not cells:
            return None

        recompute_touched_cells(db, complaint.jurisdiction_id, cells)
        return {"jurisdiction_id": complaint.jurisdiction_id, "changed_cells": sorted(cells)}
    finally:
        db.close()


async def _on_transaction_ingested_for_risk_field(payload: dict) -> None:
    complaint_id = payload.get("complaint_id")
    if not complaint_id:
        return

    try:
        result = await run_in_threadpool(_run_risk_field_recompute_sync, complaint_id)
    except Exception as exc:  # never let a risk-field hiccup break transaction ingestion
        logger.warning("risk_field.recompute_failed", extra={"extra_fields": {"complaint_id": complaint_id, "error": str(exc)}})
        return
    if result is None:
        return

    await dispatcher.publish(
        RISK_FIELD_UPDATED,
        {"jurisdiction_id": result["jurisdiction_id"], "changed_cells": result["changed_cells"]},
    )


def _run_explanation_sync(prediction_id: str) -> Optional[dict]:
    """[Phase 2F] Explains the exact top-ranked exit_channel_id for this
    prediction, using its persisted feature_snapshot (app/graph/exit_scorer.py's
    Phase 2F addition) - never a freshly-recomputed approximation. Returns
    None (never fabricated) if no snapshot exists for this prediction
    (ExplanationUnavailable) - most commonly a prediction made before this
    persistence was added."""
    db = SessionLocal()
    try:
        prediction = db.query(Prediction).filter(Prediction.prediction_id == prediction_id).first()
        if prediction is None:
            return None

        try:
            result = explain_prediction(db, prediction)
        except ExplanationUnavailable as exc:
            logger.info(
                "explanation.unavailable",
                extra={"extra_fields": {"prediction_id": prediction_id, "reason": str(exc)}},
            )
            return None

        prediction.explanation = {
            "top_factors": result.top_factors,
            "graph_path": result.graph_path,
            "comparable_cases": result.comparable_cases,
            "plain_language": result.plain_language,
            "exit_channel_id": result.exit_channel_id,
        }
        db.flush()

        append_audit_event(
            db,
            event_type="prediction.explained",
            subject_type="prediction",
            subject_id=prediction.prediction_id,
            payload={
                "complaint_id": prediction.complaint_id,
                "exit_channel_id": result.exit_channel_id,
                "top_factor": result.top_factors[0]["feature"] if result.top_factors else None,
            },
        )
        db.commit()

        complaint = db.query(Complaint).filter(Complaint.complaint_id == prediction.complaint_id).first()
        return {
            "complaint_id": prediction.complaint_id,
            "prediction_id": prediction.prediction_id,
            "jurisdiction_id": complaint.jurisdiction_id if complaint else None,
        }
    finally:
        db.close()


async def _on_exit_prediction_completed_for_explanation(payload: dict) -> None:
    """[Phase 2F] EXIT_PREDICTION_COMPLETED already carries prediction_id
    directly (Phase 2D's event, unmodified) - this handler never needs to
    guess which Prediction row to explain. A failure here can never affect
    the exit-scoring pipeline that already completed successfully."""
    prediction_id = payload.get("prediction_id")
    if not prediction_id:
        return

    try:
        result = await run_in_threadpool(_run_explanation_sync, prediction_id)
    except Exception as exc:  # never let an explanation hiccup break the scoring pipeline
        logger.warning("explanation.failed", extra={"extra_fields": {"prediction_id": prediction_id, "error": str(exc)}})
        return
    if result is None:
        return

    await dispatcher.publish(
        EXPLANATION_GENERATED,
        {
            "complaint_id": result["complaint_id"],
            "prediction_id": result["prediction_id"],
            "jurisdiction_id": result["jurisdiction_id"],
        },
    )


def register_ring_detection_handlers() -> None:
    """Idempotent, matching app/ws/handlers.py's pattern - the app (and
    therefore its startup event) restarts multiple times within one process
    in the test suite, against the same process-wide dispatcher singleton."""
    dispatcher._subscribers[GRAPH_UPDATED] = [
        h for h in dispatcher._subscribers.get(GRAPH_UPDATED, []) if h.__module__ != __name__
    ]
    dispatcher.subscribe(GRAPH_UPDATED, _on_graph_updated)


def register_corridor_prediction_handlers() -> None:
    """[Phase 2C] Same idempotent-resubscribe pattern as
    register_ring_detection_handlers() above, for the same reason. Filters
    RING_DETECTED's own subscriber list only - independent of GRAPH_UPDATED's,
    even though both handlers live in this same module."""
    dispatcher._subscribers[RING_DETECTED] = [
        h for h in dispatcher._subscribers.get(RING_DETECTED, []) if h.__module__ != __name__
    ]
    dispatcher.subscribe(RING_DETECTED, _on_ring_detected)


def register_exit_scoring_handlers() -> None:
    """[Phase 2D] Same idempotent-resubscribe pattern as the two functions
    above, for the same reason. Filters CORRIDOR_PREDICTION_COMPLETED's own
    subscriber list only."""
    dispatcher._subscribers[CORRIDOR_PREDICTION_COMPLETED] = [
        h for h in dispatcher._subscribers.get(CORRIDOR_PREDICTION_COMPLETED, []) if h.__module__ != __name__
    ]
    dispatcher.subscribe(CORRIDOR_PREDICTION_COMPLETED, _on_corridor_prediction_completed)


def register_risk_field_handlers() -> None:
    """[Phase 2E] Same idempotent-resubscribe pattern as the three functions
    above, for the same reason. Filters TRANSACTION_INGESTED's own subscriber
    list only - independent of GRAPH_UPDATED's, even though the same publish
    call in app/modules/transactions/router.py fires both topics."""
    dispatcher._subscribers[TRANSACTION_INGESTED] = [
        h for h in dispatcher._subscribers.get(TRANSACTION_INGESTED, []) if h.__module__ != __name__
    ]
    dispatcher.subscribe(TRANSACTION_INGESTED, _on_transaction_ingested_for_risk_field)


def register_explainer_handlers() -> None:
    """[Phase 2F] Same idempotent-resubscribe pattern as the four functions
    above, for the same reason. Filters EXIT_PREDICTION_COMPLETED's own
    subscriber list only."""
    dispatcher._subscribers[EXIT_PREDICTION_COMPLETED] = [
        h for h in dispatcher._subscribers.get(EXIT_PREDICTION_COMPLETED, []) if h.__module__ != __name__
    ]
    dispatcher.subscribe(EXIT_PREDICTION_COMPLETED, _on_exit_prediction_completed_for_explanation)
