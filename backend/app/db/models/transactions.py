from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.models.enums import TransactionChannel
from app.db.session import Base


class Transaction(Base):
    """docs/DATA_MODEL.md §2 `transactions`. Written by the synthetic seed
    generator (batch-mode reference data, `complaint_id IS NULL`) and, as of
    Phase 2A, by `POST /v1/transactions/ingest` (`complaint_id` required on
    that path - see API_CONTRACT.md §1a)."""

    __tablename__ = "transactions"

    txn_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    from_account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id"), nullable=False)
    to_account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    channel: Mapped[TransactionChannel] = mapped_column(Enum(TransactionChannel), nullable=False)
    hop_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    complaint_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("complaints.complaint_id"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # [Phase 2A additions, API_CONTRACT.md §1a]
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
    exit_channel_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("exit_channels.channel_id"), nullable=True
    )
