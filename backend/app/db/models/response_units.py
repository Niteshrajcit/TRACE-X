from sqlalchemy import Boolean, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.models.enums import ResponseUnitStatus
from app.db.session import Base


class ResponseUnit(Base):
    """New table, not present in the original docs/DATA_MODEL.md - added
    because docs/AI_ML_ARCHITECTURE.md §7a's Intervention Optimizer needs
    team locations to optimize over, and this phase's synthetic-data brief
    explicitly asks for "response units" to be seeded. Unused by any Phase 1
    logic; exists so Phase 4's optimizer has real seeded data to run against
    instead of inventing its own fixture format later."""

    __tablename__ = "response_units"

    unit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    jurisdiction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jurisdictions.jurisdiction_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[ResponseUnitStatus] = mapped_column(
        Enum(ResponseUnitStatus), default=ResponseUnitStatus.available, nullable=False
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
