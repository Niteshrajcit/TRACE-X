"""
docs/API_CONTRACT.md §1-2, scoped to exactly the endpoints built so far:
POST/GET /v1/complaints, GET /v1/complaints/{id}, the WebSocket connection
(app/ws/router.py), and - as of Phase 2B - GET /v1/complaints/{id}/rings,
implementing the locked contract's `GET /v1/cases/{id}/graph`'s `rings`
array under the /v1/complaints path that already substitutes for the
not-yet-built /v1/cases (established in Phase 1/2A). Everything else in
API_CONTRACT.md (the rest of /v1/cases, predictions, optimizer, alerts,
audit) remains later-phase work.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.audit.service import append_audit_event
from app.auth.dependencies import get_current_claims, require_roles
from app.auth.schemas import TokenClaims
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus, UserRole
from app.db.models.predictions import Prediction, RecommendedDeployment
from app.db.session import get_db
from app.events.dispatcher import dispatcher
from app.events.topics import APPROVAL_REQUIRED, COMPLAINT_CREATED, INTERVENTION_RECOMMENDED
from app.graph.corridor import get_prediction_for_complaint
from app.graph.explainer import ExplanationUnavailable, explain_prediction
from app.graph.optimizer import OptimizerInputError, optimize_deployment
from app.graph.ring_service import get_rings_for_complaint
from app.graph.schemas import (
    ExitVector,
    ExplanationResponse,
    ModelVersions,
    OptimizeDeploymentRequest,
    OptimizeDeploymentResponse,
    PredictionResponse,
    RingListResponse,
)
from app.modules.complaints import service
from app.modules.complaints.schemas import (
    AssignCaseRequest,
    CloseCaseRequest,
    ComplaintCreateRequest,
    ComplaintCreateResponse,
    ComplaintDetail,
    ComplaintSummary,
)

router = APIRouter(prefix="/v1/complaints", tags=["complaints"])

INVESTIGATIVE_ROLES = (
    UserRole.investigator,
    UserRole.supervisor,
    UserRole.auditor,
    UserRole.admin,
)

# [Case & Approval] docs/SECURITY_AND_GOVERNANCE.md §3 characterizes
# Auditor as "read-only content" - case-management writes (assign, close)
# are scoped narrower than INVESTIGATIVE_ROLES above, excluding auditor.
CASE_MANAGEMENT_ROLES = (
    UserRole.investigator,
    UserRole.supervisor,
    UserRole.admin,
)


@router.post("", response_model=ComplaintCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_complaint(
    request: ComplaintCreateRequest, response: Response, db: Session = Depends(get_db)
) -> ComplaintCreateResponse:
    """Public, unauthenticated - stands in for NCRP (docs/PRODUCT.md §5).
    Flow: validate -> persist -> emit complaint.created -> return the
    acknowledgement, exactly as specified for this phase."""
    complaint, was_created = await run_in_threadpool(
        service.create_complaint, db, request, is_demo_data=False
    )
    if not was_created:
        response.status_code = status.HTTP_200_OK  # idempotent replay, not a new resource

    if was_created:
        await dispatcher.publish(
            COMPLAINT_CREATED,
            {
                "complaint_id": complaint.complaint_id,
                "incident_reference": complaint.incident_reference,
                "fraud_type": complaint.fraud_type.value,
                "amount": str(complaint.amount),
                "status": complaint.status.value,
                "filed_at": complaint.filed_at.isoformat(),
                "jurisdiction_id": complaint.jurisdiction_id,
            },
        )

    return ComplaintCreateResponse(
        complaint_id=complaint.complaint_id,
        incident_reference=complaint.incident_reference,
        status=complaint.status,
        filed_at=complaint.filed_at,
    )


@router.get("", response_model=List[ComplaintSummary])
def list_complaints(
    status_filter: Optional[ComplaintStatus] = Query(default=None, alias="status"),
    assigned_to_me: bool = Query(default=False),
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*INVESTIGATIVE_ROLES)),
) -> List[ComplaintSummary]:
    """docs/API_CONTRACT.md §2's `GET /v1/cases?jurisdiction_id&status&assigned_to_me`,
    implemented as this existing endpoint's own additive filters (the
    established /v1/complaints-substitutes-for-/v1/cases precedent) rather
    than a second, parallel route. Investigator/supervisor see only their
    own jurisdiction; auditor/admin see all (docs/SECURITY_AND_GOVERNANCE.md
    §3's RBAC matrix) - `jurisdiction_id` is never a client-supplied filter,
    only derived from the verified JWT claim, unchanged from before."""
    scope_jurisdiction: Optional[str] = None
    if claims.role in (UserRole.investigator, UserRole.supervisor):
        scope_jurisdiction = claims.jurisdiction_id
    assigned_investigator_id = claims.sub if assigned_to_me else None
    complaints = service.list_complaints(
        db, jurisdiction_id=scope_jurisdiction, status=status_filter, assigned_investigator_id=assigned_investigator_id
    )
    return [ComplaintSummary.model_validate(c) for c in complaints]


def _get_complaint_or_404(db: Session, complaint_id: str) -> Complaint:
    complaint = service.get_complaint(db, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
    return complaint


def _enforce_jurisdiction_scope(complaint: Complaint, claims: TokenClaims) -> None:
    if claims.role in (UserRole.investigator, UserRole.supervisor):
        if complaint.jurisdiction_id != claims.jurisdiction_id:
            # Cross-jurisdiction access denied - never leak existence via a
            # 404-vs-403 timing/response difference beyond this explicit 403.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This complaint is outside your jurisdiction",
            )


def _build_graph_summary(db: Session, complaint_id: str) -> dict:
    """docs/API_CONTRACT.md §2's `graph_summary` - reuses
    app/graph/ring_service.py::get_rings_for_complaint (already-computed,
    Postgres-only detected-ring intelligence) rather than a fresh graph
    fetch. A small, honest summary, not a duplicate of the full
    `GET .../rings` payload."""
    rings = get_rings_for_complaint(db, complaint_id)
    return {"ring_count": len(rings), "total_members": sum(r.member_count for r in rings)}


def _build_deployment_history(db: Session, complaint_id: str) -> List[dict]:
    """docs/API_CONTRACT.md §2's `deployment_history` - every Phase 2G
    recommendation ever produced for this complaint's prediction(s),
    already durably persisted, never recomputed."""
    prediction_ids = [p.prediction_id for p in db.query(Prediction.prediction_id).filter(Prediction.complaint_id == complaint_id).all()]
    if not prediction_ids:
        return []
    deployments = (
        db.query(RecommendedDeployment)
        .filter(RecommendedDeployment.prediction_id.in_(prediction_ids))
        .order_by(RecommendedDeployment.deployment_id)
        .all()
    )
    return [
        {
            "deployment_id": d.deployment_id,
            "optimizer_mode": d.optimizer_mode.value if d.optimizer_mode else None,
            "status": d.status.value,
            "expected_coverage_total": float(d.expected_coverage_total) if d.expected_coverage_total is not None else None,
            "naive_baseline_coverage": float(d.naive_baseline_coverage) if d.naive_baseline_coverage is not None else None,
            "decided_by": d.decided_by,
            "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        }
        for d in deployments
    ]


def _build_latest_prediction_dict(db: Session, complaint_id: str) -> Optional[dict]:
    prediction = get_prediction_for_complaint(db, complaint_id, prediction_id=None)
    if prediction is None or not prediction.exit_vector:
        return None  # no usable prediction yet - never a fabricated placeholder
    return PredictionResponse(
        prediction_id=prediction.prediction_id,
        generated_at=prediction.generated_at,
        exit_vector=ExitVector(**prediction.exit_vector),
        ranked_locations=prediction.ranked_locations,
        model_versions=ModelVersions(
            ring=prediction.model_version_ring,
            corridor=prediction.model_version_corridor,
            exit_channel=prediction.model_version_location,
            time_window=prediction.model_version_time,
        ),
    ).model_dump(mode="json")


@router.get("/{complaint_id}", response_model=ComplaintDetail)
def get_complaint(
    complaint_id: str,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*INVESTIGATIVE_ROLES)),
) -> ComplaintDetail:
    """docs/API_CONTRACT.md §2's `GET /v1/cases/{complaint_id}` aggregate
    view, merged additively into this existing endpoint (see
    _build_graph_summary/_build_deployment_history/_build_latest_prediction_dict
    docstrings) - the same resource, viewed as a case."""
    complaint = _get_complaint_or_404(db, complaint_id)
    _enforce_jurisdiction_scope(complaint, claims)

    detail = ComplaintDetail.model_validate(complaint)
    detail.latest_prediction = _build_latest_prediction_dict(db, complaint_id)
    detail.graph_summary = _build_graph_summary(db, complaint_id)
    detail.deployment_history = _build_deployment_history(db, complaint_id)
    return detail


@router.post("/{complaint_id}/assign", response_model=ComplaintSummary)
def assign_complaint(
    complaint_id: str,
    request: AssignCaseRequest,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*CASE_MANAGEMENT_ROLES)),
) -> ComplaintSummary:
    """docs/API_CONTRACT.md §2's `POST /v1/cases/{complaint_id}/assign`.
    docs/SECURITY_AND_GOVERNANCE.md §3 characterizes Auditor as
    'read-only content' - excluded here, unlike the broader
    INVESTIGATIVE_ROLES set every read endpoint in this router uses."""
    complaint = _get_complaint_or_404(db, complaint_id)
    _enforce_jurisdiction_scope(complaint, claims)

    try:
        complaint = service.assign_case(db, complaint, request.investigator_id)
    except service.InvalidCaseTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.InvalidAssignment as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ComplaintSummary.model_validate(complaint)


@router.post("/{complaint_id}/close", response_model=ComplaintSummary)
def close_complaint(
    complaint_id: str,
    request: CloseCaseRequest,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*CASE_MANAGEMENT_ROLES)),
) -> ComplaintSummary:
    """docs/API_CONTRACT.md §2's `POST /v1/cases/{complaint_id}/close`."""
    complaint = _get_complaint_or_404(db, complaint_id)
    _enforce_jurisdiction_scope(complaint, claims)

    try:
        complaint = service.close_case(db, complaint, request.reason)
    except service.InvalidCaseTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ComplaintSummary.model_validate(complaint)


@router.get("/{complaint_id}/rings", response_model=RingListResponse)
def get_complaint_rings(
    complaint_id: str,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*INVESTIGATIVE_ROLES)),
) -> RingListResponse:
    """docs/API_CONTRACT.md's locked `rings` array (Phase 2B). Never
    includes accounts.ring_id (the synthetic ground truth) - only detected
    intelligence from app/db/models/rings.py."""
    complaint = _get_complaint_or_404(db, complaint_id)
    _enforce_jurisdiction_scope(complaint, claims)
    return RingListResponse(rings=get_rings_for_complaint(db, complaint_id))


