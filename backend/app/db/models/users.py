from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.models.enums import UserRole
from app.db.session import Base


class User(Base):
    """docs/DATA_MODEL.md §2 `users`. RBAC scoping (SECURITY_AND_GOVERNANCE.md
    §3) reads role/jurisdiction_id/bank_id straight off this row at login
    time and bakes them into the JWT - authorization checks never re-query
    this table on every request."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    jurisdiction_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("jurisdictions.jurisdiction_id"), nullable=True
    )
    bank_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("banks.bank_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
