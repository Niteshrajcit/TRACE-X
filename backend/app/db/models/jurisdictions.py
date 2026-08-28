from typing import Optional

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.session import Base


class Jurisdiction(Base):
    """docs/DATA_MODEL.md §2 `jurisdictions`. The `boundary GEOMETRY(POLYGON)`
    column from the spec is deferred - Phase 1 does zero polygon-containment
    queries (that logic was already redesigned away in
    docs/PRODUCT_EXPERIENCE.md §8.5 in favour of the precomputed
    `h3_cell_jurisdiction` lookup below), so there is nothing in this phase
    that would read it. Added back as a real PostGIS geometry column
    alongside the true Geography columns noted in app/db/session.py, at the
    point a screen actually needs to render it."""

    __tablename__ = "jurisdictions"

    jurisdiction_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(255), nullable=False)
    district: Mapped[str] = mapped_column(String(255), nullable=False)


class Bank(Base):
    """docs/DATA_MODEL.md §2 `banks`."""

    __tablename__ = "banks"

    bank_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ifsc_prefix: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)


class H3CellJurisdiction(Base):
    """docs/DATA_MODEL.md §2. Populated once at seed time by a
    polygon-containment pass (once real polygons exist); until then the
    synthetic generator assigns each seeded H3 cell to its jurisdiction
    directly, which is exactly the same end state a polygon pass would
    produce for the seeded points."""

    __tablename__ = "h3_cell_jurisdiction"

    h3_cell: Mapped[str] = mapped_column(String(20), primary_key=True)
    jurisdiction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jurisdictions.jurisdiction_id"), nullable=False
    )
