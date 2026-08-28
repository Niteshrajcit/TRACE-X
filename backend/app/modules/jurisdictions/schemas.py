"""
docs/API_CONTRACT.md §3's locked shape for
`GET /v1/jurisdictions/{jurisdiction_id}/risk-field?at=<timestamp>` (Phase 2E,
backing docs/AI_ML_ARCHITECTURE.md §5): `{ h3_cells: [ { h3_cell, score } ],
generated_for: <timestamp> }`.
"""
from datetime import datetime
from typing import List

from pydantic import BaseModel


class RiskFieldCell(BaseModel):
    h3_cell: str
    score: float


class RiskFieldResponse(BaseModel):
    h3_cells: List[RiskFieldCell]
    generated_for: datetime
