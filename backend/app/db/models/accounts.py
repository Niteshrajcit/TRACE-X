from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.models.enums import KycRiskTier, LinkedEntityType
from app.db.session import Base


class Account(Base):
    """docs/DATA_MODEL.md §2 `accounts`. `account_hash` is the only
    representation of the underlying account number ever persisted - see
    app/core/security.py `hash_pii`. `branch_geo GEOGRAPHY(POINT)` is stored
    as plain lat/lon floats in this phase (see app/db/session.py's module
    docstring for why). `ring_id`/`is_synthetic` are additive fields the
    synthetic generator and later ring-detection stage need
    (docs/AI_ML_ARCHITECTURE.md §2's "ground truth retained" design) -
    not present in the original DATA_MODEL.md table, added deliberately."""

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    account_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    bank_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("banks.bank_id"), nullable=True)
    branch_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    branch_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kyc_risk_tier: Mapped[KycRiskTier] = mapped_column(
        Enum(KycRiskTier), default=KycRiskTier.low, nullable=False
    )
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ring_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)


class LinkedEntity(Base):
    """docs/DATA_MODEL.md §2 `linked_entities`, enum extended with
    ip/vpa/email (the original spec listed device/phone/address_cluster;
    the synthetic-data brief for this phase explicitly asks for IPs and
    VPAs as well, and email is the natural third contact-hash type
    alongside phone)."""

    __tablename__ = "linked_entities"

    entity_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id"), nullable=False)
    entity_type: Mapped[LinkedEntityType] = mapped_column(Enum(LinkedEntityType), nullable=False)
    entity_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