@router.get("/{complaint_id}/prediction", response_model=PredictionResponse)
def get_complaint_prediction(
    complaint_id: str,
    prediction_id: Optional[str] = None,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*INVESTIGATIVE_ROLES)),
) -> PredictionResponse:
    """docs/API_CONTRACT.md §3's `GET /v1/cases/{complaint_id}/prediction`,
    implemented under /v1/complaints per this module's established
    /v1/cases-substitute precedent (see get_complaint_rings above).

    `ranked_locations`/`model_versions.exit_channel`/`.time_window` are
    read directly off the stored Prediction row - null until Phase 2D's
    exit-channel scorer (app/graph/exit_scorer.py) has run for this ring,
    populated afterward without any change needed here. Never fabricated
    either way. See docs/API_CONTRACT.md's amended §3 note for the frozen
    contract shape."""
    complaint = _get_complaint_or_404(db, complaint_id)
    _enforce_jurisdiction_scope(complaint, claims)

    prediction = get_prediction_for_complaint(db, complaint_id, prediction_id)
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No prediction found for this complaint")

    return PredictionResponse(
        prediction_id=prediction.prediction_id,
        generated_at=prediction.generated_at,
        exit_vector=ExitVector(**prediction.exit_vector),
        ranked_locations=prediction.ranked_locations,
        model_versions=ModelVersions(
            ring=prediction.model_version_ring,
            corridor=prediction.model_version_corridor,
            exit_channel=prediction.model_version_location,
            time_window=prediction.model_version_time,
        ),
    )


