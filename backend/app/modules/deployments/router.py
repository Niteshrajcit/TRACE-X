"""
docs/API_CONTRACT.md §4: `POST /v1/deployments/{deployment_id}/decision`
(Case & Approval's explicit human-approval gate over Phase 2G's
recommendations - docs/SECURITY_AND_GOVERNANCE.md §5's hard invariant that
no action can be taken without an approved decision row starts here).

Deliberately excludes the `/outcome` endpoint (docs/API_CONTRACT.md §4) and
any Action-module dispatch - both are explicitly out of this phase's scope
(Audit/Feedback and Action & Alerting, respectively). This endpoint only
ever writes to `recommended_deployments` and publishes the documented
event; nothing here sends an alert or contacts any external system.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.audit.service import append_audit_event
from app.auth.dependencies import require_roles
from app.auth.schemas import TokenClaims
from app.db.models.complaints import Complaint
from app.db.models.enums import DeploymentStatus, UserRole
from app.db.models.ml_ops import FeatureSnapshot
from app.db.models.predictions import InterventionOutcome, Prediction, RecommendedDeployment
from app.db.session import get_db
from app.events.dispatcher import dispatcher
from app.events.topics import FEEDBACK_CREATED, INTERVENTION_APPROVED, INTERVENTION_REJECTED, OUTCOME_RECORDED
from app.modules.complaints.router import CASE_MANAGEMENT_ROLES
from app.modules.deployments.schemas import DecisionRequest, DecisionResponse, OutcomeRequest, OutcomeResponse

router = APIRouter(prefix="/v1/deployments", tags=["deployments"])

# docs/API_CONTRACT.md §4's own explicit line: "auth: investigator or
# supervisor only" - narrower than every other complaint-scoped endpoint in
# this codebase (which also allow auditor/admin to read, and Phase 2G's
# optimize-deployment to write) - honored exactly, not broadened.
DECISION_ROLES = (UserRole.investigator, UserRole.supervisor)


def _resolve_complaint_for_deployment(db: Session, deployment: RecommendedDeployment) -> Complaint:
    prediction = db.query(Prediction).filter(Prediction.prediction_id == deployment.prediction_id).first()
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Underlying prediction no longer exists")
    complaint = db.query(Complaint).filter(Complaint.complaint_id == prediction.complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Underlying complaint no longer exists")
    return complaint


def _enforce_jurisdiction_scope(complaint: Complaint, claims: TokenClaims) -> None:
    """Mirrors app/modules/complaints/router.py::_enforce_jurisdiction_scope -
    duplicated rather than imported (that function is module-private by
    convention, same as app/modules/jurisdictions/router.py's own copy of
    this exact check)."""
    if claims.role in (UserRole.investigator, UserRole.supervisor):
        if complaint.jurisdiction_id != claims.jurisdiction_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This deployment is outside your jurisdiction",
            )


@router.post("/{deployment_id}/decision", response_model=DecisionResponse)
async def decide_deployment(
    deployment_id: str,
    request: DecisionRequest,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*DECISION_ROLES)),
) -> DecisionResponse:
    """Sets exactly the fields docs/PRODUCT_EXPERIENCE.md §4's event table
    names for this event's DB effect - `recommended_deployments.status`,
    `decided_by`, `decided_at` - nothing else. A deployment already decided
    (status != 'proposed') is a 409, never silently re-decided or
    overwritten - SECURITY_AND_GOVERNANCE.md §5: 'a rejected deployment...
    is retained exactly like an approved one for audit purposes.'"""
    deployment = db.query(RecommendedDeployment).filter(RecommendedDeployment.deployment_id == deployment_id).first()
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")

    complaint = _resolve_complaint_for_deployment(db, deployment)
    _enforce_jurisdiction_scope(complaint, claims)

    if deployment.status != DeploymentStatus.proposed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This deployment was already {deployment.status.value} - a decision cannot be changed.",
        )

    new_status = DeploymentStatus.approved if request.decision == "approved" else DeploymentStatus.rejected
    deployment.status = new_status
    deployment.decided_by = claims.sub
    deployment.decided_at = datetime.now(timezone.utc)
    db.flush()

    append_audit_event(
        db,
        event_type=f"intervention.{request.decision}",
        subject_type="recommended_deployment",
        subject_id=deployment.deployment_id,
        payload={
            "complaint_id": complaint.complaint_id,
            "decision": request.decision,
            "justification": request.justification,
        },
    )
    db.commit()

    topic = INTERVENTION_APPROVED if request.decision == "approved" else INTERVENTION_REJECTED
    await dispatcher.publish(
        topic,
        {
            "complaint_id": complaint.complaint_id,
            "deployment_id": deployment.deployment_id,
            "decision": request.decision,
            "jurisdiction_id": complaint.jurisdiction_id,
        },
    )

    return DecisionResponse(
        deployment_id=deployment.deployment_id,
        status=deployment.status.value,
        decided_by=deployment.decided_by,
        decided_at=deployment.decided_at,
    )


