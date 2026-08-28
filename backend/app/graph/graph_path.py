"""
Real Neo4j graph-path extraction for the Explainer - AI_ML_ARCHITECTURE.md
§6, Phase 2F.

[Phase 2F decision freeze #2] A predicted exit channel has not occurred yet,
so no `EXITED_VIA` edge to it exists in Neo4j - that relationship is only
ever written for a transaction that actually happened
(API_CONTRACT.md §1c). This module never invents one. It computes the real,
Neo4j-verified path from the victim account through the ring's actual
`TRANSFERRED_TO` chain to the "last known account" - the same reference
account app/graph/corridor.py's `_hops_for_accounts` already resolves for
exit-vector/exit-channel scoring (Phase 2C/2D), re-derived here read-only so
the explanation's path ends at the exact account the prediction was
actually computed against. The predicted exit channel is returned as a
separate, clearly-labeled field alongside the real path, never appended
into it as if it were a real edge.

No APOC/GDS is installed on either Neo4j instance (docker-compose.yml's
`NEO4J_PLUGINS: '[]'` on both `neo4j` and `neo4j-test`) - Neo4j Community's
native `shortestPath()` is hop-count/unweighted only and even that isn't
reached for here. Per the Phase 2F readiness report's recommendation, this
module reuses app/graph/builder.py::fetch_complaint_subgraph (Phase 2A,
unmodified) for the bounded real subgraph and computes the path in Python
with `networkx` (already a dependency, the same tool
app/graph/community_detection.py uses for Louvain) rather than adding a
plugin or a new dependency.

Edge weight: a uniform 1.0 per `TRANSFERRED_TO` hop - disclosed, not
fabricated. Real mule chains for one ring are typically a single near-linear
path; the honest, justifiable choice here is plain hop-count shortest path
(computed via networkx's weighted-shortest-path machinery, which reduces
exactly to hop-count under a uniform weight) rather than inventing an
unjustified temporal or amount-based weighting scheme that this dataset
does not actually support at ring-of-one-complaint scale.
"""
from typing import Optional

import networkx as nx
from neo4j import Driver
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.transactions import Transaction
from app.db.neo4j_client import get_driver
from app.graph.builder import fetch_complaint_subgraph

logger = get_logger(__name__)


def victim_account_hash(db: Session, complaint_id: str) -> Optional[str]:
    complaint = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
    if complaint is None or complaint.victim_account_id is None:
        return None
    victim = db.query(Account).filter(Account.account_id == complaint.victim_account_id).first()
    return victim.account_hash if victim else None


def last_known_account_hash(db: Session, member_account_ids: list[str]) -> Optional[str]:
    """The same 'last known account' app/graph/corridor.py::_hops_for_accounts
    resolves (Phase 2C/2D) - re-derived here read-only (identical filter:
    only hops between accounts with known geolocation; identical order:
    hop_index asc then occurred_at asc; take the last) so this module's
    path ends at the exact account corridor/exit-scorer actually used as
    their reference point. Does not call, modify, or duplicate the
    filtering logic in a way that could drift from it silently - both
    implementations independently encode the same documented rule."""
    accounts = {a.account_id: a for a in db.query(Account).filter(Account.account_id.in_(member_account_ids)).all()}
    transactions = (
        db.query(Transaction)
        .filter(Transaction.from_account_id.in_(member_account_ids), Transaction.to_account_id.in_(member_account_ids))
        .order_by(Transaction.hop_index.asc(), Transaction.occurred_at.asc())
        .all()
    )
    last_hash = None
    for txn in transactions:
        from_acc = accounts.get(txn.from_account_id)
        to_acc = accounts.get(txn.to_account_id)
        if from_acc is None or to_acc is None:
            continue
        if from_acc.branch_lat is None or from_acc.branch_lon is None:
            continue
        if to_acc.branch_lat is None or to_acc.branch_lon is None:
            continue
        last_hash = to_acc.account_hash
    return last_hash


def build_real_path_graph(chains: list[dict]) -> nx.DiGraph:
    """Pure function - builds a weighted DiGraph from
    fetch_complaint_subgraph's already-bounded, already-real path rows
    (each a `chain_hashes` node sequence). Isolated from Neo4j so it's
    directly unit-testable against fake/fixture chain data."""
    graph = nx.DiGraph()
    for row in chains:
        chain = row.get("chain_hashes")
        if not chain:
            continue
        for a, b in zip(chain, chain[1:]):
            if graph.has_edge(a, b):
                continue  # first occurrence's weight stands - uniform weight anyway
            graph.add_edge(a, b, weight=1.0)
    return graph


def compute_graph_path(
    db: Session,
    complaint_id: str,
    member_account_ids: list[str],
    predicted_exit_channel_id: Optional[str],
    driver: Optional[Driver] = None,
) -> dict:
    """Returns {"real_path": [account_hash...], "predicted_exit_channel_id":
    <id or None>, "path_complete": bool}. `real_path` is empty (never
    fabricated) if the victim or the last known account can't be resolved,
    or if Neo4j has no bounded path connecting them. `predicted_exit_channel_id`
    is always kept separate from `real_path` - it is a prediction, not an
    observed graph edge."""
    victim_hash = victim_account_hash(db, complaint_id)
    target_hash = last_known_account_hash(db, member_account_ids)

    if not victim_hash or not target_hash:
        return {"real_path": [], "predicted_exit_channel_id": predicted_exit_channel_id, "path_complete": False}

    if victim_hash == target_hash:
        return {
            "real_path": [victim_hash],
            "predicted_exit_channel_id": predicted_exit_channel_id,
            "path_complete": True,
        }

    driver = driver or get_driver()
    if driver is None:
        return {"real_path": [], "predicted_exit_channel_id": predicted_exit_channel_id, "path_complete": False}

    try:
        chains = fetch_complaint_subgraph(complaint_id, driver=driver)
    except Exception as exc:
        logger.warning("graph_path.fetch_failed", extra={"extra_fields": {"complaint_id": complaint_id, "error": str(exc)}})
        return {"real_path": [], "predicted_exit_channel_id": predicted_exit_channel_id, "path_complete": False}

    graph = build_real_path_graph(chains)
    if victim_hash not in graph or target_hash not in graph:
        return {"real_path": [], "predicted_exit_channel_id": predicted_exit_channel_id, "path_complete": False}

    try:
        path = nx.shortest_path(graph, source=victim_hash, target=target_hash, weight="weight")
    except nx.NetworkXNoPath:
        return {"real_path": [], "predicted_exit_channel_id": predicted_exit_channel_id, "path_complete": False}

    return {"real_path": path, "predicted_exit_channel_id": predicted_exit_channel_id, "path_complete": True}
