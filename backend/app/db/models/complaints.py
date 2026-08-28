from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.models.enums import ComplaintSource, ComplaintStatus, FraudType, InstitutionType
from app.db.session import Base


class Complaint(Base):
    """docs/DATA_MODEL.md §2 `complaints`, extended with the concrete field
    set the intake form actually asks for (docs/PRODUCT_EXPERIENCE.md's
    Citizen Complaint Portal / this phase's instructions): incident
    date-time, location, institution, transaction reference, description,
    evidence metadata. No victim name/phone/email column exists here by
    design (docs/DATA_MODEL.md §6) - contact identifiers are hashed into
    `accounts`/`linked_entities` before this row is written, never stored
    in the clear anywhere.
    """

    __tablename__ = "complaints"

    complaint_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    incident_reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    filed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    incident_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    fraud_type: Mapped[FraudType] = mapped_column(Enum(FraudType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    location_text: Mapped[str] = mapped_column(String(500), nullable=False)
    location_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    institution_name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution_type: Mapped[InstitutionType] = mapped_column(Enum(InstitutionType), nullable=False)
    transaction_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_notes: Mapped[list] = mapped_column(JSON, default=list)

    victim_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.account_id"), nullable=True
    )
    jurisdiction_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("jurisdictions.jurisdiction_id"), nullable=True
    )
    jurisdiction_hint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[ComplaintStatus] = mapped_column(
        Enum(ComplaintStatus), default=ComplaintStatus.new, nullable=False
    )
    assigned_investigator_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.user_id"), nullable=True
    )
    source: Mapped[ComplaintSource] = mapped_column(
        Enum(ComplaintSource), default=ComplaintSource.own_intake_form, nullable=False
    )

    # Provenance (docs/DEMO_ARCHITECTURE.md §2, docs/PRODUCT.md §5): True only
    # for complaints created by the synthetic/demo seeding path, even though
    # they go through the exact same service function and HTTP endpoint a
    # real citizen submission would. Never settable by the public request
    # schema - see app/modules/complaints/schemas.py.
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Prevents a double-click / client retry from creating two complaints
    # for one citizen submission (Phase 1 exit criterion: idempotency).
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
