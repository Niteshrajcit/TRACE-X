"""
Event handlers for automating the synthetic demo data injection.
Listens for COMPLAINT_CREATED events and automatically simulates a transaction
ring that cascades through the prediction models.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx
import yaml
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.core.security import create_access_token
from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.session import SessionLocal
from app.events.dispatcher import dispatcher
from app.events.topics import COMPLAINT_CREATED

logger = get_logger(__name__)
settings = get_settings()

def register_synthetic_handlers() -> None:
    async def on_complaint_created(payload: dict) -> None:
        complaint_id = payload["complaint_id"]
        logger.info("Automated demo simulation triggered for complaint", extra={"complaint_id": complaint_id})
        asyncio.create_task(_simulate_demo_transactions(complaint_id))
    
    dispatcher.subscribe(COMPLAINT_CREATED, on_complaint_created)


def _pick_seeded_chain(db: Session, hop_count: int) -> tuple[Account, list[Account]]:
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
            f"(found {len(all_accounts)}, need {needed})."
        )

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


async def _simulate_demo_transactions(complaint_id: str) -> None:
    # 1. Load the scenario YAML
    scenario_path = os.path.join("scripts", "demo_scenario_a_atm.yaml")
    if not os.path.exists(scenario_path):
        logger.error(f"Demo scenario file not found: {scenario_path}")
        return

    with open(scenario_path, "r") as f:
        scenario = yaml.safe_load(f)

    hops = scenario.get("hops", [])
    if not hops:
        return

    # 2. Pick a seeded chain & update complaint
    db = SessionLocal()
    try:
        complaint = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
        if not complaint:
            logger.error(f"Complaint {complaint_id} not found in DB")
            return

        # Try to pick seeded chain
        try:
            victim_account, mule_accounts = _pick_seeded_chain(db, len(hops))
        except ValueError as exc:
            logger.error(str(exc))
            return

        complaint.victim_account_id = victim_account.account_id
        complaint.location_lat = victim_account.branch_lat
        complaint.location_lon = victim_account.branch_lon
        complaint.is_demo_data = True
        
        db.flush()
        db.commit()
        db.refresh(complaint)
        amount = float(complaint.amount)
        
        # Extract fields to prevent DetachedInstanceError after session closes
        victim_hash = victim_account.account_hash
        mule_hashes = [m.account_hash for m in mule_accounts]
    except Exception as exc:
        logger.error(f"Error preparing complaint for simulation: {exc}")
        db.rollback()
        return
    finally:
        db.close()

    # 3. Simulate transactions via API
    # Mint a service token
    token = create_access_token(
        {"sub": "synthetic-harness", "role": "service", "jurisdiction_id": None, "bank_id": None},
        expires_minutes=60,
    )
    headers = {"Authorization": f"Bearer {token}"}

    from app.db.models.exit_channels import ExitChannel
    from app.db.models.enums import ExitChannelType
    
    cash_out = scenario.get("planted_cash_out", {})
    exit_channel_id = None
    if cash_out and "channel_type" in cash_out:
        db = SessionLocal()
        try:
            channel_type = ExitChannelType(cash_out["channel_type"])
            channel = db.query(ExitChannel).filter(ExitChannel.channel_type == channel_type).first()
            if channel:
                exit_channel_id = channel.channel_id
        finally:
            db.close()

    current_from = victim_hash
    occurred = datetime.now(timezone.utc) - timedelta(minutes=15)
    
    # Use 3x speed multiplier to make UI feel snappier but still show dripping
    speed = 3.0

    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        for i, (hop, mule_account) in enumerate(zip(hops, mule_accounts)):
            delay = hop.get("delay_s", 5) / speed
            await asyncio.sleep(delay)

            occurred += timedelta(seconds=hop.get("delay_s", 5) * 60)
            txn_amount = amount * hop.get("amount_pct", 1.0)

            txn_payload = {
                "complaint_id": complaint_id,
                "from_account_number": current_from,
                "to_account_number": mule_hashes[i],
                "amount": txn_amount,
                "channel": hop["channel"],
                "occurred_at": occurred.isoformat(),
            }
            if i == len(hops) - 1 and exit_channel_id:
                txn_payload["exit_channel_id"] = exit_channel_id

            try:
                resp = await client.post("/v1/transactions/ingest", json=txn_payload, headers=headers)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"Automated ingest failed for hop {i+1}: {e}")

            current_from = mule_hashes[i]

    logger.info("Automated demo simulation complete", extra={"complaint_id": complaint_id})
