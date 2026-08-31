"""
Synthetic data generator (docs/DEMO_ARCHITECTURE.md §2, "batch mode").

Everything this module writes is base/reference data seeded directly into
the database - not "the canonical demo scenario," which is a *complaint*
and must go through the real `POST /v1/complaints` endpoint
(app/synthetic/seed_demo_complaint.py does that separately). Batch-mode
reference data (accounts, exit channels, response units, historical
incidents, base transaction pool) has no equivalent public "same interface"
to go through yet - there is no `/v1/accounts` or `/v1/transactions/ingest`
endpoint in Phase 1 by design - so it is written directly, exactly the way
docs/DEMO_ARCHITECTURE.md §2 describes batch mode working.

Every row this module creates sets `is_synthetic=True` (or, for complaints,
`is_demo_data=True`) - never silently indistinguishable from real data
(docs/PRODUCT.md §5's non-negotiable rule).

Geography is grounded in real coordinates around four Tamil Nadu / South
Indian jurisdictions so H3 cells and distances are meaningful, even though
every entity inside them is fictional.
"""
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import h3
from faker import Faker
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models.accounts import Account, LinkedEntity
from app.db.models.complaints import Complaint
from app.db.models.enums import (
    ComplaintStatus,
    ExitChannelType,
    FraudType,
    InstitutionType,
    InterventionActionType,
    KycRiskTier,
    LinkedEntityType,
    OutcomeResult,
    ResponseUnitStatus,
    TransactionChannel,
    UserRole,
)
from app.db.models.exit_channels import ExitChannel
from app.db.models.jurisdictions import Bank, H3CellJurisdiction, Jurisdiction
from app.db.models.response_units import ResponseUnit
from app.db.models.transactions import Transaction
from app.db.models.users import User
from app.modules.complaints.schemas import ComplaintCreateRequest
from app.modules.complaints.service import DEFAULT_JURISDICTION_NAME, create_complaint

settings = get_settings()
fake = Faker("en_IN")

# Fictional bank names, deliberately not real institutions
# (docs/DEMO_ARCHITECTURE.md §2 / §7 - "clearly synthetic").
SYNTHETIC_BANK_NAMES = [
    ("Northbridge Bank", "NBRB"),
    ("Suryodaya Cooperative Bank", "SRDY"),
    ("Coastline Trust Bank", "CTLB"),
    ("Meridian Rural Bank", "MRDB"),
]

JURISDICTIONS = [
    ("Chennai Central", "Tamil Nadu", "Chennai", 13.0827, 80.2707),
    ("Coimbatore City", "Tamil Nadu", "Coimbatore", 11.0168, 76.9558),
    ("Bengaluru South", "Karnataka", "Bengaluru Urban", 12.9716, 77.5946),
    ("Hyderabad Central", "Telangana", "Hyderabad", 17.3850, 78.4867),
]

