"""
Graph Builder tests against a REAL Neo4j instance (docs/API_CONTRACT.md
§1c). Skipped automatically if Neo4j isn't reachable - these are the tests
that need the real thing, not a substitute.

Every test tags its own account/complaint/channel identifiers with a
unique per-test prefix (`graph_prefix` fixture) and the `_cleanup_graph_nodes`
fixture removes exactly those tagged nodes afterward - the graph is a real,
shared instance, not reset per test like the relational DB.
"""
import pytest

from app.db.neo4j_client import check_connectivity, get_driver
from app.graph import builder as graph_builder

pytestmark = pytest.mark.skipif(
    not check_connectivity(), reason="Neo4j not reachable - skipping real-graph tests"
)


def _run(query, **params):
    driver = get_driver()
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def test_apply_transaction_creates_both_account_nodes_and_edge(_cleanup_graph_nodes, graph_prefix):
    from_hash = f"{graph_prefix}-from"
    to_hash = f"{graph_prefix}-to"

    applied = graph_builder.apply_transaction(
        from_hash=from_hash,
        to_hash=to_hash,
        txn_id=f"{graph_prefix}-txn1",
        amount="50000.00",
        channel="upi",
        hop_index=1,
        occurred_at="2026-08-26T10:00:00+00:00",
    )
    assert applied is True

    rows = _run(
        "MATCH (a:Account {account_hash: $from_hash})-[t:TRANSFERRED_TO]->(b:Account {account_hash: $to_hash}) "
        "RETURN t.amount AS amount, t.channel AS channel, t.hop_index AS hop_index, t.txn_id AS txn_id",
        from_hash=from_hash,
        to_hash=to_hash,
    )
    assert len(rows) == 1
    assert rows[0]["channel"] == "upi"
    assert rows[0]["hop_index"] == 1
    assert rows[0]["txn_id"] == f"{graph_prefix}-txn1"


def test_apply_transaction_beyond_max_depth_is_skipped(_cleanup_graph_nodes, graph_prefix):
    from app.core.config import get_settings

    max_depth = get_settings().max_hop_depth
    from_hash = f"{graph_prefix}-deep-from"
    to_hash = f"{graph_prefix}-deep-to"

    applied = graph_builder.apply_transaction(
        from_hash=from_hash,
        to_hash=to_hash,
        txn_id=f"{graph_prefix}-deep-txn",
        amount="1000.00",
        channel="upi",
        hop_index=max_depth + 1,
        occurred_at="2026-08-26T10:00:00+00:00",
    )
    assert applied is False

    rows = _run(
        "MATCH (a:Account {account_hash: $from_hash})-[t:TRANSFERRED_TO]->(b:Account {account_hash: $to_hash}) "
        "RETURN t",
        from_hash=from_hash,
        to_hash=to_hash,
    )
    assert rows == []


@pytest.mark.parametrize(
    "entity_type,label,id_property",
    [
        ("device", "Device", "device_hash"),
        ("phone", "Phone", "phone_hash"),
        ("ip", "IP", "ip_hash"),
        ("vpa", "VPA", "vpa_hash"),
    ],
)
def test_link_entity_creates_node_and_has_edge(
    _cleanup_graph_nodes, graph_prefix, entity_type, label, id_property
):
    account_hash = f"{graph_prefix}-acct-{entity_type}"
    entity_hash = f"{graph_prefix}-entity-{entity_type}"

    graph_builder.link_entity(account_hash, entity_type, entity_hash)

    rows = _run(
        f"MATCH (a:Account {{account_hash: $account_hash}})-[:HAS_{entity_type.upper()}]->"
        f"(n:{label} {{{id_property}: $entity_hash}}) RETURN n",
        account_hash=account_hash,
        entity_hash=entity_hash,
    )
    assert len(rows) == 1


def test_sync_exit_channel_creates_node(_cleanup_graph_nodes, graph_prefix):
    from app.db.models.enums import ExitChannelType, InterventionActionType

    class _FakeChannel:
        channel_id = f"{graph_prefix}-channel"
        channel_type = ExitChannelType.atm_cash
        h3_cell = "88618c4885fffff"
        geo_lat = 13.05
        geo_lon = 80.25
        intervention_action_type = InterventionActionType.physical_team_deployment

    graph_builder.sync_exit_channel(_FakeChannel())

    rows = _run(
        "MATCH (e:ExitChannel {channel_id: $channel_id}) RETURN e.channel_type AS channel_type, e.h3_cell AS h3_cell",
        channel_id=f"{graph_prefix}-channel",
    )
    assert len(rows) == 1
    assert rows[0]["channel_type"] == "atm_cash"


