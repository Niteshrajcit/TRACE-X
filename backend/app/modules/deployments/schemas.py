"""
docs/API_CONTRACT.md §4's `POST /v1/deployments/{deployment_id}/decision`
(Case & Approval's approval gate over Phase 2G's recommendations) and
`POST /v1/deployments/{deployment_id}/outcome` (Audit/Feedback - records
what actually happened, feeds the retraining label table).
"""
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field

from app.db.models.enums import OutcomeResult


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    justification: Annotated[str, Field(min_length=3, max_length=2000)]


class DecisionResponse(BaseModel):
    deployment_id: str
    status: str
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None


class OutcomeRequest(BaseModel):
    result: OutcomeResult
    notes: Optional[Annotated[str, Field(max_length=2000)]] = None


class OutcomeResponse(BaseModel):
    outcome_id: str
    deployment_id: str
    result: OutcomeResult
    recorded_by: str
    recorded_at: datetime
    feature_snapshot_id: Optional[str] = None
