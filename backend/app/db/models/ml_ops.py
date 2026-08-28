"""docs/DATA_MODEL.md §2 `model_registry`, `feature_snapshots`. Unused this
phase - no model is trained yet. Present for schema completeness only."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.models.enums import ModelStage
from app.db.session import Base


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry"

    model_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    stage: Mapped[ModelStage] = mapped_column(Enum(ModelStage), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class FeatureSnapshot(Base):
    __tablename__ = "feature_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.complaint_id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_vector: Mapped[dict] = mapped_column(JSON, default=dict)
    label: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