REAL_LOCATIONS = {
    "Chennai Central": [
        (13.0827, 80.2707, "Chennai Central Station"),
        (13.0418, 80.2341, "T. Nagar Hub"),
        (13.0850, 80.2101, "Anna Nagar"),
        (13.0012, 80.2565, "Adyar Bus Depot"),
        (13.0522, 80.2121, "Vadapalani"),
        (12.9750, 80.2210, "Velachery Bypass"),
        (13.0335, 80.2795, "Marina Beach Road"),
        (13.0186, 80.2230, "Guindy Industrial Estate"),
    ],
    "Coimbatore City": [
        (11.0168, 76.9558, "Gandhipuram"),
        (11.0045, 76.9616, "Town Hall"),
        (11.0287, 76.9362, "RS Puram"),
        (11.0315, 76.9660, "Cross Cut Road"),
        (11.0423, 76.9942, "Peelamedu Airport Road"),
        (10.9995, 76.9647, "Ukkadam Lake Road"),
        (11.0217, 77.0019, "Singanallur Checkpost"),
        (11.0123, 76.9745, "Race Course Road"),
    ],
    "Bengaluru South": [
        (12.9716, 77.5946, "Cubbon Park"),
        (12.9279, 77.5806, "Jayanagar 4th Block"),
        (12.9121, 77.6446, "HSR Layout Sector 1"),
        (12.9377, 77.6259, "Koramangala 80ft Road"),
        (12.9063, 77.5855, "JP Nagar Phase 2"),
        (12.9591, 77.5760, "Basavanagudi Gandhi Bazaar"),
        (12.9758, 77.6066, "MG Road Metro"),
        (12.9304, 77.5849, "South End Circle"),
    ],
    "Hyderabad Central": [
        (17.3850, 78.4867, "Charminar Monument"),
        (17.4399, 78.4983, "Secunderabad Junction"),
        (17.4239, 78.4738, "Hussain Sagar Lake"),
        (17.3949, 78.4730, "Abids Circle"),
        (17.4262, 78.4485, "Banjara Hills"),
        (17.4311, 78.4116, "Jubilee Hills"),
        (17.3616, 78.4747, "Falaknuma Road"),
        (17.4112, 78.4373, "Golconda Fort"),
    ],
}

H3_RESOLUTION = 8


def _jitter(center_lat: float, center_lon: float, spread_km: float = 8.0, jurisdiction_name: str = None) -> tuple[float, float, str]:
    if jurisdiction_name and jurisdiction_name in REAL_LOCATIONS:
        loc = random.choice(REAL_LOCATIONS[jurisdiction_name])
        return loc[0], loc[1], loc[2]
    d_lat = random.uniform(-spread_km, spread_km) / 111.0
    d_lon = random.uniform(-spread_km, spread_km) / (111.0 * 0.98)
    return center_lat + d_lat, center_lon + d_lon, "Unknown Location"


def seed_jurisdictions(db: Session) -> dict[str, str]:
    ids: dict[str, str] = {}
    for name, state, district, _, _ in JURISDICTIONS:
        existing = db.query(Jurisdiction).filter(Jurisdiction.name == name).first()
        if existing:
            ids[name] = existing.jurisdiction_id
            continue
        j = Jurisdiction(name=name, state=state, district=district)
        db.add(j)
        db.flush()
        ids[name] = j.jurisdiction_id

    # Fallback queue every unmatched complaint lands in
    # (app/modules/complaints/service.py DEFAULT_JURISDICTION_NAME).
    # [Fix found during the Docker verification gate] The returned `ids`
    # dict must include this entry whether the row was just created or
    # already existed from a prior run - it was previously only added on
    # the create branch, so a second invocation of this function silently
    # returned a dict missing the fallback queue's id.
    fallback = db.query(Jurisdiction).filter(Jurisdiction.name == DEFAULT_JURISDICTION_NAME).first()
    if not fallback:
        fallback = Jurisdiction(
            name=DEFAULT_JURISDICTION_NAME, state="Unassigned", district="Unassigned"
        )
        db.add(fallback)
        db.flush()
    ids[DEFAULT_JURISDICTION_NAME] = fallback.jurisdiction_id

    db.commit()
    return ids


def seed_banks(db: Session) -> list[str]:
    ids = []
    for name, prefix in SYNTHETIC_BANK_NAMES:
        existing = db.query(Bank).filter(Bank.name == name).first()
        if existing:
            ids.append(existing.bank_id)
            continue
        b = Bank(name=name, ifsc_prefix=prefix)
        db.add(b)
        db.flush()
        ids.append(b.bank_id)
    db.commit()
    return ids


DEMO_USER_PASSWORD = "TraceX@Demo123"


