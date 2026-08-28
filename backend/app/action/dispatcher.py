"""
Action & Alerting - docs/ARCHITECTURE.md's "Action & Alerting" module,
docs/SECURITY_AND_GOVERNANCE.md §5's hard invariant: "the Action module's
send function requires a decision_id referencing an approved row and
verifies its status server-side before constructing any outbound payload."

Trigger is the documented event chain, not a new REST endpoint -
API_CONTRACT.md §4: "if approved triggers Action module (which emits
action.dispatched)" and ARCHITECTURE.md §4's event table:
`intervention.approved` -> consumers include "Action module (approved
only)". See app/action/handlers.py for the INTERVENTION_APPROVED subscriber
that calls dispatch_action_for_deployment below.

State model (deliberately using only existing columns - no new migration):
- RecommendedDeployment.status: proposed -> approved/rejected (Phase 3)
- Alert.sent_at set / Alert.delivered_at set-or-null: dispatched -> delivered
  or failed (this module) - `alerts` has no dedicated status enum in
  DATA_MODEL.md's frozen schema, so "failed" is honestly represented as
  "sent_at is set, delivered_at is not" rather than inventing a new column.
- InterventionOutcome existing for a deployment: completed (Phase 3's
  /outcome endpoint, app/modules/deployments/router.py)
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.action import mock_router
from app.action.signing import sign_payload
from app.audit.service import append_audit_event
from app.core.logging_config import get_logger
from app.db.models.common import new_uuid
from app.db.models.complaints import Complaint
from app.db.models.enums import AlertChannel, DeploymentStatus, InterventionActionType
from app.db.models.exit_channels import ExitChannel
from app.db.models.predictions import Alert, Prediction, RecommendedDeployment

logger = get_logger(__name__)

_CHANNEL_BY_ACTION_TYPE = {
    InterventionActionType.physical_team_deployment: AlertChannel.bank_webhook_sim,
    InterventionActionType.exchange_freeze_request: AlertChannel.exchange_webhook_sim,
    InterventionActionType.merchant_hold_request: AlertChannel.merchant_webhook_sim,
}

_RECOMMENDED_ACTION_BY_ACTION_TYPE = {
    InterventionActionType.physical_team_deployment: "deploy_team_to_exit_channel",
    InterventionActionType.exchange_freeze_request: "request_exchange_freeze",
    InterventionActionType.merchant_hold_request: "request_merchant_hold",
}

_RECEIVER_BY_CHANNEL = {
    AlertChannel.bank_webhook_sim: mock_router.receive_bank_webhook,
    AlertChannel.i4c_webhook_sim: mock_router.receive_i4c_webhook,
    AlertChannel.exchange_webhook_sim: mock_router.receive_exchange_webhook,
    AlertChannel.merchant_webhook_sim: mock_router.receive_merchant_webhook,
}


def _find_existing_alert(db: Session, prediction_id: str, deployment_id: str) -> Optional[Alert]:
    """Idempotency: `alerts` has no `deployment_id` column (DATA_MODEL.md's
    frozen schema only links Alert -> Prediction, and one Prediction can
    have several RecommendedDeployments over time) - the deployment_id is
    carried inside Alert.payload (already a free-form JSONB column, exactly
    what it's for) instead of adding a migration."""
    for alert in db.query(Alert).filter(Alert.prediction_id == prediction_id).all():
        if (alert.payload or {}).get("deployment_id") == deployment_id:
            return alert
    return None


def dispatch_action_for_deployment(db: Session, deployment_id: str) -> Optional[Alert]:
    """Returns the Alert row (existing or newly created) - or None, never a
    fabricated one, if dispatch genuinely cannot happen (not approved, or
    the underlying prediction/complaint/top exit channel no longer
    exists). Re-verifies `status == approved` itself rather than trusting
    the caller already checked - the literal SECURITY_AND_GOVERNANCE.md §5
    invariant."""
    deployment = db.query(RecommendedDeployment).filter(RecommendedDeployment.deployment_id == deployment_id).first()
    if deployment is None or deployment.status != DeploymentStatus.approved:
        return None

    existing = _find_existing_alert(db, deployment.prediction_id, deployment_id)
    if existing is not None:
        return existing  # already dispatched - idempotent, never re-sent

    prediction = db.query(Prediction).filter(Prediction.prediction_id == deployment.prediction_id).first()
    if prediction is None or not prediction.ranked_locations:
        return None
    complaint = db.query(Complaint).filter(Complaint.complaint_id == prediction.complaint_id).first()
    if complaint is None:
        return None

    top_exit_channel_id = (
        deployment.assignment[0]["exit_channel_id"] if deployment.assignment else prediction.ranked_locations[0]["exit_channel_id"]
    )
    top_channel = db.query(ExitChannel).filter(ExitChannel.channel_id == top_exit_channel_id).first()
    if top_channel is None:
        return None
    top_ranked = next((r for r in prediction.ranked_locations if r["exit_channel_id"] == top_exit_channel_id), prediction.ranked_locations[0])

    channel = _CHANNEL_BY_ACTION_TYPE[top_channel.intervention_action_type]
    recommended_action = _RECOMMENDED_ACTION_BY_ACTION_TYPE[top_channel.intervention_action_type]

    lo, hi = top_ranked["time_window_min"]
    alert_id = new_uuid()
    # docs/API_CONTRACT.md §4's exact documented alert payload shape.
    unsigned_payload = {
        "alert_id": alert_id,
        "complaint_id": complaint.complaint_id,
        "deployment_id": deployment_id,
        "issued_by_jurisdiction": complaint.jurisdiction_id,
        "risk_summary": (
            f"{round(top_ranked['probability'] * 100)}% probability of cash withdrawal "
            f"at H3 cell {top_ranked['h3_cell']} within {lo:.0f}-{hi:.0f} min"
        ),
        "recommended_action": recommended_action,
        "evidence_ref": f"/v1/complaints/{complaint.complaint_id}/explanation",
        "requires_human_approval": True,
    }
    signature = sign_payload(unsigned_payload)
    signed_payload = {**unsigned_payload, "signature": signature}

    sent_at = datetime.now(timezone.utc)
    delivered_at = None
    try:
        receiver = _RECEIVER_BY_CHANNEL[channel]
        ack = asyncio.run(receiver(payload=signed_payload, x_signature=signature))
        if ack.get("received"):
            delivered_at = datetime.now(timezone.utc)
    except Exception as exc:  # never fabricate delivery - a receiver failure just leaves delivered_at unset
        logger.warning(
            "action.receiver_failed",
            extra={"extra_fields": {"deployment_id": deployment_id, "channel": channel.value, "error": str(exc)}},
        )

    alert = Alert(
        alert_id=alert_id,
        prediction_id=prediction.prediction_id,
        channel=channel,
        recipient_ref=top_channel.external_ref,
        payload=signed_payload,
        sent_at=sent_at,
        delivered_at=delivered_at,
    )
    db.add(alert)
    db.flush()

    append_audit_event(
        db,
        event_type="action.dispatched",
        subject_type="alert",
        subject_id=alert.alert_id,
        payload={
            "complaint_id": complaint.complaint_id,
            "deployment_id": deployment_id,
            "channel": channel.value,
            "delivered": delivered_at is not None,
        },
    )
    db.commit()
    db.refresh(alert)
    return alert
