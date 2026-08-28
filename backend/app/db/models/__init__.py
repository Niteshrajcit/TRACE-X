"""
Import every model module so `Base.metadata` (used by Alembic autogenerate
and by the test suite's `create_all`) sees the full schema from
docs/DATA_MODEL.md in one place, even though Phase 1's application logic
only touches a subset of these tables (complaints/accounts/linked_entities/
transactions/users/jurisdictions/audit_events). The rest exist now so the
schema is provably complete and so Phase 2+ never needs a "day one" migration
that reshapes tables Phase 1 already shipped.
"""
from app.db.models.users import User
from app.db.models.jurisdictions import Jurisdiction, Bank, H3CellJurisdiction
from app.db.models.complaints import Complaint
from app.db.models.accounts import Account, LinkedEntity
from app.db.models.transactions import Transaction
from app.db.models.exit_channels import ExitChannel
from app.db.models.response_units import ResponseUnit
from app.db.models.predictions import Prediction, RecommendedDeployment, Alert, InterventionOutcome
from app.db.models.audit import AuditEvent
from app.db.models.ml_ops import ModelRegistryEntry, FeatureSnapshot
from app.db.models.rings import DetectedRing, DetectedRingMember, DetectedRingComplaint

__all__ = [
    "User",
    "Jurisdiction",
    "Bank",
    "H3CellJurisdiction",
    "Complaint",
    "Account",
    "LinkedEntity",
    "Transaction",
    "ExitChannel",
    "ResponseUnit",
    "Prediction",
    "RecommendedDeployment",
    "Alert",
    "InterventionOutcome",
    "AuditEvent",
    "ModelRegistryEntry",
    "FeatureSnapshot",
    "DetectedRing",
    "DetectedRingMember",
    "DetectedRingComplaint",
]