def test_apply_transaction_with_exit_channel_creates_exited_via_edge(_cleanup_graph_nodes, graph_prefix):
    from app.db.models.enums import ExitChannelType, InterventionActionType

    class _FakeChannel:
        channel_id = f"{graph_prefix}-exit-channel"
        channel_type = ExitChannelType.atm_cash
        h3_cell = "88618c4885fffff"
        geo_lat = 13.05
        geo_lon = 80.25
        intervention_action_type = InterventionActionType.physical_team_deployment

    graph_builder.sync_exit_channel(_FakeChannel())
    to_hash = f"{graph_prefix}-exit-account"
    graph_builder.apply_transaction(
        from_hash=f"{graph_prefix}-exit-source",
        to_hash=to_hash,
        txn_id=f"{graph_prefix}-exit-txn",
        amount="20000.00",
        channel="cash_withdrawal",
        hop_index=2,
        occurred_at="2026-08-26T11:00:00+00:00",
        exit_channel_id=f"{graph_prefix}-exit-channel",
    )

    rows = _run(
        "MATCH (a:Account {account_hash: $to_hash})-[:EXITED_VIA]->(e:ExitChannel {channel_id: $channel_id}) "
        "RETURN e",
        to_hash=to_hash,
        channel_id=f"{graph_prefix}-exit-channel",
    )
    assert len(rows) == 1


def test_ensure_complaint_victim_link(_cleanup_graph_nodes, graph_prefix):
    complaint_id = f"{graph_prefix}-complaint"
    victim_hash = f"{graph_prefix}-victim"

    graph_builder.ensure_complaint_victim_link(complaint_id, victim_hash)

    rows = _run(
        "MATCH (c:Complaint {complaint_id: $complaint_id})-[:INVOLVES]->(a:Account {account_hash: $victim_hash}) "
        "RETURN a",
        complaint_id=complaint_id,
        victim_hash=victim_hash,
    )
    assert len(rows) == 1


def test_ensure_complaint_victim_link_is_idempotent(_cleanup_graph_nodes, graph_prefix):
    complaint_id = f"{graph_prefix}-complaint2"
    victim_hash = f"{graph_prefix}-victim2"

    graph_builder.ensure_complaint_victim_link(complaint_id, victim_hash)
    graph_builder.ensure_complaint_victim_link(complaint_id, victim_hash)

    rows = _run(
        "MATCH (c:Complaint {complaint_id: $complaint_id})-[r:INVOLVES]->(a:Account) RETURN r",
        complaint_id=complaint_id,
    )
    assert len(rows) == 1  # MERGE, not duplicated


def test_fetch_complaint_subgraph_bounded_traversal(_cleanup_graph_nodes, graph_prefix):
    complaint_id = f"{graph_prefix}-bfscomplaint"
    victim_hash = f"{graph_prefix}-bfsvictim"
    mule_1 = f"{graph_prefix}-bfsmule1"
    mule_2 = f"{graph_prefix}-bfsmule2"

    graph_builder.ensure_complaint_victim_link(complaint_id, victim_hash)
    graph_builder.apply_transaction(
        from_hash=victim_hash, to_hash=mule_1, txn_id=f"{graph_prefix}-t1",
        amount="1000", channel="upi", hop_index=1, occurred_at="2026-08-26T10:00:00+00:00",
    )
    graph_builder.apply_transaction(
        from_hash=mule_1, to_hash=mule_2, txn_id=f"{graph_prefix}-t2",
        amount="900", channel="upi", hop_index=2, occurred_at="2026-08-26T10:05:00+00:00",
    )

    rows = graph_builder.fetch_complaint_subgraph(complaint_id, max_depth=6)
    depths = {r["depth"] for r in rows if r["depth"] is not None}
    assert 1 in depths
    assert 2 in depths


def test_neo4j_constraints_exist():
    """docs/DATA_MODEL.md §3's five uniqueness constraints, applied by
    scripts/init_neo4j.py - verified independently here, not just trusted
    from the script's own success message."""
    rows = _run("SHOW CONSTRAINTS")
    names = {r["name"] for r in rows}
    expected = {
        "complaint_id_unique",
        "account_hash_unique",
        "device_hash_unique",
        "phone_hash_unique",
        "exit_channel_id_unique",
    }
    assert expected.issubset(names)