def seed_users(db: Session, jurisdiction_ids: dict[str, str], bank_ids: list[str]) -> list[User]:
    """Known demo credentials, clearly documented as such - never a pattern
    to reuse for anything beyond local development/demo. One investigator
    and one supervisor per real jurisdiction (excluding the fallback queue),
    plus one auditor, one admin, and one bank liaison overall."""
    created: list[User] = []
    real_jurisdictions = {k: v for k, v in jurisdiction_ids.items() if k != DEFAULT_JURISDICTION_NAME}

    def _get_or_create(email: str, role: UserRole, jurisdiction_id: Optional[str], bank_id: Optional[str]):
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return existing
        user = User(
            email=email,
            password_hash=hash_password(DEMO_USER_PASSWORD),
            role=role,
            jurisdiction_id=jurisdiction_id,
            bank_id=bank_id,
        )
        db.add(user)
        db.flush()
        return user

    for name, jurisdiction_id in real_jurisdictions.items():
        slug = name.lower().replace(" ", "_")
        created.append(
            _get_or_create(f"investigator.{slug}@tracex-demo.com", UserRole.investigator, jurisdiction_id, None)
        )
        created.append(
            _get_or_create(f"supervisor.{slug}@tracex-demo.com", UserRole.supervisor, jurisdiction_id, None)
        )

    created.append(_get_or_create("auditor@tracex-demo.com", UserRole.auditor, None, None))
    created.append(_get_or_create("admin@tracex-demo.com", UserRole.admin, None, None))
    created.append(
        _get_or_create("liaison.bank@tracex-demo.com", UserRole.bank_liaison, None, bank_ids[0] if bank_ids else None)
    )

    db.commit()
    return created


def seed_response_units(db: Session, jurisdiction_ids: dict[str, str]) -> None:
    for name, _, _, lat, lon in JURISDICTIONS:
        jurisdiction_id = jurisdiction_ids[name]
        if db.query(ResponseUnit).filter(ResponseUnit.jurisdiction_id == jurisdiction_id).first():
            continue
        for i in range(3):
            u_lat, u_lon, loc_name = _jitter(lat, lon, spread_km=6.0, jurisdiction_name=name)
            db.add(
                ResponseUnit(
                    jurisdiction_id=jurisdiction_id,
                    name=f"Patrol Unit at {loc_name}",
                    lat=u_lat,
                    lon=u_lon,
                    status=ResponseUnitStatus.available,
                    is_synthetic=True,
                )
            )
    db.commit()


