"""
Transaction ingestion business logic (docs/API_CONTRACT.md §1a/§1b).

PostgreSQL is written first and is authoritative; the Neo4j graph write
(app/graph/builder.py) happens only after this function's caller (the
router) has confirmed the Postgres commit succeeded, and is never allowed
to roll that commit back on failure.
"""
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.service import append_audit_event
from app.core.security import hash_pii
from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import LinkedEntityType
from app.db.models.exit_channels import ExitChannel
from app.db.models.transactions import Transaction
from app.modules.transactions.schemas import TransactionIngestRequest
from app.shared.accounts import attach_linked_entity, find_or_create_account
from app.core.config import get_settings

settings = get_settings()
MAX_HOP_DEPTH = settings.max_hop_depth


class ComplaintNotFound(Exception):
    pass


class ExitChannelNotFound(Exception):
    pass


class IdempotencyConflict(Exception):
    """Raised when a caller reuses an idempotency_key with a materially
    different payload - a client bug, not something to silently paper over
    by picking one payload or the other."""


def _matches_existing(db: Session, existing: Transaction, request: TransactionIngestRequest) -> bool:
    """Compares the *hashed* identity plus every other field - never
    compares raw request values against stored hashes directly.

    `occurred_at` is compared with tzinfo stripped on both sides: SQLite
    (this repo's Docker-less test/dev dialect, app/db/session.py) does not
    round-trip timezone-aware datetimes, so a value written as tz-aware UTC
    comes back naive on the next query - comparing it directly against the
    freshly-parsed, still-aware request value would spuriously read as a
    conflict on every replay. Same normalization already applied in
    app/audit/service.py's `_canonical_timestamp` for the identical reason;
    both `occurred_at` values are UTC by construction, so stripping tzinfo
    is lossless and dialect-independent (PostgreSQL, which does preserve
    tzinfo, compares identically either way)."""
    from_account = db.query(Account).filter(Account.account_id == existing.from_account_id).first()
    to_account = db.query(Account).filter(Account.account_id == existing.to_account_id).first()
    return (
        existing.complaint_id == request.complaint_id
        and from_account is not None
        and from_account.account_hash == hash_pii(request.from_account_number)
        and to_account is not None
        and to_account.account_hash == hash_pii(request.to_account_number)
        and existing.amount == request.amount
        and existing.channel == request.channel
        and existing.occurred_at.replace(tzinfo=None) == request.occurred_at.replace(tzinfo=None)
    )


def compute_hop_index(db: Session, complaint: Complaint, from_account_id: str) -> int:
    """docs/API_CONTRACT.md §1a: server-computed, Postgres-only (never a
    Neo4j graph query - Postgres is the source of truth, per §1b), capped
    at MAX_HOP_DEPTH rather than growing unbounded.

    - `from_account_id` is the complaint's victim account -> hop_index 1
      (the first hop away from the victim).
    - otherwise -> 1 + the highest hop_index among this complaint's
      transactions that deposited *into* from_account (the natural next
      link in the chain), capped at MAX_HOP_DEPTH.
    - from_account has never received funds in this complaint's traced
      chain: if the complaint has no transactions at all yet, this is
      legitimately the first hop (e.g. no victim_account_id was ever
      recorded); if the complaint already has other transactions but this
      account was never one of their recipients, treat it as already at
      the bounded max depth rather than allowing an unbounded jump into
      the middle of an existing chain.
    """
    if complaint.victim_account_id and from_account_id == complaint.victim_account_id:
        return 1

    prior_max = (
        db.query(func.max(Transaction.hop_index))
        .filter(
            Transaction.complaint_id == complaint.complaint_id,
            Transaction.to_account_id == from_account_id,
        )
        .scalar()
    )
    if prior_max is not None:
        return min(prior_max + 1, MAX_HOP_DEPTH)

    has_any_transactions = (
        db.query(Transaction.txn_id)
        .filter(Transaction.complaint_id == complaint.complaint_id)
        .first()
        is not None
    )
    return 1 if not has_any_transactions else MAX_HOP_DEPTH


def ingest_transaction(
    db: Session, request: TransactionIngestRequest
) -> tuple[Transaction, bool]:
    """Returns (transaction, was_created). was_created=False means an
    existing row with the same idempotency_key was returned (a true
    replay - identical payload). Raises IdempotencyConflict if the same
    key was reused with a different payload, ComplaintNotFound /
    ExitChannelNotFound for bad references."""
    if request.idempotency_key:
        existing = (
            db.query(Transaction)
            .filter(Transaction.idempotency_key == request.idempotency_key)
            .first()
        )
        if existing:
            if _matches_existing(db, existing, request):
                return existing, False
            raise IdempotencyConflict(
                f"idempotency_key '{request.idempotency_key}' was already used with a different payload"
            )

    complaint = db.query(Complaint).filter(Complaint.complaint_id == request.complaint_id).first()
    if complaint is None:
        raise ComplaintNotFound(f"No complaint with id {request.complaint_id}")

    exit_channel: Optional[ExitChannel] = None
    if request.exit_channel_id:
        exit_channel = (
            db.query(ExitChannel).filter(ExitChannel.channel_id == request.exit_channel_id).first()
        )
        if exit_channel is None:
            raise ExitChannelNotFound(f"No exit channel with id {request.exit_channel_id}")

    # Only the synthetic harness calls this endpoint today (no real bank/NCRP
    # adapter exists yet - ⚪ FUTURE per docs/PRODUCT.md §5), so a NEW account
    # first seen through transaction ingestion is honestly synthetic. An
    # account already known (e.g. a citizen's own victim account from
    # POST /v1/complaints) keeps whatever provenance it already has -
    # find_or_create_account never overwrites an existing row's flag.
    from_account_id = find_or_create_account(db, request.from_account_number, is_synthetic=True)
    to_account_id = find_or_create_account(db, request.to_account_number, is_synthetic=True)

    attach_linked_entity(db, from_account_id, LinkedEntityType.device, request.device_id)
    attach_linked_entity(db, from_account_id, LinkedEntityType.ip, request.ip_address)
    attach_linked_entity(db, from_account_id, LinkedEntityType.phone, request.originator_phone)
    attach_linked_entity(db, from_account_id, LinkedEntityType.vpa, request.originator_vpa)

    hop_index = compute_hop_index(db, complaint, from_account_id)

    txn = Transaction(
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        amount=request.amount,
        channel=request.channel,
        hop_index=hop_index,
        complaint_id=complaint.complaint_id,
        occurred_at=request.occurred_at,
        idempotency_key=request.idempotency_key,
        exit_channel_id=request.exit_channel_id,
        is_synthetic=True,
    )
    db.add(txn)
    db.flush()

    append_audit_event(
        db,
        event_type="transaction.ingested",
        subject_type="transaction",
        subject_id=txn.txn_id,
        payload={
            "complaint_id": complaint.complaint_id,
            "channel": txn.channel.value,
            "hop_index": hop_index,
        },
    )

    db.commit()
    db.refresh(txn)
    return txn, True
