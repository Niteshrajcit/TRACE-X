"""
docs/API_CONTRACT.md §5: `GET /v1/audit/events`, `GET /v1/audit/verify-chain`,
`GET /v1/models` (Audit & Governance / model-registry visibility surfaces).
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    event_id: str
    seq_no: int
    event_type: str
    actor_id: Optional[str] = None
    subject_type: str
    subject_id: Optional[str] = None
    occurred_at: datetime
    this_hash: str

    model_config = {"from_attributes": True}


class VerifyChainResponse(BaseModel):
    valid: bool
    broken_at_seq: Optional[int] = None


class ModelRegistryEntryResponse(BaseModel):
    model_id: str
    stage: str
    version: str
    trained_at: datetime
    metrics: dict
    is_active: bool

    model_config = {"from_attributes": True}
