"""
Pydantic request/response schemas for the complaint intake vertical slice
(docs/API_CONTRACT.md §1, extended with the concrete field set this phase's
brief specifies: incident date/time, location, fraud category, amount,
bank/wallet/merchant info, transaction reference, description, evidence
metadata, contact information).

Deliberate design point: `ComplaintCreateRequest` (the PUBLIC schema bound to
POST /v1/complaints) has no `is_demo_data` field. There is no way for an
HTTP caller - citizen or synthetic-seeding script alike - to set that flag
themselves; only the internal service function
(app/modules/complaints/service.py `create_complaint`) can, via a
keyword-only argument no request schema exposes. This is what makes "the
canonical demo scenario must be data generated/seeded through the same
interfaces used by the application" true without opening a public API field
that would let anyone mislabel real data as demo data or vice versa.
"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, List, Optional

from pydantic import BaseModel, EmailStr, Field

from app.db.models.enums import ComplaintStatus, FraudType, InstitutionType


class ComplaintCreateRequest(BaseModel):
    incident_datetime: datetime
    fraud_type: FraudType
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("100000000"))]

    location_text: Annotated[str, Field(min_length=3, max_length=500)]
    location_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    location_lon: Optional[float] = Field(default=None, ge=-180, le=180)

    institution_name: Annotated[str, Field(min_length=1, max_length=255)]
    institution_type: InstitutionType
    transaction_reference: Optional[str] = Field(default=None, max_length=255)

    # Contact/account fields - hashed at the ingestion boundary
    # (app/modules/complaints/service.py) and never stored in the clear or
    # returned in any response (docs/SECURITY_AND_GOVERNANCE.md §2).
    victim_account_number: Optional[str] = Field(default=None, max_length=64)
    victim_phone: Optional[str] = Field(default=None, max_length=20)
    victim_email: Optional[EmailStr] = None

    description: Annotated[str, Field(min_length=10, max_length=5000)]
    evidence_notes: List[str] = Field(default_factory=list, max_length=20)

    jurisdiction_hint: Optional[str] = Field(default=None, max_length=255)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class ComplaintCreateResponse(BaseModel):
    complaint_id: str
    incident_reference: str
    status: ComplaintStatus
    filed_at: datetime


class ComplaintSummary(BaseModel):
    complaint_id: str
    incident_reference: str
    fraud_type: FraudType
    amount: Decimal
    status: ComplaintStatus
    filed_at: datetime
    jurisdiction_id: Optional[str] = None
    assigned_investigator_id: Optional[str] = None

    model_config = {"from_attributes": True}


class ComplaintDetail(ComplaintSummary):
    incident_datetime: datetime
    location_text: str
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    institution_name: str
    institution_type: InstitutionType
    transaction_reference: Optional[str] = None
    description: str
    evidence_notes: List[str]
    is_demo_data: bool

    # [Case & Approval] API_CONTRACT.md §2's `GET /v1/cases/{complaint_id}`
    # aggregate view - additive, optional fields on the existing complaint
    # detail response (the same resource, viewed as a case), never a
    # separate/duplicate endpoint. Each is reused from an existing,
    # already-computed source - never recomputed.
    latest_prediction: Optional[dict] = None
    graph_summary: Optional[dict] = None
    deployment_history: List[dict] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AssignCaseRequest(BaseModel):
    investigator_id: str


class CloseCaseRequest(BaseModel):
    reason: Annotated[str, Field(min_length=3, max_length=1000)]
