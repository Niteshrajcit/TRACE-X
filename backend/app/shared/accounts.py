"""
Shared account/linked-entity hashing helpers (SECURITY_AND_GOVERNANCE.md §2).
Extracted from app/modules/complaints/service.py during Phase 2A so
app/modules/transactions/service.py uses the exact same hash-at-the-boundary
logic rather than a second, drifting copy - "do not accept client-computed
hashes as the authoritative identity" only holds if there is exactly one
place identifiers get hashed.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import hash_pii
from app.db.models.accounts import Account, LinkedEntity
from app.db.models.enums import LinkedEntityType


def find_or_create_account(
    db: Session, account_number: Optional[str], *, is_synthetic: bool
) -> Optional[str]:
    """Returns the account_id for a raw account number, hashing it first.
    Never touches `is_synthetic` on an account that already exists -
    provenance is set once, at first sight, not overwritten by whichever
    caller happens to reference the account next."""
    if not account_number:
        return None
    account_hash = hash_pii(account_number)
    existing = db.query(Account).filter(Account.account_hash == account_hash).first()
    if existing:
        return existing.account_id
    account = Account(account_hash=account_hash, is_synthetic=is_synthetic)
    db.add(account)
    db.flush()
    return account.account_id


def attach_linked_entity(
    db: Session, account_id: Optional[str], entity_type: LinkedEntityType, raw_value: Optional[str]
) -> None:
    if not account_id or not raw_value:
        return
    entity_hash = hash_pii(raw_value)
    exists = (
        db.query(LinkedEntity)
        .filter(
            LinkedEntity.account_id == account_id,
            LinkedEntity.entity_type == entity_type,
            LinkedEntity.entity_hash == entity_hash,
        )
        .first()
    )
    if exists:
        return
    db.add(LinkedEntity(account_id=account_id, entity_type=entity_type, entity_hash=entity_hash))
