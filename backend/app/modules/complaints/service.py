"""
Complaint intake business logic. This is the one place complaint creation
happens - the public API router calls it, and so does the synthetic/demo
seeding script (app/synthetic/seed_demo_complaint.py), satisfying
docs/DEMO_ARCHITECTURE.md's "the canonical demo scenario must be data
generated/seeded through the same interfaces used by the application"
at the service-function level (the same validation, ID generation, hashing,
and event emission path), even though only the seeding script can pass
`is_demo_data=True`.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import append_audit_event
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus, LinkedEntityType, UserRole
from app.db.models.jurisdictions import Jurisdiction
from app.db.models.users import User
from app.modules.complaints.schemas import ComplaintCreateRequest
from app.shared.accounts import attach_linked_entity, find_or_create_account


class DuplicateIdempotencyKey(Exception):
    """Raised internally to signal 'return the existing row', not an error
    the caller should surface as a failure."""

    def __init__(self, existing: Complaint):
        self.existing = existing


def generate_incident_reference() -> str:
    """`TX-<year>-<8 hex chars>` - unique by construction (derived from a
    fresh UUID4), so no sequence/counter table and no race condition to
    guard against under concurrent submissions. A friendlier sequential
    number (TX-2026-000123) is a fast-follow once a single counter's
    contention profile under real concurrent load is worth designing for -
    not needed at this phase's scale."""
    return f"TX-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:8].upper()}"


DEFAULT_JURISDICTION_NAME = "Unassigned Queue"


def _resolve_jurisdiction(db: Session, jurisdiction_hint: Optional[str]) -> Optional[str]:
    """Matches the citizen's free-text jurisdiction hint against a seeded
    jurisdiction; falls back to a seeded "Unassigned Queue" jurisdiction
    (rather than NULL) so every complaint has a jurisdiction channel to be
    pushed to over WebSocket - a complaint nobody's console can ever receive
    would silently defeat the real-time proof this phase exists to
    demonstrate. A supervisor/auditor triaging that queue and reassigning
    the jurisdiction is a natural Phase 3 case-management feature, not
    built here."""
    match = None
    if jurisdiction_hint:
        hint = jurisdiction_hint.strip().lower()
        match = (
            db.query(Jurisdiction)
            .filter(
                func.lower(Jurisdiction.name).contains(hint)
                | func.lower(Jurisdiction.district).contains(hint)
                | func.lower(Jurisdiction.state).contains(hint)
            )
            .first()
        )
    if match:
        return match.jurisdiction_id

    # Get-or-create: the fallback queue must exist even on a database that
    # was never run through the synthetic seed script - a fresh Postgres or
    # a fresh test database must not silently leave complaints unroutable.
    fallback = db.query(Jurisdiction).filter(Jurisdiction.name == DEFAULT_JURISDICTION_NAME).first()
    if fallback is None:
        fallback = Jurisdiction(
            name=DEFAULT_JURISDICTION_NAME, state="Unassigned", district="Unassigned"
        )
        db.add(fallback)
        db.flush()
    return fallback.jurisdiction_id


def create_complaint(
    db: Session,
    request: ComplaintCreateRequest,
    *,
    is_demo_data: bool = False,
) -> tuple[Complaint, bool]:
    """Returns (complaint, was_created). was_created=False means an existing
    row with the same idempotency_key was returned instead of creating a
    duplicate (Phase 1 exit criterion: idempotency handling)."""
    if request.idempotency_key:
        existing = (
            db.query(Complaint)
            .filter(Complaint.idempotency_key == request.idempotency_key)
            .first()
        )
        if existing:
            return existing, False

    victim_account_id = find_or_create_account(db, request.victim_account_number, is_synthetic=False)
    attach_linked_entity(db, victim_account_id, LinkedEntityType.phone, request.victim_phone)
    attach_linked_entity(
        db, victim_account_id, LinkedEntityType.email,
        str(request.victim_email) if request.victim_email else None,
    )

    jurisdiction_id = _resolve_jurisdiction(db, request.jurisdiction_hint)

    complaint = Complaint(
        incident_reference=generate_incident_reference(),
        incident_datetime=request.incident_datetime,
        fraud_type=request.fraud_type,
        amount=request.amount,
        location_text=request.location_text,
        location_lat=request.location_lat,
        location_lon=request.location_lon,
        institution_name=request.institution_name,
        institution_type=request.institution_type,
        transaction_reference=request.transaction_reference,
        description=request.description,
        evidence_notes=request.evidence_notes,
        victim_account_id=victim_account_id,
        jurisdiction_id=jurisdiction_id,
        jurisdiction_hint=request.jurisdiction_hint,
        status=ComplaintStatus.new,
        is_demo_data=is_demo_data,
        idempotency_key=request.idempotency_key,
    )
    db.add(complaint)
    db.flush()  # assign complaint_id before it's referenced by the audit event

    append_audit_event(
        db,
        event_type="complaint.created",
        subject_type="complaint",
        subject_id=complaint.complaint_id,
        payload={
            "incident_reference": complaint.incident_reference,
            "fraud_type": complaint.fraud_type.value,
            "is_demo_data": is_demo_data,
        },
    )

    db.commit()
    db.refresh(complaint)
    return complaint, True


