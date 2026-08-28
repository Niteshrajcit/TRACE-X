"""
Response shape for exposing detected ring intelligence
(docs/API_CONTRACT.md's locked `GET /v1/cases/{complaint_id}/graph`'s
`rings` array - implemented as `GET /v1/complaints/{complaint_id}/rings`,
following the same /v1/complaints-substitutes-for-/v1/cases precedent
Phase 1/2A already established, since /v1/cases doesn't exist yet).

Never includes accounts.ring_id (the synthetic ground truth) - only fields
derived from DetectedRing/DetectedRingMember (app/db/models/rings.py).
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class RingSummary(BaseModel):
    ring_id: str
    detected_at: datetime
    algorithm_name: str
    algorithm_version: str

    member_count: int
    member_account_ids: List[str]

    transaction_count: int
    total_amount: Decimal
    average_transaction_amount: Optional[Decimal] = None
    transaction_velocity: Optional[Decimal] = None
    burst_ratio: Optional[Decimal] = None

    fan_in_count: int
    fan_out_count: int
    fan_in_amount: Decimal
    fan_out_amount: Decimal

    device_count: int
    ip_count: int
    phone_count: int
    vpa_count: int

    geographic_spread_km: Optional[Decimal] = None
    cohesion_score: Decimal
    exit_channel_ids: List[str]

    model_config = {"from_attributes": True}


class RingListResponse(BaseModel):
    rings: List[RingSummary]


# [Phase 2C] GET /v1/complaints/{complaint_id}/prediction - API_CONTRACT.md
# §3's `exit_vector` response shape, frozen to Phase 2C scope only:
# `ranked_locations`/`model_versions.exit_channel`/`.time_window` are
# explicitly None (Phase 2D, §4, not yet built), never a fabricated value.


class ExitVector(BaseModel):
    bearing_deg: float
    distance_range_km: List[float]
    confidence_cone_deg: float
    exit_channel_type: str


class ModelVersions(BaseModel):
    ring: Optional[str] = None
    corridor: Optional[str] = None
    exit_channel: Optional[str] = None  # Phase 2D - always None until that stage exists
    time_window: Optional[str] = None  # Phase 2D - always None until that stage exists


class PredictionResponse(BaseModel):
    prediction_id: str
    generated_at: datetime
    exit_vector: ExitVector
    ranked_locations: Optional[List[dict]] = None  # Phase 2D - always None, never fabricated
    model_versions: ModelVersions
    disclaimer: str = (
        "This is an investigative lead based on automated pattern analysis, "
        "not a definitive determination of wrongdoing."
    )

    model_config = {"from_attributes": True}


class PredictionListResponse(BaseModel):
    predictions: List[PredictionResponse]


# [Phase 2F] GET /v1/complaints/{complaint_id}/explanation - API_CONTRACT.md
# §3, backing AI_ML_ARCHITECTURE.md §6. `top_factors` shape is the Phase 2F
# decision freeze: {feature, weight, direction} - no `evidence_ref` (no
# evidence-reference contract has been defined anywhere in this project).


class TopFactor(BaseModel):
    feature: str
    weight: float
    direction: str


class GraphPath(BaseModel):
    real_path: List[str]  # Neo4j-verified TRANSFERRED_TO chain only - never a fabricated edge
    predicted_exit_channel_id: Optional[str] = None  # kept separate - a prediction, not an observed edge
    path_complete: bool


class ComparableCase(BaseModel):
    complaint_id: str
    similarity_score: float
    summary: str


# [Phase 2G] POST /v1/complaints/{complaint_id}/optimize-deployment -
# API_CONTRACT.md §4, backing AI_ML_ARCHITECTURE.md §7. Mode is
# auto-selected server-side; the caller supplies whichever constraint
# applies to the mode this complaint's top-ranked candidate actually needs.


class LatLon(BaseModel):
    lat: float
    lon: float


class OptimizeDeploymentRequest(BaseModel):
    team_count: Optional[int] = None
    team_locations: Optional[List[LatLon]] = None
    request_slot_count: Optional[int] = None


class OptimizeDeploymentResponse(BaseModel):
    deployment_id: str
    optimizer_mode: str
    assignment: List[dict]
    expected_coverage_total: float
    naive_baseline_coverage: float


class ExplanationResponse(BaseModel):
    available: bool = True
    reason: Optional[str] = None  # populated only when available=False - never fabricated otherwise
    prediction_id: Optional[str] = None
    exit_channel_id: Optional[str] = None
    top_factors: List[TopFactor] = []
    graph_path: Optional[GraphPath] = None
    comparable_cases: List[ComparableCase] = []
    plain_language: Optional[str] = None
