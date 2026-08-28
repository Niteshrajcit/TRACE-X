"""Wires the in-process event dispatcher to the WebSocket fan-out. This is
the entire "Phase 1 real-time proof" mechanism: nothing here polls anything."""
from app.events.dispatcher import dispatcher
from app.events.topics import (
    ACTION_DISPATCHED,
    APPROVAL_REQUIRED,
    COMPLAINT_CREATED,
    EXPLANATION_GENERATED,
    FEEDBACK_CREATED,
    INTERVENTION_APPROVED,
    INTERVENTION_RECOMMENDED,
    INTERVENTION_REJECTED,
    OUTCOME_RECORDED,
    RISK_FIELD_UPDATED,
)
from app.ws.manager import manager


async def _on_complaint_created(payload: dict) -> None:
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": COMPLAINT_CREATED, **payload})


async def _on_risk_field_updated(payload: dict) -> None:
    """[Phase 2E] docs/PRODUCT_EXPERIENCE.md §4's documented WS payload shape
    for this event: {type, jurisdiction_id, changed_cells}. Jurisdiction-wide
    channel, same as COMPLAINT_CREATED above - every investigator watching
    this jurisdiction gets it, not just the one connected to this incident."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": RISK_FIELD_UPDATED, **payload})


async def _on_explanation_generated(payload: dict) -> None:
    """[Phase 2F] API_CONTRACT.md §7's documented wire shape is
    {type, complaint_id, prediction_id} - jurisdiction_id is carried in the
    internal dispatcher payload purely for channel routing (same
    established pattern as _on_complaint_created above, whose own
    documented wire sample also omits jurisdiction_id yet the real
    broadcast includes it via **payload)."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": EXPLANATION_GENERATED, **payload})


async def _on_intervention_recommended(payload: dict) -> None:
    """[Phase 2G] API_CONTRACT.md §7's documented wire shape is
    {type, complaint_id, deployment_id, expected_coverage_total} -
    jurisdiction_id is carried in the internal dispatcher payload purely
    for channel routing, same established pattern as the handlers above."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": INTERVENTION_RECOMMENDED, **payload})


async def _on_approval_required(payload: dict) -> None:
    """[Case & Approval] API_CONTRACT.md §7's documented wire shape is
    {type, complaint_id, deployment_id}."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": APPROVAL_REQUIRED, **payload})


async def _on_intervention_approved(payload: dict) -> None:
    """[Case & Approval] API_CONTRACT.md §7's documented wire shape is
    {type, complaint_id, deployment_id, decision}."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": INTERVENTION_APPROVED, **payload})


async def _on_intervention_rejected(payload: dict) -> None:
    """[Case & Approval] Same wire shape as _on_intervention_approved above,
    a different topic - rejections are first-class, not silent
    (docs/SECURITY_AND_GOVERNANCE.md §5)."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": INTERVENTION_REJECTED, **payload})


async def _on_action_dispatched(payload: dict) -> None:
    """[Action & Alerting] API_CONTRACT.md §7's documented wire shape is
    {type, complaint_id, alert_id, channel}."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": ACTION_DISPATCHED, **payload})


async def _on_outcome_recorded(payload: dict) -> None:
    """[Audit/Feedback] API_CONTRACT.md §7's documented wire shape is
    {type, complaint_id, deployment_id, result}."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": OUTCOME_RECORDED, **payload})


async def _on_feedback_created(payload: dict) -> None:
    """[Audit/Feedback] API_CONTRACT.md §7's documented wire shape is
    {type, complaint_id, feature_snapshot_id}."""
    jurisdiction_id = payload.get("jurisdiction_id")
    if not jurisdiction_id:
        return
    await manager.broadcast(jurisdiction_id, {"type": FEEDBACK_CREATED, **payload})


def register_ws_event_handlers() -> None:
    """Idempotent on purpose: the test suite starts the FastAPI app (and
    therefore its startup event) multiple times against the same
    process-wide `dispatcher` singleton. Without clearing first, each
    additional app startup would add another duplicate subscription and a
    connected client would receive the same push N times."""
    dispatcher._subscribers[COMPLAINT_CREATED] = []
    dispatcher.subscribe(COMPLAINT_CREATED, _on_complaint_created)
    dispatcher._subscribers[RISK_FIELD_UPDATED] = []
    dispatcher.subscribe(RISK_FIELD_UPDATED, _on_risk_field_updated)
    dispatcher._subscribers[EXPLANATION_GENERATED] = []
    dispatcher.subscribe(EXPLANATION_GENERATED, _on_explanation_generated)
    dispatcher._subscribers[INTERVENTION_RECOMMENDED] = []
    dispatcher.subscribe(INTERVENTION_RECOMMENDED, _on_intervention_recommended)
    dispatcher._subscribers[APPROVAL_REQUIRED] = []
    dispatcher.subscribe(APPROVAL_REQUIRED, _on_approval_required)
    dispatcher._subscribers[INTERVENTION_APPROVED] = []
    dispatcher.subscribe(INTERVENTION_APPROVED, _on_intervention_approved)
    dispatcher._subscribers[INTERVENTION_REJECTED] = []
    dispatcher.subscribe(INTERVENTION_REJECTED, _on_intervention_rejected)
    dispatcher._subscribers[ACTION_DISPATCHED] = []
    dispatcher.subscribe(ACTION_DISPATCHED, _on_action_dispatched)
    dispatcher._subscribers[OUTCOME_RECORDED] = []
    dispatcher.subscribe(OUTCOME_RECORDED, _on_outcome_recorded)
    dispatcher._subscribers[FEEDBACK_CREATED] = []
    dispatcher.subscribe(FEEDBACK_CREATED, _on_feedback_created)
