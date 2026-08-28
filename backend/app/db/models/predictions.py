"""
docs/DATA_MODEL.md §2 `predictions`, `recommended_deployments`, `alerts`,
`intervention_outcomes`. None of these are written or read by any Phase 1
endpoint - the AI/ML, optimizer, and action layers are explicitly out of
scope for this phase. The tables exist now purely so the schema matches the
locked architecture in full and Phase 2-4 don't start with a migration.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.common import new_uuid
from app.db.models.enums import AlertChannel, DeploymentStatus, OptimizerMode, OutcomeResult
from app.db.session import Base


class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.complaint_id"), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version_ring: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_version_corridor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_version_location: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_version_time: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # [Phase 2C] AI_ML_ARCHITECTURE.md §3's Corridor/Exit-Vector Predictor output:
    # {bearing_deg, distance_range_km, confidence_cone_deg, exit_channel_type}. One JSONB field,
    # not four scalar columns - these are always read/written together, never queried individually
    # (docs/DATA_MODEL.md §2's predictions table, Phase 2C addition).
    exit_vector: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ranked_locations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=None)
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class RecommendedDeployment(Base):
    __tablename__ = "recommended_deployments"

    deployment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("predictions.prediction_id"), nullable=False
    )
    optimizer_mode: Mapped[Optional[OptimizerMode]] = mapped_column(Enum(OptimizerMode), nullable=True)
    team_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    request_slot_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assignment: Mapped[list] = mapped_column(JSON, default=list)
    expected_coverage_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    naive_baseline_coverage: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    status: Mapped[DeploymentStatus] = mapped_column(
        Enum(DeploymentStatus), default=DeploymentStatus.proposed, nullable=False
    )
    decided_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    alert_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("predictions.prediction_id"), nullable=False
    )
    channel: Mapped[AlertChannel] = mapped_column(Enum(AlertChannel), nullable=False)
    recipient_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class InterventionOutcome(Base):
    __tablename__ = "intervention_outcomes"

    outcome_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    deployment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recommended_deployments.deployment_id"), nullable=False
    )
    recorded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[OutcomeResult] = mapped_column(Enum(OutcomeResult), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feeds_retraining: Mapped[bool] = mapped_column(default=True)
