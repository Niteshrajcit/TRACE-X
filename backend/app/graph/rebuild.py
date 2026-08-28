"""
Rebuild logic: PostgreSQL -> Neo4j (docs/ARCHITECTURE.md: "Neo4j is a
derived/rebuildable intelligence graph"; docs/API_CONTRACT.md §1b).
PostgreSQL is never written to here - this module only reads it and writes
derived state to Neo4j.

Split into a per-complaint step (`rebuild_complaint_subgraph`, safe to call
on its own - it only MERGEs, never deletes) and the full destructive
rebuild (`rebuild_all`, which wipes every managed node first). Tests use
the per-complaint step directly, scoped to their own tagged data, rather
than the full wipe - `wipe_graph`/`rebuild_all` are exercised deliberately
against a real environment (scripts/rebuild_neo4j_graph.py), not run
unattended in the automated suite against a shared Neo4j instance that may
also hold real seeded/demo data.
"""
from typing import Optional

from neo4j import Driver

from app.core.logging_config import get_logger
from app.db.models.accounts import Account, LinkedEntity
from app.db.models.complaints import Complaint
from app.db.models.exit_channels import ExitChannel
from app.db.models.transactions import Transaction
from app.db.neo4j_client import check_connectivity, get_driver
from app.graph import builder as graph_builder

logger = get_logger(__name__)

MANAGED_LABELS = ["Complaint", "Account", "Device", "Phone", "IP", "VPA", "ExitChannel"]


def wipe_graph(driver: Optional[Driver] = None) -> None:
    """Deletes every node this application manages (and their relationships,
    via DETACH DELETE) - constraints/indexes are schema, not data, and are
    untouched (scripts/init_neo4j.py owns those, separately). Destructive
    across the *entire* instance - never call this from an automated test."""
    driver = driver or get_driver()
    if driver is None:
        raise RuntimeError("Neo4j is not reachable - cannot wipe")
    label_filter = " OR ".join(f"n:{label}" for label in MANAGED_LABELS)
    with driver.session() as session:
        session.run(f"MATCH (n) WHERE {label_filter} DETACH DELETE n")


def rebuild_complaint_subgraph(db, complaint_id: str, driver: Optional[Driver] = None) -> dict:
    """Re-derives one complaint's graph structure from its Postgres rows -
    the victim link, every transaction (in hop order), and every linked
    entity on each transaction's from-account. Idempotent (MERGE
    throughout via app/graph/builder.py) - safe to call on a graph that
    already has some or all of this data."""
    summary = {"complaint_linked": 0, "transactions_applied": 0, "entities_linked": 0}

    complaint = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
    if complaint is None:
        return summary

    if complaint.victim_account_id:
        victim = db.query(Account).filter(Account.account_id == complaint.victim_account_id).first()
        if victim:
            graph_builder.ensure_complaint_victim_link(complaint.complaint_id, victim.account_hash, driver=driver)
            summary["complaint_linked"] = 1

    transactions = (
        db.query(Transaction)
        .filter(Transaction.complaint_id == complaint_id)
        .order_by(Transaction.hop_index.asc())
        .all()
    )
    touched_account_ids: set[str] = set()
    for txn in transactions:
        from_account = db.query(Account).filter(Account.account_id == txn.from_account_id).first()
        to_account = db.query(Account).filter(Account.account_id == txn.to_account_id).first()
        if from_account is None or to_account is None:
            continue
        applied = graph_builder.apply_transaction(
            from_hash=from_account.account_hash,
            to_hash=to_account.account_hash,
            txn_id=txn.txn_id,
            amount=str(txn.amount),
            channel=txn.channel.value,
            hop_index=txn.hop_index,
            occurred_at=txn.occurred_at.isoformat(),
            exit_channel_id=txn.exit_channel_id,
            driver=driver,
        )
        if applied:
            summary["transactions_applied"] += 1
        touched_account_ids.add(txn.from_account_id)

    for account_id in touched_account_ids:
        account = db.query(Account).filter(Account.account_id == account_id).first()
        if account is None:
            continue
        for entity in db.query(LinkedEntity).filter(LinkedEntity.account_id == account_id).all():
            graph_builder.link_entity(account.account_hash, entity.entity_type.value, entity.entity_hash, driver=driver)
            summary["entities_linked"] += 1

    return summary