def seed_exit_channels(db: Session, jurisdiction_ids: dict[str, str]) -> list[ExitChannel]:
    channels: list[ExitChannel] = []
    for name, _, _, lat, lon in JURISDICTIONS:
        jurisdiction_id = jurisdiction_ids[name]
        # Idempotency check: if any channel is already mapped to this jurisdiction, skip seeding it.
        existing_h3 = db.query(H3CellJurisdiction).filter(H3CellJurisdiction.jurisdiction_id == jurisdiction_id).first()
        if existing_h3 and db.query(ExitChannel).filter(ExitChannel.h3_cell == existing_h3.h3_cell).first():
            continue

        for i in range(6):  # atm_cash - the primary Scenario A channel type
            c_lat, c_lon, loc_name = _jitter(lat, lon, jurisdiction_name=name)
            cell = h3.latlng_to_cell(c_lat, c_lon, H3_RESOLUTION)
            channel = ExitChannel(
                channel_type=ExitChannelType.atm_cash,
                external_ref=f"ATM at {loc_name}",
                geo_lat=c_lat,
                geo_lon=c_lon,
                h3_cell=cell,
                channel_attributes={
                    "cash_limit": random.choice([10000, 20000, 40000]),
                    "cctv_flag": random.choice([True, True, False]),
                    "footfall_tier": random.choice(["low", "medium", "high"]),
                },
                intervention_action_type=InterventionActionType.physical_team_deployment,
                historical_incident_count=random.randint(0, 5),
                is_synthetic=True,
            )
            db.add(channel)
            db.flush()
            channels.append(channel)
            if not db.query(H3CellJurisdiction).filter(H3CellJurisdiction.h3_cell == cell).first():
                db.add(H3CellJurisdiction(h3_cell=cell, jurisdiction_id=jurisdiction_id))

        for i in range(2):  # crypto_p2p - Scenario B
            c_lat, c_lon, loc_name = _jitter(lat, lon, jurisdiction_name=name)
            cell = h3.latlng_to_cell(c_lat, c_lon, H3_RESOLUTION)
            channel = ExitChannel(
                channel_type=ExitChannelType.crypto_p2p,
                external_ref=f"Crypto Exchange near {loc_name}",
                geo_lat=c_lat,
                geo_lon=c_lon,
                h3_cell=cell,
                channel_attributes={
                    "exchange_name": f"Fictional Exchange {chr(65 + i)}",
                    "kyc_tier": random.choice(["low", "medium", "high"]),
                },
                intervention_action_type=InterventionActionType.exchange_freeze_request,
                is_synthetic=True,
            )
            db.add(channel)
            channels.append(channel)

        for i in range(2):  # ecommerce_merchant - Scenario C
            c_lat, c_lon, loc_name = _jitter(lat, lon, jurisdiction_name=name)
            cell = h3.latlng_to_cell(c_lat, c_lon, H3_RESOLUTION)
            channel = ExitChannel(
                channel_type=ExitChannelType.ecommerce_merchant,
                external_ref=f"Warehouse at {loc_name}",
                geo_lat=c_lat,
                geo_lon=c_lon,
                h3_cell=cell,
                channel_attributes={
                    "merchant_name": f"Fictional Marketplace {chr(65 + i)}",
                    "sku_category": random.choice(["electronics", "gift_cards", "jewellery"]),
                },
                intervention_action_type=InterventionActionType.merchant_hold_request,
                is_synthetic=True,
            )
            db.add(channel)
            channels.append(channel)

    db.commit()
    return channels


def _make_synthetic_account(db: Session, bank_ids: list[str], jurisdiction_center: tuple[float, float], jurisdiction_name: str) -> Account:
    lat, lon, _ = _jitter(jurisdiction_center[0], jurisdiction_center[1], jurisdiction_name=jurisdiction_name)
    account = Account(
        account_hash=fake.sha256(),
        bank_id=random.choice(bank_ids) if bank_ids else None,
        branch_lat=lat,
        branch_lon=lon,
        kyc_risk_tier=random.choice(list(KycRiskTier)),
        opened_at=fake.date_time_between(start_date="-3y", end_date="-1m", tzinfo=timezone.utc),
        is_synthetic=True,
    )
    db.add(account)
    db.flush()
    return account


def _attach_synthetic_linked_entities(db: Session, account: Account) -> None:
    db.add(LinkedEntity(account_id=account.account_id, entity_type=LinkedEntityType.device, entity_hash=fake.sha256()))
    db.add(LinkedEntity(account_id=account.account_id, entity_type=LinkedEntityType.phone, entity_hash=fake.sha256()))
    db.add(LinkedEntity(account_id=account.account_id, entity_type=LinkedEntityType.ip, entity_hash=fake.sha256()))
    db.add(LinkedEntity(account_id=account.account_id, entity_type=LinkedEntityType.vpa, entity_hash=fake.sha256()))