@router.get("/{complaint_id}/explanation", response_model=ExplanationResponse)
def get_complaint_explanation(
    complaint_id: str,
    prediction_id: Optional[str] = None,
    exit_channel_id: Optional[str] = None,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*INVESTIGATIVE_ROLES)),
) -> ExplanationResponse:
    """docs/API_CONTRACT.md §3's `GET /v1/cases/{complaint_id}/explanation`,
    implemented under /v1/complaints per this module's established
    /v1/cases-substitute precedent (see get_complaint_rings above). Backs
    AI_ML_ARCHITECTURE.md §6 (Phase 2F).

    [Phase 2F, readiness-report-documented interpretation] `predictions.explanation`
    persists only the auto-generated explanation for the TOP-ranked
    exit_channel_id (written by the exit_prediction.completed -> Explainer
    -> explanation.generated event flow). A request naming a different
    `exit_channel_id` (PRODUCT_EXPERIENCE.md §5: "click a ranked cell ->
    opens explanation for *that* cell specifically") is computed live from
    that channel's own persisted feature_snapshot and returned - never
    written back over the persisted top-ranked explanation.

    Never fabricates: a Prediction with no persisted feature_snapshot
    (generated before Phase 2F's feature-vector persistence) returns
    `available: false` with a `reason`, not a recomputed approximation."""
    complaint = _get_complaint_or_404(db, complaint_id)
    _enforce_jurisdiction_scope(complaint, claims)

    prediction = get_prediction_for_complaint(db, complaint_id, prediction_id)
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No prediction found for this complaint")

    if exit_channel_id is None and prediction.explanation:
        # Already computed and persisted (the auto-generated, top-ranked
        # explanation) - serve it directly rather than recomputing.
        cached = prediction.explanation
        return ExplanationResponse(
            available=True,
            prediction_id=prediction.prediction_id,
            exit_channel_id=cached.get("exit_channel_id"),
            top_factors=cached.get("top_factors", []),
            graph_path=cached.get("graph_path"),
            comparable_cases=cached.get("comparable_cases", []),
            plain_language=cached.get("plain_language"),
        )

    try:
        result = explain_prediction(db, prediction, exit_channel_id=exit_channel_id)
    except ExplanationUnavailable as exc:
        return ExplanationResponse(available=False, reason=str(exc), prediction_id=prediction.prediction_id)

    return ExplanationResponse(
        available=True,
        prediction_id=result.prediction_id,
        exit_channel_id=result.exit_channel_id,
        top_factors=result.top_factors,
        graph_path=result.graph_path,
        comparable_cases=result.comparable_cases,
        plain_language=result.plain_language,
    )