def _extract_feature_vector_for_deployment(prediction: Prediction, deployment: RecommendedDeployment) -> Optional[dict]:
    """Reuses the exact per-candidate feature vector app/graph/exit_scorer.py
    already persisted at scoring time (Phase 2F/2G) - never recomputed,
    never fabricated. Returns None (an honest gap, not an invented vector)
    if this prediction predates that persistence or lacks the acted-upon
    channel's entry."""
    snapshot = prediction.feature_snapshot or {}
    by_channel = snapshot.get("by_exit_channel_id") or {}
    if not by_channel:
        return None
    exit_channel_id = deployment.assignment[0]["exit_channel_id"] if deployment.assignment else None
    if exit_channel_id is None and prediction.ranked_locations:
        exit_channel_id = prediction.ranked_locations[0]["exit_channel_id"]
    return by_channel.get(exit_channel_id)


@router.post("/{deployment_id}/outcome", response_model=OutcomeResponse)
async def record_outcome(
    deployment_id: str,
    request: OutcomeRequest,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*CASE_MANAGEMENT_ROLES)),
) -> OutcomeResponse:
    """docs/API_CONTRACT.md §4's `POST /v1/deployments/{deployment_id}/outcome`.
    docs/SECURITY_AND_GOVERNANCE.md §3 characterizes Auditor as read-only -
    reuses the same CASE_MANAGEMENT_ROLES set as assign/close (excludes
    auditor), not the narrower investigator/supervisor-only DECISION_ROLES
    (recording what happened is case-management, not the approval act
    itself). One outcome per deployment, ever - a second attempt is a 409,
    never silently overwritten (mirrors the decision gate's own discipline).

    Feeds retraining exactly as docs/AI_ML_ARCHITECTURE.md §8 describes:
    "every outcome is written as a labeled training row... into a
    versioned feature/label table" - reusing the already-persisted
    feature_snapshot from scoring time, never a freshly-recomputed one."""
    deployment = db.query(RecommendedDeployment).filter(RecommendedDeployment.deployment_id == deployment_id).first()
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")

    complaint = _resolve_complaint_for_deployment(db, deployment)
    _enforce_jurisdiction_scope(complaint, claims)

    if deployment.status != DeploymentStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An outcome can only be recorded for an approved deployment.",
        )

    existing_outcome = db.query(InterventionOutcome).filter(InterventionOutcome.deployment_id == deployment_id).first()
    if existing_outcome is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An outcome was already recorded for this deployment.")

    outcome = InterventionOutcome(
        deployment_id=deployment_id,
        recorded_by=claims.sub,
        recorded_at=datetime.now(timezone.utc),
        result=request.result,
        notes=request.notes,
    )
    db.add(outcome)
    db.flush()

    prediction = db.query(Prediction).filter(Prediction.prediction_id == deployment.prediction_id).first()
    feature_vector = _extract_feature_vector_for_deployment(prediction, deployment) if prediction else None
    feature_snapshot = None
    if feature_vector is not None:
        feature_snapshot = FeatureSnapshot(
            complaint_id=complaint.complaint_id,
            stage="intervention_outcome",
            feature_vector=feature_vector,
            label={"result": request.result.value, "outcome_id": outcome.outcome_id},
        )
        db.add(feature_snapshot)
        db.flush()

    append_audit_event(
        db,
        event_type="outcome.recorded",
        subject_type="intervention_outcome",
        subject_id=outcome.outcome_id,
        payload={
            "complaint_id": complaint.complaint_id,
            "deployment_id": deployment_id,
            "result": request.result.value,
            "feature_snapshot_written": feature_snapshot is not None,
        },
    )
    db.commit()
    db.refresh(outcome)

    await dispatcher.publish(
        OUTCOME_RECORDED,
        {
            "complaint_id": complaint.complaint_id,
            "deployment_id": deployment_id,
            "result": request.result.value,
            "jurisdiction_id": complaint.jurisdiction_id,
        },
    )
    if feature_snapshot is not None:
        await dispatcher.publish(
            FEEDBACK_CREATED,
            {
                "complaint_id": complaint.complaint_id,
                "feature_snapshot_id": feature_snapshot.snapshot_id,
                "jurisdiction_id": complaint.jurisdiction_id,
            },
        )

    return OutcomeResponse(
        outcome_id=outcome.outcome_id,
        deployment_id=deployment_id,
        result=outcome.result,
        recorded_by=outcome.recorded_by,
        recorded_at=outcome.recorded_at,
        feature_snapshot_id=feature_snapshot.snapshot_id if feature_snapshot else None,
    )