def seed_mule_rings(
    db: Session, bank_ids: list[str], jurisdiction_ids: dict[str, str], ring_count: int = 20
) -> list[dict]:
    """Ground-truth mule rings (docs/AI_ML_ARCHITECTURE.md §2's "ground
    truth retained" design): each ring is a victim + a chain of 2-4 mule
    accounts, all tagged with the same `ring_id`, plus a synthetic
    transaction chain between them with realistic hop timing. Ring
    membership is asserted here, not detected - Phase 2's Ring Detector is
    evaluated against exactly this ground truth later.

    [Phase 2D addition] The chain's *final* hop also plants a genuine
    exit-channel + exit-timing ground truth, the same way ring membership
    above is ground truth: not inferred, not labeled after the fact, but
    asserted directly by the generator as the scenario's own known outcome.
    Concretely, the last Transaction in the chain gets a real
    `exit_channel_id`, chosen from this ring's own jurisdiction's already-
    seeded ExitChannel rows (seed_exit_channels) - exactly mirroring how a
    real mule chain's last hop is the one that actually cashes out
    somewhere. This makes two things independently queryable, without any
    side table, the same way accounts.ring_id already is the ground truth
    for Ring Detection:
      - "true" exit channel: the exit_channel_id on the ring's own last
        Transaction (by hop_index)
      - "true" time-to-exit: that Transaction's occurred_at minus the
        first Transaction's occurred_at
    Backward compatible: if no ExitChannel rows exist yet for this
    jurisdiction (e.g. a caller that seeds mule rings without first calling
    seed_exit_channels, as some tests deliberately do), the last
    transaction is left with no exit_channel_id, exactly as before this
    change - never an error, never a fabricated channel."""
    rings = []
    jurisdiction_centers = {
        name: (lat, lon) for name, _, _, lat, lon in JURISDICTIONS
    }
    for _ in range(ring_count):
        jurisdiction_name = random.choice(list(jurisdiction_centers.keys()))
        center = jurisdiction_centers[jurisdiction_name]
        ring_id = fake.uuid4()

        victim = _make_synthetic_account(db, bank_ids, center, jurisdiction_name)
        _attach_synthetic_linked_entities(db, victim)
        victim.ring_id = ring_id

        chain_length = random.randint(2, 4)
        mules = []
        for _ in range(chain_length):
            mule = _make_synthetic_account(db, bank_ids, center, jurisdiction_name)
            _attach_synthetic_linked_entities(db, mule)
            mule.ring_id = ring_id
            mules.append(mule)

        chain = [victim] + mules
        first_occurred_at = None
        last_txn: Optional[Transaction] = None
        occurred = datetime.now(timezone.utc) - timedelta(days=random.randint(5, 120))
        for hop_index, (src, dst) in enumerate(zip(chain, chain[1:]), start=1):
            occurred += timedelta(minutes=random.randint(4, 25))
            if first_occurred_at is None:
                first_occurred_at = occurred
            amount = Decimal(random.randint(15000, 200000)) * Decimal(str(round(0.85 ** hop_index, 2)))
            last_txn = Transaction(
                from_account_id=src.account_id,
                to_account_id=dst.account_id,
                amount=amount,
                channel=random.choice([TransactionChannel.upi, TransactionChannel.imps]),
                hop_index=hop_index,
                occurred_at=occurred,
                is_synthetic=True,
            )
            db.add(last_txn)

        true_exit_channel_id = None
        # Find exit channels seeded for this jurisdiction via the H3CellJurisdiction mapping.
        jurisdiction_id = jurisdiction_ids.get(jurisdiction_name)
        jurisdiction_channels = []
        if jurisdiction_id:
            h3_cells = [row[0] for row in db.query(H3CellJurisdiction.h3_cell).filter(H3CellJurisdiction.jurisdiction_id == jurisdiction_id).all()]
            if h3_cells:
                jurisdiction_channels = db.query(ExitChannel).filter(ExitChannel.h3_cell.in_(h3_cells)).all()
        if jurisdiction_channels and last_txn is not None:
            true_exit_channel = random.choice(jurisdiction_channels)
            last_txn.exit_channel_id = true_exit_channel.channel_id
            true_exit_channel_id = true_exit_channel.channel_id

        rings.append(
            {
                "ring_id": ring_id,
                "jurisdiction": jurisdiction_name,
                "victim_account_id": victim.account_id,
                "mule_account_ids": [m.account_id for m in mules],
                "true_exit_channel_id": true_exit_channel_id,
                "ring_start_at": first_occurred_at.isoformat() if first_occurred_at else None,
                "true_exit_occurred_at": occurred.isoformat(),
            }
        )

    db.commit()
    return rings