@router.post("/{complaint_id}/optimize-deployment", response_model=OptimizeDeploymentResponse)
async def optimize_deployment_for_complaint(
    complaint_id: str,
    request: OptimizeDeploymentRequest,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*INVESTIGATIVE_ROLES)),
) -> OptimizeDeploymentResponse:
    """docs/API_CONTRACT.md §4's `POST /v1/cases/{complaint_id}/optimize-deployment`,
    implemented under /v1/complaints per this module's established
    /v1/cases-substitute precedent. Backs AI_ML_ARCHITECTURE.md §7 (Phase 2G).

    Mode is auto-selected server-side from the top-ranked exit channel's
    intervention_action_type - never caller-supplied. Re-callable with a
    different constraint; each call persists a new deployment_id, never
    overwrites a prior one (API_CONTRACT.md §4's own explicit note)."""
    complaint = _get_complaint_or_404(db, complaint_id)
    _enforce_jurisdiction_scope(complaint, claims)

    prediction = get_prediction_for_complaint(db, complaint_id, prediction_id=None)
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No prediction found for this complaint")

    try:
        result = await run_in_threadpool(
            optimize_deployment,
            db,
            prediction,
            request.team_count,
            [loc.model_dump() for loc in request.team_locations] if request.team_locations else None,
            request.request_slot_count,
        )
    except OptimizerInputError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    deployment = RecommendedDeployment(
        prediction_id=prediction.prediction_id,
        optimizer_mode=result["optimizer_mode"],
        team_count=request.team_count,
        request_slot_count=request.request_slot_count,
        assignment=result["assignment"],
        expected_coverage_total=result["expected_coverage_total"],
        naive_baseline_coverage=result["naive_baseline_coverage"],
    )
    db.add(deployment)
    db.flush()

    append_audit_event(
        db,
        event_type="deployment.recommended",
        subject_type="recommended_deployment",
        subject_id=deployment.deployment_id,
        payload={
            "complaint_id": complaint_id,
            "prediction_id": prediction.prediction_id,
            "optimizer_mode": result["optimizer_mode"].value,
            "expected_coverage_total": result["expected_coverage_total"],
        },
    )
    db.commit()

    await dispatcher.publish(
        INTERVENTION_RECOMMENDED,
        {
            "complaint_id": complaint_id,
            "deployment_id": deployment.deployment_id,
            "expected_coverage_total": result["expected_coverage_total"],
            "jurisdiction_id": complaint.jurisdiction_id,
        },
    )
    # [Case & Approval, additive] docs/PRODUCT_EXPERIENCE.md §4: this event
    # "fires the instant a deployment is proposed" - exactly this moment.
    # No new row (a derived state, per that same table), purely a WS signal
    # that a decision is now pending - zero change to this endpoint's own
    # response, persisted data, or the INTERVENTION_RECOMMENDED publish above.
    await dispatcher.publish(
        APPROVAL_REQUIRED,
        {
            "complaint_id": complaint_id,
            "deployment_id": deployment.deployment_id,
            "jurisdiction_id": complaint.jurisdiction_id,
        },
    )

    return OptimizeDeploymentResponse(
        deployment_id=deployment.deployment_id,
        optimizer_mode=result["optimizer_mode"].value,
        assignment=result["assignment"],
        expected_coverage_total=float(result["expected_coverage_total"]),
        naive_baseline_coverage=float(result["naive_baseline_coverage"]),
    )