def get_complaint(db: Session, complaint_id: str) -> Optional[Complaint]:
    return db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()


def list_complaints(
    db: Session,
    *,
    jurisdiction_id: Optional[str] = None,
    status: Optional[ComplaintStatus] = None,
    assigned_investigator_id: Optional[str] = None,
    limit: int = 100,
) -> list[Complaint]:
    query = db.query(Complaint).order_by(Complaint.filed_at.desc())
    if jurisdiction_id is not None:
        query = query.filter(Complaint.jurisdiction_id == jurisdiction_id)
    if status is not None:
        query = query.filter(Complaint.status == status)
    if assigned_investigator_id is not None:
        query = query.filter(Complaint.assigned_investigator_id == assigned_investigator_id)
    return query.limit(limit).all()


class InvalidAssignment(Exception):
    """Raised - never silently coerced - when the target user can't
    plausibly be assigned this case: wrong role, or a different
    jurisdiction than the complaint's own."""


class InvalidCaseTransition(Exception):
    """Raised when a case-lifecycle action is attempted against a
    complaint already in a terminal or otherwise incompatible state -
    never silently overwritten."""


def assign_case(db: Session, complaint: Complaint, investigator_id: str) -> Complaint:
    """docs/API_CONTRACT.md §2 `POST /v1/cases/{complaint_id}/assign`.
    Idempotent in the ordinary sense: assigning the same investigator again
    is a harmless no-op re-confirmation, not an error; re-assigning to a
    different investigator is also allowed (mutable case-management state,
    unlike an intervention decision, which is a one-time act - see
    RecommendedDeployment's own status machine)."""
    if complaint.status == ComplaintStatus.closed:
        raise InvalidCaseTransition("Cannot assign a closed case.")

    target = db.query(User).filter(User.user_id == investigator_id).first()
    if target is None:
        raise InvalidAssignment(f"User {investigator_id!r} does not exist.")
    if target.role not in (UserRole.investigator, UserRole.supervisor):
        raise InvalidAssignment(f"User {investigator_id!r} is not an investigator or supervisor.")
    if target.jurisdiction_id != complaint.jurisdiction_id:
        raise InvalidAssignment(f"User {investigator_id!r} is not in this case's jurisdiction.")

    complaint.assigned_investigator_id = investigator_id
    db.flush()

    append_audit_event(
        db,
        event_type="case.assigned",
        subject_type="complaint",
        subject_id=complaint.complaint_id,
        payload={"investigator_id": investigator_id},
    )
    db.commit()
    db.refresh(complaint)
    return complaint


def close_case(db: Session, complaint: Complaint, reason: str) -> Complaint:
    """docs/API_CONTRACT.md §2 `POST /v1/cases/{complaint_id}/close`. No
    dedicated `close_reason` column exists in docs/DATA_MODEL.md's
    `complaints` table - the reason is persisted durably via the
    hash-chained audit event payload instead of a new migration, exactly
    the same choice already made for the Phase 2G optimizer's contextual
    detail (never a new column for something the audit trail already
    durably records)."""
    if complaint.status == ComplaintStatus.closed:
        raise InvalidCaseTransition("This case is already closed.")

    complaint.status = ComplaintStatus.closed
    db.flush()

    append_audit_event(
        db,
        event_type="case.closed",
        subject_type="complaint",
        subject_id=complaint.complaint_id,
        payload={"reason": reason},
    )
    db.commit()
    db.refresh(complaint)
    return complaint
