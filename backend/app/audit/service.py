"""
Hash-chained, append-only audit log.
docs/SECURITY_AND_GOVERNANCE.md §4: `this_hash = SHA256(prev_hash ||
canonical_json(payload) || occurred_at || seq_no)`. Real, working
tamper-evidence - not the "blockchain anchoring" idea that was explicitly
decided against for this build (docs/PRODUCT_EXPERIENCE.md §8.3).

Concurrency note: `seq_no`/`prev_hash` are computed from the current max row
inside the caller's transaction. On PostgreSQL this should be hardened with
`SELECT ... FOR UPDATE` on the last row (or a dedicated counter table) before
concurrent writers are a real concern - Phase 1's write volume (one event per
complaint submission) does not need that yet, and SQLite (this phase's
Docker-less test/dev target) doesn't support that clause the same way. Noted
here rather than silently assumed safe at higher concurrency.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models.audit import AuditEvent


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_timestamp(occurred_at: datetime) -> str:
    """SQLite (this phase's Docker-less test/dev database, see
    app/db/session.py) does not round-trip timezone-aware datetimes - a
    value written as tz-aware UTC comes back naive on the next query, which
    would otherwise make `verify_chain`'s recomputed hash disagree with the
    hash computed at write time purely because of a storage round-trip, not
    real tampering. Every `occurred_at` in this module is UTC by
    construction, so stripping tzinfo before hashing - consistently on both
    the write path and the verify path - is lossless and dialect-independent
    (PostgreSQL, which does preserve tzinfo, produces the same normalized
    string here too)."""
    return occurred_at.replace(tzinfo=None).isoformat()


def append_audit_event(
    db: Session,
    *,
    event_type: str,
    subject_type: str,
    subject_id: Optional[str],
    payload: dict,
    actor_id: Optional[str] = None,
) -> AuditEvent:
    last = db.query(AuditEvent).order_by(AuditEvent.seq_no.desc()).first()
    seq_no = (last.seq_no + 1) if last else 1
    prev_hash = last.this_hash if last else None
    occurred_at = datetime.now(timezone.utc)

    digest_input = "|".join(
        [prev_hash or "", _canonical_json(payload), _canonical_timestamp(occurred_at), str(seq_no)]
    )
    this_hash = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()

    event = AuditEvent(
        seq_no=seq_no,
        event_type=event_type,
        actor_id=actor_id,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
        occurred_at=occurred_at,
        prev_hash=prev_hash,
        this_hash=this_hash,
    )
    db.add(event)
    db.flush()  # assign event_id / make visible to the rest of this transaction
    return event


def verify_chain(
    db: Session, from_seq: Optional[int] = None, to_seq: Optional[int] = None
) -> tuple[bool, Optional[int]]:
    """Recomputes every hash from seq_no=1 forward (or from `from_seq`/to
    `to_seq` - docs/API_CONTRACT.md §5's `GET /v1/audit/verify-chain?from_seq=&to_seq=`);
    returns (valid, first broken seq_no or None). `from_seq`/`to_seq` are
    additive, optional parameters - existing callers passing neither behave
    exactly as before (full-chain verification from seq 1).

    A partial range's starting `prev_hash` must be the REAL preceding
    event's hash, not None - otherwise the first event in an arbitrary
    from_seq > 1 range would always look "broken" purely from the range
    boundary, not real tampering."""
    query = db.query(AuditEvent).order_by(AuditEvent.seq_no.asc())
    if from_seq is not None:
        query = query.filter(AuditEvent.seq_no >= from_seq)
    if to_seq is not None:
        query = query.filter(AuditEvent.seq_no <= to_seq)
    events = query.all()

    prev_hash: Optional[str] = None
    if from_seq is not None and from_seq > 1:
        preceding = db.query(AuditEvent).filter(AuditEvent.seq_no == from_seq - 1).first()
        prev_hash = preceding.this_hash if preceding else None

    for event in events:
        digest_input = "|".join(
            [
                prev_hash or "",
                _canonical_json(event.payload),
                _canonical_timestamp(event.occurred_at),
                str(event.seq_no),
            ]
        )
        expected = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
        if expected != event.this_hash or (event.prev_hash or None) != prev_hash:
            return False, event.seq_no
        prev_hash = event.this_hash
    return True, None
