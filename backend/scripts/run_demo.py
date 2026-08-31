"""
Full end-to-end demo seeder: creates a complete, realistic fraud case using
only the seeded synthetic accounts (which have real branch_lat/lon), then
drips the transaction chain through the real API so the full intelligence
pipeline (ring detection -> corridor prediction -> exit scoring -> map) runs.

Because all accounts in the chain already exist in Postgres with real
branch coordinates, the corridor predictor can compute geo-features and
the prediction map will show real locations.

Usage:
    python scripts/run_demo.py scripts/demo_scenario_a_atm.yaml --speed 2.0
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import yaml

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.db.models.accounts import Account
from app.db.models.exit_channels import ExitChannel
from app.db.models.enums import ExitChannelType
from app.db.models.jurisdictions import Jurisdiction
from app.db.models.transactions import Transaction
from app.db.models.complaints import Complaint
from app.modules.complaints.service import create_complaint, DEFAULT_JURISDICTION_NAME
from app.modules.complaints.schemas import ComplaintCreateRequest
from sqlalchemy import func
from decimal import Decimal


def pick_seeded_chain(jurisdiction_hint: str, hop_count: int) -> tuple[Account, list[Account]]:
    """Pick a victim account and `hop_count` mule accounts from the seeded ring
    pool, all with real branch coordinates. Returns (victim_account, mule_accounts).
    Prefers accounts that already have internal synthetic transactions between them."""
    db = SessionLocal()
    try:
        # Get all seeded ring accounts with coordinates
        all_accounts = (
            db.query(Account)
            .filter(
                Account.is_synthetic == True,
                Account.ring_id.isnot(None),
                Account.branch_lat.isnot(None),
                Account.branch_lon.isnot(None),
            )
            .all()
        )

        needed = hop_count + 1
        if len(all_accounts) < needed:
            raise ValueError(
                f"Not enough seeded accounts with geo-coordinates "
                f"(found {len(all_accounts)}, need {needed}). "
                "Run 'python scripts/seed_synthetic.py' first."
            )

        # Pick from different rings
        seen_rings = set()
        selected = []
        for acc in all_accounts:
            if acc.ring_id not in seen_rings:
                selected.append(acc)
                seen_rings.add(acc.ring_id)
            if len(selected) >= needed:
                break

        if len(selected) < needed:
            for acc in all_accounts:
                if acc not in selected:
                    selected.append(acc)
                if len(selected) >= needed:
                    break

        return selected[0], selected[1:needed]
    finally:
        db.close()


def seed_complaint_with_seeded_victim(
    fraud_type: str,
    amount: int,
    location_text: str,
    jurisdiction_hint: str,
    victim_account: Account,
) -> str:
    """Creates the complaint record directly via the service (same code path
    as the HTTP endpoint), but sets victim_account_id to the already-seeded
    account so it has real branch_lat/lon. Returns the complaint_id."""
    db = SessionLocal()
    try:
        request = ComplaintCreateRequest(
            incident_datetime=datetime.now(timezone.utc) - timedelta(minutes=15),
            fraud_type=fraud_type,
            amount=Decimal(str(amount)),
            location_text=location_text,
            location_lat=victim_account.branch_lat,
            location_lon=victim_account.branch_lon,
            institution_name="Northbridge Bank",
            institution_type="bank",
            transaction_reference=f"TXN-DEMO-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            victim_account_number=None,  # we'll set victim_account_id directly
            victim_phone="+91-90000-00002",
            victim_email="demo@example.com",
            description="Live demo simulated incident - UPI fraud via mule chain.",
            evidence_notes=["Live demo run", "Automated scenario playback"],
            jurisdiction_hint=jurisdiction_hint,
            idempotency_key=None,
        )
        complaint, _ = create_complaint(db, request, is_demo_data=True)

        # Override victim_account_id to point at the seeded account with coordinates
        complaint.victim_account_id = victim_account.account_id
        db.flush()
        db.commit()
        db.refresh(complaint)
        return complaint.complaint_id
    finally:
        db.close()


def get_exit_channel_id(channel_type_str: str) -> Optional[str]:
    db = SessionLocal()
    try:
        channel_type = ExitChannelType(channel_type_str)
        channel = db.query(ExitChannel).filter(ExitChannel.channel_type == channel_type).first()
        if not channel:
            return None
        return channel.channel_id
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_file", help="Path to the scenario YAML file")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--speed", type=float, default=1.0, help="Speed multiplier (e.g. 2.0 for 2x speed)")
    args = parser.parse_args()

    with open(args.scenario_file, "r") as f:
        scenario = yaml.safe_load(f)

    print(f"Loaded scenario: {scenario['scenario']}")

    hops = scenario.get("hops", [])
    if not hops:
        print("No hops defined in scenario.")
        return

    # Mint a service token for the transaction ingest endpoint
    token = create_access_token(
        {"sub": "synthetic-harness", "role": "service", "jurisdiction_id": None, "bank_id": None},
        expires_minutes=60,
    )
    headers = {"Authorization": f"Bearer {token}"}

    jurisdiction_hint = scenario.get("jurisdiction_hint", "Chennai")

    # Pick seeded accounts with real coordinates
    try:
        victim_account, mule_accounts = pick_seeded_chain(jurisdiction_hint, len(hops))
        print(f"Victim account: {victim_account.account_hash[:16]}... lat={victim_account.branch_lat:.4f}")
        for i, m in enumerate(mule_accounts):
            print(f"Mule {i+1}:        {m.account_hash[:16]}... lat={m.branch_lat:.4f}")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Create complaint with the seeded victim account (has real coordinates)
    print("\n[1] Creating complaint with seeded victim account...")
    complaint_id = seed_complaint_with_seeded_victim(
        fraud_type=scenario["fraud_type"],
        amount=scenario["amount"],
        location_text=f"Demo Location, {jurisdiction_hint}",
        jurisdiction_hint=jurisdiction_hint,
        victim_account=victim_account,
    )
    print(f"    Complaint ID: {complaint_id}")
    print(f"    Reference:    TX-2026-DEMO")

    # Drip transactions through the real API using seeded accounts
    current_from = victim_account.account_hash

    # Exit channel for last hop
    cash_out = scenario.get("planted_cash_out", {})
    exit_channel_id = None
    if cash_out and "channel_type" in cash_out:
        exit_channel_id = get_exit_channel_id(cash_out["channel_type"])
        if exit_channel_id:
            print(f"    Exit channel: {exit_channel_id[:8]}... ({cash_out['channel_type']})")

    occurred = datetime.now(timezone.utc) - timedelta(minutes=15)

    for i, (hop, mule_account) in enumerate(zip(hops, mule_accounts)):
        delay = hop.get("delay_s", 5) / args.speed
        print(f"\n    Sleeping {delay:.1f}s before hop {i+1}...")
        time.sleep(delay)

        occurred += timedelta(seconds=hop.get("delay_s", 5) * 60)
        amount = scenario["amount"] * hop.get("amount_pct", 1.0)

        txn_payload = {
            "complaint_id": complaint_id,
            "from_account_number": current_from,
            "to_account_number": mule_account.account_hash,
            "amount": amount,
            "channel": hop["channel"],
            "occurred_at": occurred.isoformat(),
        }
        if i == len(hops) - 1 and exit_channel_id:
            txn_payload["exit_channel_id"] = exit_channel_id

        print(f"[2.{i+1}] Hop {current_from[:8]}... -> {mule_account.account_hash[:8]}... (lat={mule_account.branch_lat:.4f})")
        txn_resp = httpx.post(
            f"{args.base_url}/v1/transactions/ingest",
            json=txn_payload,
            headers=headers,
            timeout=10.0,
        )
        txn_resp.raise_for_status()
        print(f"      Ingested: {txn_resp.json()['txn_id']}")
        current_from = mule_account.account_hash

    print(f"\n✓ Scenario complete!")
    print(f"  Case URL: http://localhost:5173/cases/{complaint_id}")
    print(f"  All accounts have real coordinates - prediction map should populate in ~10s")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"Request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        sys.exit(1)
    except httpx.ConnectError:
        print("Could not reach backend.", file=sys.stderr)
        sys.exit(1)
