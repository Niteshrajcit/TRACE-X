"""
Unit tests for the Case & Approval lifecycle/assignment rules -
app/modules/complaints/service.py::assign_case/close_case. Pure
service-layer, no HTTP/RBAC layer involved (that's covered by
tests/test_case_approval_integration.py).
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import ComplaintStatus, FraudType, InstitutionType, UserRole
from app.db.models.jurisdictions import Jurisdiction
from app.db.models.users import User
from app.modules.complaints.service import (
    InvalidAssignment,
    InvalidCaseTransition,
    assign_case,
    close_case,
)


def _make_jurisdiction(db, name="Case Test Jurisdiction"):
    j = Jurisdiction(name=name, state="Tamil Nadu", district="Chennai")
    db.add(j)
    db.flush()
    return j


def _make_user(db, role, jurisdiction_id):
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="not-a-real-hash",
        role=role,
        jurisdiction_id=jurisdiction_id,
    )
    db.add(user)
    db.flush()
    return user


def _make_complaint(db, jurisdiction_id, status=ComplaintStatus.new):
    victim = Account(account_hash=f"case-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"CASE-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=100000,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Case & Approval unit test complaint",
        victim_account_id=victim.account_id,
        jurisdiction_id=jurisdiction_id,
        status=status,
    )
    db.add(complaint)
    db.commit()
    return complaint


# --- assign_case --------------------------------------------------------------


def test_assign_case_to_a_valid_investigator_in_the_same_jurisdiction(db):
    jurisdiction = _make_jurisdiction(db)
    investigator = _make_user(db, UserRole.investigator, jurisdiction.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)

    result = assign_case(db, complaint, investigator.user_id)
    assert result.assigned_investigator_id == investigator.user_id


def test_assign_case_to_a_supervisor_is_also_valid(db):
    jurisdiction = _make_jurisdiction(db)
    supervisor = _make_user(db, UserRole.supervisor, jurisdiction.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)

    result = assign_case(db, complaint, supervisor.user_id)
    assert result.assigned_investigator_id == supervisor.user_id


def test_assign_case_rejects_nonexistent_user(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)

    with pytest.raises(InvalidAssignment):
        assign_case(db, complaint, str(uuid.uuid4()))


def test_assign_case_rejects_wrong_role(db):
    jurisdiction = _make_jurisdiction(db)
    bank_liaison = _make_user(db, UserRole.bank_liaison, jurisdiction.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)

    with pytest.raises(InvalidAssignment):
        assign_case(db, complaint, bank_liaison.user_id)


def test_assign_case_rejects_cross_jurisdiction_investigator(db):
    jurisdiction_a = _make_jurisdiction(db, "Case Jurisdiction A")
    jurisdiction_b = _make_jurisdiction(db, "Case Jurisdiction B")
    investigator = _make_user(db, UserRole.investigator, jurisdiction_b.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction_a.jurisdiction_id)

    with pytest.raises(InvalidAssignment):
        assign_case(db, complaint, investigator.user_id)


def test_assign_case_rejects_assignment_to_a_closed_case(db):
    jurisdiction = _make_jurisdiction(db)
    investigator = _make_user(db, UserRole.investigator, jurisdiction.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id, status=ComplaintStatus.closed)

    with pytest.raises(InvalidCaseTransition):
        assign_case(db, complaint, investigator.user_id)


def test_assign_case_reassignment_to_a_different_investigator_succeeds(db):
    """Assignment is mutable case-management state, not a one-time
    decision - reassigning is allowed, unlike an intervention decision."""
    jurisdiction = _make_jurisdiction(db)
    first = _make_user(db, UserRole.investigator, jurisdiction.jurisdiction_id)
    second = _make_user(db, UserRole.investigator, jurisdiction.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)

    assign_case(db, complaint, first.user_id)
    result = assign_case(db, complaint, second.user_id)
    assert result.assigned_investigator_id == second.user_id


def test_assign_case_same_investigator_twice_is_a_harmless_no_op(db):
    jurisdiction = _make_jurisdiction(db)
    investigator = _make_user(db, UserRole.investigator, jurisdiction.jurisdiction_id)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)

    first = assign_case(db, complaint, investigator.user_id)
    second = assign_case(db, complaint, investigator.user_id)
    assert first.assigned_investigator_id == second.assigned_investigator_id == investigator.user_id


# --- close_case -----------------------------------------------------------------


def test_close_case_transitions_status_to_closed(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)

    result = close_case(db, complaint, "Determined not to be actionable fraud.")
    assert result.status == ComplaintStatus.closed


def test_close_case_rejects_an_already_closed_case(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id, status=ComplaintStatus.closed)

    with pytest.raises(InvalidCaseTransition):
        close_case(db, complaint, "Trying to close again.")
