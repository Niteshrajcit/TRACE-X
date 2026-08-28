"""
The Phase 2A integration test required by the implementation brief:

    transaction ingestion -> PostgreSQL transaction -> Graph Builder
    -> Neo4j nodes -> Neo4j relationships -> correct hop indexes

Walks a realistic 3-hop mule chain (victim -> mule1 -> mule2 -> mule3,
cashing out at a seeded ATM exit channel, with device/IP/phone/VPA context
on one hop) through the real HTTP API, then independently queries both
PostgreSQL and Neo4j to verify - never trusting only the API's own success
responses or application logs.
"""
import pytest

from app.core.security import hash_pii
from app.db.models.enums import ExitChannelType, InterventionActionType
from app.db.models.exit_channels import ExitChannel
from app.db.models.transactions import Transaction
from app.db.neo4j_client import check_connectivity, get_driver
from tests.conftest import auth_headers, service_token, valid_transaction_payload

pytestmark = pytest.mark.skipif(
    not check_connectivity(), reason="Neo4j not reachable - skipping the graph integration test"
)


def _run(query, **params):
    driver = get_driver()
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


@pytest.fixture
def seeded_exit_channel(db):
    channel = ExitChannel(
        channel_type=ExitChannelType.atm_cash,
        external_ref="Integration Test ATM",
        geo_lat=13.05,
        geo_lon=80.25,
        h3_cell="88618c4885fffff",
        channel_attributes={"cash_limit": 20000, "cctv_flag": True, "footfall_tier": "medium"},
        intervention_action_type=InterventionActionType.physical_team_deployment,
        is_synthetic=True,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def test_full_mule_chain_ingestion_produces_a_verified_neo4j_subgraph(
    client, db, submitted_complaint, seeded_exit_channel
):
    complaint_id = submitted_complaint["complaint_id"]
    victim = "VICTIM-0001"  # matches submitted_complaint fixture
    mule_1, mule_2, mule_3 = "INTEG-MULE-1", "INTEG-MULE-2", "INTEG-MULE-3"

    def ingest(**overrides):
        payload = valid_transaction_payload(complaint_id=complaint_id, **overrides)
        response = client.post(
            "/v1/transactions/ingest", json=payload, headers=auth_headers(service_token())
        )
        assert response.status_code == 202, response.text
        return response.json()

    try:
        r1 = ingest(
            from_account_number=victim,
            to_account_number=mule_1,
            amount="200000.00",
            device_id="victim-phone-imei-001",
            ip_address="198.51.100.7",
        )
        r2 = ingest(from_account_number=mule_1, to_account_number=mule_2, amount="180000.00", channel="imps")
        r3 = ingest(
            from_account_number=mule_2,
            to_account_number=mule_3,
            amount="150000.00",
            channel="cash_withdrawal",
            exit_channel_id=seeded_exit_channel.channel_id,
            originator_vpa="mule2@fraudbank",
        )

        # ---- Step 1: PostgreSQL is the source of truth - verify there directly ----
        assert r1["hop_index"] == 1
        assert r2["hop_index"] == 2
        assert r3["hop_index"] == 3

        pg_rows = (
            db.query(Transaction)
            .filter(Transaction.complaint_id == complaint_id)
            .order_by(Transaction.hop_index.asc())
            .all()
        )
        assert [row.hop_index for row in pg_rows] == [1, 2, 3]
        assert pg_rows[2].exit_channel_id == seeded_exit_channel.channel_id
        assert all(row.is_synthetic for row in pg_rows)

        # ---- Step 2: independently inspect Neo4j - not application logs ----
        victim_hash = hash_pii(victim)
        mule_1_hash = hash_pii(mule_1)
        mule_2_hash = hash_pii(mule_2)
        mule_3_hash = hash_pii(mule_3)

        # Complaint -> victim account
        involves = _run(
            "MATCH (c:Complaint {complaint_id: $cid})-[:INVOLVES]->(a:Account {account_hash: $h}) RETURN a",
            cid=complaint_id, h=victim_hash,
        )
        assert len(involves) == 1, "Complaint is not linked to its victim account in Neo4j"

        # The full chain, in order, with correct hop indexes as edge properties
        chain = _run(
            "MATCH (v:Account {account_hash: $victim_hash})"
            "-[t1:TRANSFERRED_TO]->(m1:Account {account_hash: $mule1_hash})"
            "-[t2:TRANSFERRED_TO]->(m2:Account {account_hash: $mule2_hash})"
            "-[t3:TRANSFERRED_TO]->(m3:Account {account_hash: $mule3_hash}) "
            "RETURN t1.hop_index AS h1, t2.hop_index AS h2, t3.hop_index AS h3, "
            "       t1.amount AS a1, t2.channel AS c2",
            victim_hash=victim_hash, mule1_hash=mule_1_hash, mule2_hash=mule_2_hash, mule3_hash=mule_3_hash,
        )
        assert len(chain) == 1, "The 3-hop TRANSFERRED_TO chain was not found intact in Neo4j"
        assert (chain[0]["h1"], chain[0]["h2"], chain[0]["h3"]) == (1, 2, 3)
        assert chain[0]["a1"] == "200000.00"
        assert chain[0]["c2"] == "imps"

        # Device/IP linked to the victim account (from the first hop)
        device_link = _run(
            "MATCH (a:Account {account_hash: $h})-[:HAS_DEVICE]->(d:Device {device_hash: $dh}) RETURN d",
            h=victim_hash, dh=hash_pii("victim-phone-imei-001"),
        )
        ip_link = _run(
            "MATCH (a:Account {account_hash: $h})-[:HAS_IP]->(i:IP {ip_hash: $ih}) RETURN i",
            h=victim_hash, ih=hash_pii("198.51.100.7"),
        )
        assert len(device_link) == 1
        assert len(ip_link) == 1

        # VPA linked to mule_2 (the from-account of the third hop)
        vpa_link = _run(
            "MATCH (a:Account {account_hash: $h})-[:HAS_VPA]->(v:VPA {vpa_hash: $vh}) RETURN v",
            h=mule_2_hash, vh=hash_pii("mule2@fraudbank"),
        )
        assert len(vpa_link) == 1

        # Terminal cash-out: mule_3 -> the seeded ExitChannel
        exit_link = _run(
            "MATCH (a:Account {account_hash: $h})-[:EXITED_VIA]->(e:ExitChannel {channel_id: $cid}) RETURN e",
            h=mule_3_hash, cid=seeded_exit_channel.channel_id,
        )
        assert len(exit_link) == 1, "Terminal account is not linked to the exit channel in Neo4j"

        # ---- Step 3: bounded traversal returns the whole chain within the configured depth ----
        subgraph = _run(
            "MATCH (c:Complaint {complaint_id: $cid})-[:INVOLVES]->(v:Account) "
            "OPTIONAL MATCH p = (v)-[:TRANSFERRED_TO*1..6]->(a:Account) "
            "RETURN a.account_hash AS reached, length(p) AS depth",
            cid=complaint_id,
        )
        reached_hashes = {row["reached"] for row in subgraph}
        assert {mule_1_hash, mule_2_hash, mule_3_hash}.issubset(reached_hashes)
        depths = {row["reached"]: row["depth"] for row in subgraph}
        assert depths[mule_1_hash] == 1
        assert depths[mule_2_hash] == 2
        assert depths[mule_3_hash] == 3
    finally:
        _run(
            "MATCH (n) WHERE n.complaint_id = $cid OR n.account_hash IN $hashes "
            "OR n.device_hash = $dh OR n.ip_hash = $ih OR n.vpa_hash = $vh OR n.channel_id = $chid "
            "DETACH DELETE n",
            cid=complaint_id,
            hashes=[hash_pii(victim), hash_pii(mule_1), hash_pii(mule_2), hash_pii(mule_3)],
            dh=hash_pii("victim-phone-imei-001"),
            ih=hash_pii("198.51.100.7"),
            vh=hash_pii("mule2@fraudbank"),
            chid=seeded_exit_channel.channel_id,
        )
