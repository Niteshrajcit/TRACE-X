"""
docs/API_CONTRACT.md §3: `GET /v1/jurisdictions/{jurisdiction_id}/risk-field?at=<timestamp>`
(Phase 2E, docs/AI_ML_ARCHITECTURE.md §5). Two modes, both backed by the one
`compute_risk_field` fusion implementation in app/graph/risk_field.py:

- No `at`: serves the live in-process cache (docs/DATA_MODEL.md's
  `risk_field_cache[jurisdiction_id]`), bootstrapping it on first access if
  this jurisdiction's cache is still cold (e.g. right after a process
  restart, before the next transaction.ingested tick) - never a stale/empty
  response when a real field can be derived.
- `at=<timestamp>`: historical replay, always freshly re-derived from the
  durable `predictions` table for that instant - never read from, and never
  written into, the live cache (a past snapshot must never overwrite what
  connected investigators are currently looking at).
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.auth.schemas import TokenClaims
from app.db.models.enums import UserRole
from app.db.models.jurisdictions import Jurisdiction
from app.db.session import get_db
from app.graph.risk_field import compute_risk_field, get_cache_generated_at, get_cached_field, seed_cache_from_scratch
from app.modules.jurisdictions.schemas import RiskFieldCell, RiskFieldResponse

router = APIRouter(prefix="/v1/jurisdictions", tags=["jurisdictions"])

INVESTIGATIVE_ROLES = (
    UserRole.investigator,
    UserRole.supervisor,
    UserRole.auditor,
    UserRole.admin,
)


def _get_jurisdiction_or_404(db: Session, jurisdiction_id: str) -> Jurisdiction:
    jurisdiction = db.query(Jurisdiction).filter(Jurisdiction.jurisdiction_id == jurisdiction_id).first()
    if jurisdiction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jurisdiction not found")
    return jurisdiction


def _enforce_jurisdiction_scope(jurisdiction_id: str, claims: TokenClaims) -> None:
    """Mirrors app/modules/complaints/router.py::_enforce_jurisdiction_scope -
    investigator/supervisor confined to their own jurisdiction; auditor/admin
    see any (docs/SECURITY_AND_GOVERNANCE.md §3's RBAC matrix)."""
    if claims.role in (UserRole.investigator, UserRole.supervisor):
        if jurisdiction_id != claims.jurisdiction_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This jurisdiction is outside your jurisdiction",
            )


@router.get("/{jurisdiction_id}/risk-field", response_model=RiskFieldResponse)
def get_jurisdiction_risk_field(
    jurisdiction_id: str,
    at: Optional[datetime] = None,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(*INVESTIGATIVE_ROLES)),
) -> RiskFieldResponse:
    _get_jurisdiction_or_404(db, jurisdiction_id)
    _enforce_jurisdiction_scope(jurisdiction_id, claims)

    if at is not None:
        as_of = at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)
        field = compute_risk_field(db, jurisdiction_id, as_of=as_of)
        generated_for = as_of
    else:
        generated_for = get_cache_generated_at(jurisdiction_id)
        if generated_for is None:
            field = seed_cache_from_scratch(db, jurisdiction_id)
            generated_for = get_cache_generated_at(jurisdiction_id)
        else:
            field = get_cached_field(jurisdiction_id)

    h3_cells = [RiskFieldCell(h3_cell=cell, score=score) for cell, score in sorted(field.items())]
    return RiskFieldResponse(h3_cells=h3_cells, generated_for=generated_for)
