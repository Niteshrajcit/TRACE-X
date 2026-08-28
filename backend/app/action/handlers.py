"""
Wires INTERVENTION_APPROVED -> Action & Alerting into the existing
in-process event dispatcher - mirrors app/graph/handlers.py's exact
pattern (sync work in a threadpool, publish the next documented event on
success, log-and-return on failure, never break the caller's own flow).

    intervention.approved -> Action & Alerting dispatch -> action.dispatched

A rejected or still-proposed deployment never reaches this handler at all -
app/modules/deployments/router.py only ever publishes INTERVENTION_APPROVED
when decision == "approved" - but app/action/dispatcher.py re-checks
status == approved anyway (SECURITY_AND_GOVERNANCE.md §5's literal
invariant, never trusted from the event alone).
"""
from typing import Optional

from starlette.concurrency import run_in_threadpool

from app.action.dispatcher import dispatch_action_for_deployment
from app.core.logging_config import get_logger
from app.db.models.predictions import Alert
from app.db.session import SessionLocal
from app.events.dispatcher import dispatcher
from app.events.topics import ACTION_DISPATCHED, INTERVENTION_APPROVED

logger = get_logger(__name__)


def _run_dispatch_sync(deployment_id: str) -> Optional[dict]:
    db = SessionLocal()
    try:
        alert = dispatch_action_for_deployment(db, deployment_id)
        if alert is None:
            return None
        return {"alert_id": alert.alert_id, "channel": alert.channel.value, "delivered": alert.delivered_at is not None}
    finally:
        db.close()


async def _on_intervention_approved(payload: dict) -> None:
    deployment_id = payload.get("deployment_id")
    if not deployment_id:
        return

    try:
        result = await run_in_threadpool(_run_dispatch_sync, deployment_id)
    except Exception as exc:  # never let a dispatch hiccup break the approval flow that already succeeded
        logger.warning("action.dispatch_handler_failed", extra={"extra_fields": {"deployment_id": deployment_id, "error": str(exc)}})
        return
    if result is None:
        return

    await dispatcher.publish(
        ACTION_DISPATCHED,
        {
            "complaint_id": payload.get("complaint_id"),
            "deployment_id": deployment_id,
            "alert_id": result["alert_id"],
            "channel": result["channel"],
            "delivered": result["delivered"],
            "jurisdiction_id": payload.get("jurisdiction_id"),
        },
    )


def register_action_handlers() -> None:
    """Idempotent, same pattern as app/graph/handlers.py's own
    register_*_handlers functions. Must be called AFTER
    app/ws/handlers.py::register_ws_event_handlers() in app/main.py's
    startup sequence - that function unconditionally clears
    INTERVENTION_APPROVED's whole subscriber list before adding its own,
    which would otherwise wipe this module's subscription too."""
    dispatcher._subscribers[INTERVENTION_APPROVED] = [
        h for h in dispatcher._subscribers.get(INTERVENTION_APPROVED, []) if h.__module__ != __name__
    ]
    dispatcher.subscribe(INTERVENTION_APPROVED, _on_intervention_approved)
