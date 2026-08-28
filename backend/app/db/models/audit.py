from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.session import Base


class AuditEvent(Base):
    """docs/DATA_MODEL.md §2 `audit_events`, docs/SECURITY_AND_GOVERNANCE.md
    §4: append-only, hash-chained. `seq_no` is the strict ordering the chain
    hashes over - it must be assigned inside the same transaction that
    computes `this_hash` (see app/modules/audit/service.py), never left to
    an autoincrement race. No UPDATE/DELETE code path exists anywhere in this
    codebase for this table; enforcing that at the database grant level too
    (REVOKE UPDATE, DELETE) is a documented Postgres-deployment step, not
    something SQLite migrations can express - noted as a known gap for the
    Docker/Postgres environment this eventually runs in."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    seq_no: Mapped[int] = mapped_column(nullable=False, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Widened 36 -> 64 (Phase 2B foundation fix): every other subject_id in
    # this system is a 36-char UUID, but a ring's subject_id is its
    # deterministic SHA-256 ring_id (app/graph/ring_service.py::compute_ring_id,
    # 64 hex chars) - VARCHAR(36) silently truncated it on PostgreSQL,
    # raising StringDataRightTruncation mid-`run_ring_detection`, which
    # aborted before `db.commit()` while the ring's Neo4j write (a separate,
    # already-committed connection) survived - the exact mechanism behind
    # the historical orphaned-Ring-node incidents. SQLite does not enforce
    # VARCHAR length at all, which is why the existing SQLite-backed test
    # suite never caught this.
    subject_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    this_hash: Mapped[str] = mapped_column(String(64), nullable=False)
