"""
docs/DATA_MODEL.md §2 (Phase 2B addition), docs/AI_ML_ARCHITECTURE.md §2/§2a/§2b.

`ring_id` is a deterministic hash of (sorted member account_ids, algorithm
name, algorithm version) - NOT a fresh UUID per run. This makes "reproduce
the result from the same graph input" true at the identifier level, not
just the membership level: an unchanged graph re-detected produces the
identical ring_id. When the same membership is detected again with updated
underlying transaction data (new transactions between the same accounts),
`persist_ring` (app/graph/ring_service.py) UPSERTs that row in place rather
than accumulating a new record per run - one current row per distinct
membership set. A full history of every detection run is available via the
`audit_events` log entry this module also writes (event_type =
'ring.detected'), not via row versioning here.

`accounts.ring_id` (app/db/models/accounts.py) is the *synthetic ground
truth* planted by the generator - a completely different, deliberately
separate concept from the tables below, which hold *detected* intelligence.
Never join or conflate the two outside app/graph/evaluation.py, which exists
specifically to compare them and is never exposed via the API
(docs/PRODUCT.md §5: "Do not expose hidden synthetic ground truth to
investigators").
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.session import Base


class DetectedRing(Base):
    __tablename__ = "detected_rings"

    ring_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    algorithm_name: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_graph_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    average_transaction_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 2), nullable=True)
    transaction_velocity: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    fan_in_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fan_out_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fan_in_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    fan_out_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)

    device_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_count: Mapped[int] = mapped_column(Integer, nullable=False)
    phone_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vpa_count: Mapped[int] = mapped_column(Integer, nullable=False)

    geographic_spread_km: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    burst_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    cohesion_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)

    exit_channel_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Full transparent-feature record (docs/AI_ML_ARCHITECTURE.md §2b) -
    # duplicates some columns above for queryability, but is the complete,
    # authoritative feature snapshot including each feature's documented
    # formula name, so a stored ring is self-describing without needing the
    # docs open to know how a number was derived.
    suspiciousness_features: Mapped[dict] = mapped_column(JSON, default=dict)

    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DetectedRingMember(Base):
    __tablename__ = "detected_ring_members"
    __table_args__ = (UniqueConstraint("ring_id", "account_id", name="uq_ring_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    ring_id: Mapped[str] = mapped_column(String(64), ForeignKey("detected_rings.ring_id"), nullable=False)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id"), nullable=False)


class DetectedRingComplaint(Base):
    """Incident/case association 'where applicable' - a ring is linked to a
    complaint when at least one ring member is that complaint's victim
    account, or appears in one of that complaint's transactions. A ring can
    have zero associated complaints (e.g. a mule cluster discovered purely
    from shared-device batch data with no live complaint yet)."""

    __tablename__ = "detected_ring_complaints"
    __table_args__ = (UniqueConstraint("ring_id", "complaint_id", name="uq_ring_complaint"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    ring_id: Mapped[str] = mapped_column(String(64), ForeignKey("detected_rings.ring_id"), nullable=False)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.complaint_id"), nullable=False)
