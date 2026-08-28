from typing import Optional

from sqlalchemy import JSON, Boolean, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.models.enums import ExitChannelType, InterventionActionType
from app.db.session import Base


class ExitChannel(Base):
    """docs/DATA_MODEL.md §2 `exit_channels` (generalized from the original
    `cash_out_points`, docs/PRODUCT_EXPERIENCE.md §7). Not read by any
    scoring/prediction logic in Phase 1 - seeded now by the synthetic
    generator so the geospatial base data (ATM/branch/exchange/merchant
    locations) exists ahead of Phase 2+."""

    __tablename__ = "exit_channels"

    channel_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    channel_type: Mapped[ExitChannelType] = mapped_column(Enum(ExitChannelType), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    geo_lat: Mapped[float] = mapped_column(Float, nullable=False)
    geo_lon: Mapped[float] = mapped_column(Float, nullable=False)
    h3_cell: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    channel_attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    intervention_action_type: Mapped[InterventionActionType] = mapped_column(
        Enum(InterventionActionType), nullable=False
    )
    historical_incident_count: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
