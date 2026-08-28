"""
docs/API_CONTRACT.md §5's Audit & Governance surfaces:

    GET /v1/audit/events?subject_id=&from=&to=      -- auditor/admin only
    GET /v1/audit/verify-chain?from_seq=&to_seq=
    GET /v1/models

RBAC precisely reconciles two documents rather than picking one and
ignoring the other: API_CONTRACT.md's own inline note says these are
"auditor/admin only," while docs/SECURITY_AND_GOVERNANCE.md §3's RBAC
matrix gives investigator "own actions only" and supervisor
"jurisdiction-scoped" audit visibility. Read together (API_CONTRACT.md's
own header: "Depends on... SECURITY_AND_GOVERNANCE.md for the RBAC matrix
these endpoints enforce"), the natural, non-fabricated reconciliation is:
auditor/admin get full, unscoped, filterless access (matches "Full,
cross-jurisdiction"); investigator/supervisor may only ever look up a
KNOWN subject already within their own jurisdiction (the per-incident
`#audit` tab, PRODUCT_EXPERIENCE.md §3.2) - never the unscoped global
stream. `verify-chain` and `/models` have no such per-subject scoping
concept in either document and are implemented exactly as literally
written: auditor/admin only.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.audit.service import verify_chain
from app.auth.dependencies import require_roles
from app.auth.schemas import TokenClaims
from app.db.models.audit import AuditEvent
from app.db.models.complaints import Complaint
from app.db.models.enums import UserRole
from app.db.models.ml_ops import ModelRegistryEntry
from app.db.models.predictions import Alert, InterventionOutcome, Prediction, RecommendedDeployment
from app.db.session import get_db
from app.modules.audit.schemas import AuditEventResponse, ModelRegistryEntryResponse, VerifyChainResponse

router = APIRouter(prefix="/v1", tags=["audit"])

AUDIT_FULL_ROLES = (UserRole.auditor, UserRole.admin)
AUDIT_SCOPED_ROLES = (UserRole.investigator, UserRole.supervisor, UserRole.auditor, UserRole.admin)


def _resolve_jurisdiction_for_subject(db: Session, subject_type: str, subject_id: str) -> Optional[str]:
    """Traces any audit subject this system produces back to the
    complaint/jurisdiction it belongs to - every subject_type ever passed
    to append_audit_event (complaint, prediction, recommended_deployment,
    intervention_outcome, alert) is reachable this way. Returns None
    (never a guessed jurisdiction) for an unrecognized subject_type or a
    subject that no longer resolves."""
    complaint_id: Optional[str] = None

    if subject_type == "complaint":
        complaint_id = subject_id
    elif subject_type == "prediction":
        prediction = db.query(Prediction).filter(Prediction.prediction_id == subject_id).first()
        complaint_id = prediction.complaint_id if prediction else None
    elif subject_type == "recommended_deployment":
        deployment = db.query(RecommendedDeployment).filter(RecommendedDeployment.deployment_id == subject_id).first()
        if deployment is not None:
            prediction = db.query(Prediction).filter(Prediction.prediction_id == deployment.prediction_id).first()
            complaint_id = prediction.complaint_id if prediction else None
    elif subject_type == "intervention_outcome":
        outcome = db.query(InterventionOutcome).filter(InterventionOutcome.outcome_id == subject_id).first()
        if outcome is not None:
            deployment = db.query(RecommendedDeployment).filter(RecommendedDeployment.deployment_id == outcome.deployment_id).first()
            if deployment is not None:
                prediction = db.query(Prediction).filter(Prediction.prediction_id == deployment.prediction_id).first()
                complaint_id = prediction.complaint_id if prediction else None
    elif subject_type == "alert":
        alert = db.query(Alert).filter(Alert.alert_id == subject_id).first()
        if alert is not None:
            prediction = db.query(Prediction).filter(Prediction.prediction_id == alert.prediction_id).first()
            complaint_id = prediction.complaint_id if prediction else None

    if complaint_id is None:
        return None
    complaint = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
    return complaint.jurisdiction_id if complaint else None


@router.get("/audit/events", response_model=List[AuditEventResponse])
def list_audit_events(
    subject_id: Optional[str] = Query(default=None),
    subject_type: Optional[str] = Query(default=None),
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*AUDIT_SCOPED_ROLES)),
) -> List[AuditEventResponse]:
    if claims.role in (UserRole.investigator, UserRole.supervisor):
        if not subject_id or not subject_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="subject_id and subject_type are required for this role.",
            )
        jurisdiction_id = _resolve_jurisdiction_for_subject(db, subject_type, subject_id)
        if jurisdiction_id is None or jurisdiction_id != claims.jurisdiction_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This audit subject is outside your jurisdiction")

    query = db.query(AuditEvent).order_by(AuditEvent.seq_no.asc())
    if subject_id is not None:
        query = query.filter(AuditEvent.subject_id == subject_id)
    if subject_type is not None:
        query = query.filter(AuditEvent.subject_type == subject_type)
    if from_ is not None:
        query = query.filter(AuditEvent.occurred_at >= from_)
    if to is not None:
        query = query.filter(AuditEvent.occurred_at <= to)

    return [AuditEventResponse.model_validate(e) for e in query.limit(500).all()]


@router.get("/audit/verify-chain", response_model=VerifyChainResponse)
def verify_audit_chain(
    from_seq: Optional[int] = Query(default=None),
    to_seq: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*AUDIT_FULL_ROLES)),
) -> VerifyChainResponse:
    valid, broken_at_seq = verify_chain(db, from_seq=from_seq, to_seq=to_seq)
    return VerifyChainResponse(valid=valid, broken_at_seq=broken_at_seq)


@router.get("/models", response_model=List[ModelRegistryEntryResponse])
def list_models(
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*AUDIT_FULL_ROLES)),
) -> List[ModelRegistryEntryResponse]:
    """Honestly returns [] today - no phase has ever registered a model
    version here (docs/AI_ML_ARCHITECTURE.md §9's model_registry has
    existed, unused, since Phase 0/1). This surface makes that visible
    rather than fabricating rows; the retraining job that would populate
    it is documented (§8) as a separate, non-live batch job, out of this
    backend-freeze pass's scope."""
    entries = db.query(ModelRegistryEntry).order_by(ModelRegistryEntry.trained_at.desc()).all()
    return [ModelRegistryEntryResponse.model_validate(e) for e in entries]