def seed_historical_incidents(db: Session, jurisdiction_names: list[str], count: int = 10) -> None:
    """Closed prior cases, created through the same `create_complaint`
    service function every real submission uses (docs/DEMO_ARCHITECTURE.md
    §2's methodology point), then backdated/closed to represent already-
    resolved history - the one deliberate, documented exception to "insert
    directly," because a complaint's creation path is the one interface
    this phase's brief specifically requires reuse of."""
    fraud_types = list(FraudType)
    institution_types = list(InstitutionType)
    outcomes = list(OutcomeResult)

    for _ in range(count):
        jurisdiction_hint = random.choice(jurisdiction_names)
        request = ComplaintCreateRequest(
            incident_datetime=fake.date_time_between(start_date="-180d", end_date="-2d", tzinfo=timezone.utc),
            fraud_type=random.choice(fraud_types),
            amount=Decimal(random.randint(5000, 500000)),
            location_text=f"{fake.street_name()}, {jurisdiction_hint}",
            location_lat=None,
            location_lon=None,
            institution_name=random.choice(SYNTHETIC_BANK_NAMES)[0],
            institution_type=random.choice(institution_types),
            transaction_reference=fake.bothify(text="TXN########"),
            victim_account_number=fake.bban(),
            victim_phone=fake.phone_number(),
            victim_email=fake.email(),
            description=f"Synthetic historical case: {fake.sentence(nb_words=12)}",
            evidence_notes=[fake.sentence(nb_words=6)],
            jurisdiction_hint=jurisdiction_hint,
            idempotency_key=None,
        )
        complaint, _ = create_complaint(db, request, is_demo_data=True)
        complaint.status = ComplaintStatus.closed
        complaint.filed_at = request.incident_datetime + timedelta(hours=random.randint(1, 72))
        db.add(complaint)
    db.commit()


def run_full_seed(db: Session) -> dict:
    # [Bug found and fixed during the Docker infrastructure verification gate]
    # This used to call random.seed(settings.synthetic_random_seed) /
    # Faker.seed(...) on every invocation. That makes sense for a single
    # isolated run, but it actively breaks the documented behavior that
    # mule rings and historical incidents are additive across repeated
    # invocations (seed_mule_rings/seed_historical_incidents have no
    # existence-check, unlike the reference-data seeders below, precisely
    # so re-running the script adds new synthetic cases). Re-pinning the
    # RNG to the same fixed value every call instead made every account's
    # `fake.sha256()` hash byte-for-byte identical across separate runs,
    # which is invisible on an empty database but throws a
    # UniqueViolation on `accounts.account_hash` the moment a second run
    # happens against a database that already has data from a first run
    # or from the test suite (which calls run_full_seed internally) - this
    # is exactly the sequence the Docker verification gate exercised
    # (run the test suite, then re-seed) and exactly how it surfaced.
    # settings.synthetic_random_seed is left in Settings as a documented,
    # honest no-op for now rather than silently deleted - reintroducing
    # per-run (not cross-run) determinism, e.g. seeding once at process
    # start rather than per call, is a reasonable future improvement if
    # reproducible-per-run generation is ever actually needed.
    jurisdiction_ids = seed_jurisdictions(db)
    bank_ids = seed_banks(db)
    users = seed_users(db, jurisdiction_ids, bank_ids)
    seed_response_units(db, jurisdiction_ids)
    channels = seed_exit_channels(db, jurisdiction_ids)
    rings = seed_mule_rings(db, bank_ids, jurisdiction_ids)
    seed_historical_incidents(
        db, [name for name in jurisdiction_ids if name != DEFAULT_JURISDICTION_NAME]
    )

    return {
        "jurisdictions": len(jurisdiction_ids),
        "banks": len(bank_ids),
        "users": len(users),
        "exit_channels": len(channels),
        "mule_rings": len(rings),
    }