def _sync_complaintless_transactions(db, driver: Optional[Driver] = None) -> dict:
    """[Added Phase 2B - a real gap found while wiring up ring detection]
    `rebuild_complaint_subgraph` only ever covered `Transaction.complaint_id
    IS NOT NULL` rows. Batch-mode synthetic reference data - critically,
    `app/synthetic/generator.py::seed_mule_rings`'s *planted ground-truth
    mule rings*, the very thing this phase's ring detection is supposed to
    find - has `complaint_id = NULL` by design (DEMO_ARCHITECTURE.md §2:
    batch-mode data belongs to no live complaint) and was therefore
    silently never written to Neo4j at all, by either the original
    ingestion path (there is none for batch data) or the rebuild script.
    Ring detection could never have recovered a planted ring that was
    invisible to Neo4j in the first place - this function is the fix,
    applying every complaint-less transaction the same way
    `rebuild_complaint_subgraph` applies complaint-linked ones."""
    summary = {"transactions_applied": 0, "entities_linked": 0}

    transactions = (
        db.query(Transaction)
        .filter(Transaction.complaint_id.is_(None))
        .order_by(Transaction.hop_index.asc())
        .all()
    )
    touched_account_ids: set[str] = set()
    for txn in transactions:
        from_account = db.query(Account).filter(Account.account_id == txn.from_account_id).first()
        to_account = db.query(Account).filter(Account.account_id == txn.to_account_id).first()
        if from_account is None or to_account is None:
            continue
        applied = graph_builder.apply_transaction(
            from_hash=from_account.account_hash,
            to_hash=to_account.account_hash,
            txn_id=txn.txn_id,
            amount=str(txn.amount),
            channel=txn.channel.value,
            hop_index=txn.hop_index,
            occurred_at=txn.occurred_at.isoformat(),
            exit_channel_id=txn.exit_channel_id,
            driver=driver,
        )
        if applied:
            summary["transactions_applied"] += 1
        touched_account_ids.add(txn.from_account_id)

    for account_id in touched_account_ids:
        account = db.query(Account).filter(Account.account_id == account_id).first()
        if account is None:
            continue
        for entity in db.query(LinkedEntity).filter(LinkedEntity.account_id == account_id).all():
            graph_builder.link_entity(account.account_hash, entity.entity_type.value, entity.entity_hash, driver=driver)
            summary["entities_linked"] += 1

    return summary


def rebuild_all(db, driver: Optional[Driver] = None, wipe: bool = True) -> dict:
    """Full rebuild: every ExitChannel, every complaint that has at least
    one transaction, AND every complaint-less (batch-mode synthetic
    reference) transaction - see `_sync_complaintless_transactions` above
    for why that last part matters. `wipe=True` (the default, and the only
    mode scripts/rebuild_neo4j_graph.py uses) deletes the entire managed
    graph first - this is the destructive path, deliberate and explicit."""
    # [Bug found during Phase 2A live verification] Driver.verify_connectivity()
    # returns None on success (it only raises on failure) - `not
    # driver.verify_connectivity()` was therefore always True, making this
    # check fail even when Neo4j was perfectly reachable. Reusing
    # check_connectivity() (already correct: try/except, not a truthiness
    # check on a None-returning call) rather than re-deriving the same
    # logic a second, subtly wrong way.
    driver = driver or get_driver()
    if driver is None or not check_connectivity():
        raise RuntimeError("Neo4j is not reachable - cannot rebuild")

    if wipe:
        wipe_graph(driver)

    summary = {"exit_channels": 0, "complaints_linked": 0, "transactions_applied": 0, "entities_linked": 0}

    for channel in db.query(ExitChannel).all():
        graph_builder.sync_exit_channel(channel, driver=driver)
        summary["exit_channels"] += 1

    complaint_ids = [
        row[0]
        for row in db.query(Transaction.complaint_id).filter(Transaction.complaint_id.isnot(None)).distinct().all()
    ]
    for complaint_id in complaint_ids:
        per_complaint = rebuild_complaint_subgraph(db, complaint_id, driver=driver)
        summary["complaints_linked"] += per_complaint["complaint_linked"]
        summary["transactions_applied"] += per_complaint["transactions_applied"]
        summary["entities_linked"] += per_complaint["entities_linked"]

    complaintless = _sync_complaintless_transactions(db, driver=driver)
    summary["transactions_applied"] += complaintless["transactions_applied"]
    summary["entities_linked"] += complaintless["entities_linked"]

    return summary
