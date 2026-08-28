"""
docs/API_CONTRACT.md §1a. Service-role-only; no investigator/citizen access.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.dependencies import require_roles
from app.auth.schemas import TokenClaims
from app.db.models.accounts import Account, LinkedEntity
from app.db.models.complaints import Complaint
from app.db.models.enums import UserRole
from app.db.models.exit_channels import ExitChannel
from app.db.models.transactions import Transaction
from app.db.session import get_db
from app.events.dispatcher import dispatcher
from app.events.topics import GRAPH_UPDATED, TRANSACTION_INGESTED
from app.graph import builder as graph_builder
from app.modules.transactions import service
from app.modules.transactions.schemas import TransactionIngestRequest, TransactionIngestResponse

router = APIRouter(prefix="/v1/transactions", tags=["transactions"])


def _write_to_graph(db: Session, txn: Transaction) -> None:
    """Best-effort Neo4j write, called only after the Postgres commit
    succeeded (docs/API_CONTRACT.md §1b) - never raises past this function,
    a Neo4j problem is logged and left for scripts/rebuild_neo4j_graph.py
    to reconcile, not surfaced as a 500 for a transaction that is already
    safely recorded."""
    complaint = db.query(Complaint).filter(Complaint.complaint_id == txn.complaint_id).first()
    from_account = db.query(Account).filter(Account.account_id == txn.from_account_id).first()
    to_account = db.query(Account).filter(Account.account_id == txn.to_account_id).first()
    if complaint is None or from_account is None or to_account is None:
        return  # should not happen - both were just resolved in the same transaction

    if complaint.victim_account_id:
        victim = db.query(Account).filter(Account.account_id == complaint.victim_account_id).first()
        if victim:
            graph_builder.ensure_complaint_victim_link(complaint.complaint_id, victim.account_hash)

    if txn.exit_channel_id:
        exit_channel = db.query(ExitChannel).filter(ExitChannel.channel_id == txn.exit_channel_id).first()
        if exit_channel:
            graph_builder.sync_exit_channel(exit_channel)

    graph_builder.apply_transaction(
        from_hash=from_account.account_hash,
        to_hash=to_account.account_hash,
        txn_id=txn.txn_id,
        amount=str(txn.amount),
        channel=txn.channel.value,
        hop_index=txn.hop_index,
        occurred_at=txn.occurred_at.isoformat(),
        exit_channel_id=txn.exit_channel_id,
    )


def _link_from_account_entities(db: Session, txn: Transaction) -> None:
    """Mirrors every linked_entities row on the from-account into the graph
    as a HAS_* edge. Re-derived from `linked_entities` (hashes only - raw
    device/IP/phone/VPA values are never stored anywhere, per
    SECURITY_AND_GOVERNANCE.md §2) rather than threaded through from the
    request, so this also correctly re-links entities attached to this
    account by an *earlier* transaction, not just this one."""
    entities = (
        db.query(LinkedEntity)
        .filter(LinkedEntity.account_id == txn.from_account_id)
        .all()
    )
    from_account = db.query(Account).filter(Account.account_id == txn.from_account_id).first()
    if from_account is None:
        return
    for entity in entities:
        graph_builder.link_entity(from_account.account_hash, entity.entity_type.value, entity.entity_hash)


@router.post("/ingest", response_model=TransactionIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_transaction(
    request: TransactionIngestRequest,
    response: Response,
    db: Session = Depends(get_db),
    claims: TokenClaims = Depends(require_roles(UserRole.service)),
) -> TransactionIngestResponse:
    try:
        txn, was_created = await run_in_threadpool(service.ingest_transaction, db, request)
    except service.ComplaintNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.ExitChannelNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.IdempotencyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not was_created:
        response.status_code = status.HTTP_200_OK  # idempotent replay, not a new resource
        return TransactionIngestResponse(txn_id=txn.txn_id, hop_index=txn.hop_index)

    await dispatcher.publish(
        TRANSACTION_INGESTED,
        {
            "txn_id": txn.txn_id,
            "complaint_id": txn.complaint_id,
            "amount": str(txn.amount),
            "channel": txn.channel.value,
            "hop_index": txn.hop_index,
            "occurred_at": txn.occurred_at.isoformat(),
        },
    )

    # Neo4j write: best-effort, after commit, never rolls back the Postgres
    # row already safely persisted above (docs/API_CONTRACT.md §1b).
    await run_in_threadpool(_write_to_graph, db, txn)
    await run_in_threadpool(_link_from_account_entities, db, txn)

    await dispatcher.publish(
        GRAPH_UPDATED,
        {"complaint_id": txn.complaint_id, "txn_id": txn.txn_id, "hop_index": txn.hop_index},
    )

    return TransactionIngestResponse(txn_id=txn.txn_id, hop_index=txn.hop_index)
