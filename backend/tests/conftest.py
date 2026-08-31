"""
Test fixtures.

Runs against a single process-wide in-memory SQLite database rather than
PostgreSQL+PostGIS (the documented, canonical target - docs/ARCHITECTURE.md
§8). This is a deliberate, disclosed deviation: this backend was built and
must be verifiable in an environment without Docker installed, and the
schema uses only cross-dialect types for exactly this reason (see
app/db/session.py's module docstring). Every test in this suite exercises
business logic (validation, ID generation, RBAC, hashing, events,
WebSocket delivery), none of it PostGIS-specific geospatial querying -
Phase 1 does none of that yet - so SQLite is a faithful stand-in here.
Running the same suite against the docker-compose Postgres service is a
one-line DATABASE_URL change (see backend/README.md).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-deployment")
os.environ.setdefault("PII_HASH_PEPPER", "test-pepper-not-for-deployment")
os.environ.setdefault("WEBHOOK_HMAC_SECRET", "test-webhook-secret-not-for-deployment")
os.environ.setdefault("ENVIRONMENT", "test")

# Phase 2B foundation repair: ring-detection tests were found writing real
# :Ring/MEMBER_OF_RING/Account/Complaint data into the shared development
# Neo4j instance (bolt://localhost:7687) because that graph, unlike
# Postgres, is never reset between tests, and ring detection runs
# whole-graph community detection - a single test's own cleanup cannot
# scope away the *other* communities that run touches. The test suite must
# default to the disposable instance defined in docker-compose.yml's
# `neo4j-test` service instead - started explicitly with
# `docker compose --profile test up -d neo4j-test`, never by plain
# `docker compose up`. Overridable only for exceptional, deliberate use;
# `_assert_test_neo4j_is_isolated` below is the actual enforcement, not
# this default alone.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7688")

import pytest
from starlette.testclient import TestClient

from app.core.security import create_access_token, hash_pii
from app.db import models  # noqa: F401 - registers every table on Base.metadata
from app.db.models.enums import UserRole
from app.db.models.jurisdictions import Jurisdiction
from app.db.session import Base, SessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
def _clean_database():
    """Full reset before every test - cheap on an in-memory SQLite DB and
    guarantees no cross-test state leakage (e.g. audit chain sequence
    numbers, idempotency keys)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def jurisdiction_a(db):
    j = Jurisdiction(name="Chennai Central", state="Tamil Nadu", district="Chennai")
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


@pytest.fixture
def jurisdiction_b(db):
    j = Jurisdiction(name="Coimbatore City", state="Tamil Nadu", district="Coimbatore")
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


def make_token(role: UserRole, jurisdiction_id: str | None = None, sub: str = "test-user") -> str:
    return create_access_token(
        {"sub": sub, "role": role.value, "jurisdiction_id": jurisdiction_id, "bank_id": None}
    )


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def valid_complaint_payload(**overrides) -> dict:
    payload = {
        "incident_datetime": "2026-08-20T10:15:00+00:00",
        "fraud_type": "upi_fraud",
        "amount": "200000.00",
        "location_text": "T. Nagar, Chennai",
        "location_lat": 13.0418,
        "location_lon": 80.2341,
        "institution_name": "Northbridge Bank",
        "institution_type": "bank",
        "transaction_reference": "TXN00000001",
        "victim_account_number": "1234567890",
        "victim_phone": "+91-90000-00001",
        "victim_email": "citizen@example.com",
        "description": "Received a phishing call and lost money via UPI transfer to an unknown account.",
        "evidence_notes": ["Screenshot of the debit SMS"],
        "jurisdiction_hint": "Chennai",
    }
    payload.update(overrides)
    return payload


# --- Phase 2A: transaction ingestion helpers -------------------------------


def service_token() -> str:
    return make_token(UserRole.service, sub="synthetic-harness")


def valid_transaction_payload(**overrides) -> dict:
    payload = {
        "complaint_id": "REPLACE_ME",
        "from_account_number": "FROM-ACCT-0001",
        "to_account_number": "TO-ACCT-0001",
        "amount": "50000.00",
        "channel": "upi",
        "occurred_at": "2026-08-26T10:20:00+00:00",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def submitted_complaint(client, jurisdiction_a) -> dict:
    """A real complaint, created through the public API, for transaction
    tests that need a genuine complaint_id/victim_account_id to reference."""
    response = client.post(
        "/v1/complaints",
        json=valid_complaint_payload(jurisdiction_hint="Chennai", victim_account_number="VICTIM-0001"),
    )
    assert response.status_code == 201
    return response.json()


# --- Phase 2A: Neo4j graph test isolation -----------------------------------
# The graph lives in a real, shared Neo4j instance (not reset per test like
# the relational DB) - every graph test tags its own account/complaint/
# channel identifiers with a unique per-test prefix, and this autouse
# fixture deletes exactly those tagged nodes afterward. Tests that need it
# request `graph_prefix`; tests that don't are unaffected (the cleanup query
# only matches nodes carrying that specific prefix).


# --- Phase 2B: disposable Neo4j test instance guard ---------------------
# Tests must never write ring-detection (or any) artifacts into the shared
# development Neo4j instance (bolt://localhost:7687 / bolt://neo4j:7687,
# the docker-compose `neo4j` service). This is enforced, not just
# documented by the NEO4J_URI default above: `_assert_test_neo4j_is_isolated`
# fails the entire session loudly if the resolved URI is ever the dev/prod
# one, and the disposable instance is wiped clean once per session since
# the guard has already proven it isn't shared/real data.

_DEV_NEO4J_HOSTS_PORTS = {("localhost", 7687), ("127.0.0.1", 7687), ("neo4j", 7687)}


def _assert_test_neo4j_is_isolated(uri: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(uri)
    if (parsed.hostname, parsed.port) in _DEV_NEO4J_HOSTS_PORTS:
        raise RuntimeError(
            f"Refusing to run tests against {uri} - this is the shared development/production "
            "Neo4j instance. Point NEO4J_URI at a disposable instance instead (see "
            "docker-compose.yml's neo4j-test service, started with "
            "`docker compose --profile test up -d neo4j-test`), so test runs can never write "
            "Ring/Account/Complaint test artifacts into real graph data."
        )


@pytest.fixture(scope="session", autouse=True)
def _guard_and_reset_test_neo4j():
    """Runs once per test session, before any test body. Aborts the whole
    session immediately (not just one test) if NEO4J_URI ever resolves to
    the shared dev/prod instance - the regression check for the Aug 26
    test-leakage incident, where whole-graph ring detection run against a
    shared Neo4j left 47 orphaned :Ring nodes behind. See
    tests/test_neo4j_test_isolation.py for the Docker-independent unit
    tests exercising the guard logic itself."""
    from app.core.config import get_settings
    from app.db.neo4j_client import get_driver, initialize_schema

    _assert_test_neo4j_is_isolated(get_settings().neo4j_uri)

    driver = get_driver()
    if driver is not None:
        try:
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
            # A fresh disposable instance has never had docs/DATA_MODEL.md
            # §3's uniqueness constraints applied (scripts/init_neo4j.py /
            # manual setup only ever did this on the old shared instance) -
            # without this, test_neo4j_constraints_exist fails not because
            # of a real regression but because nothing ever bootstrapped
            # this container's schema. initialize_schema() is the same
            # idempotent (`IF NOT EXISTS`) call production/dev setup uses.
            initialize_schema()
        except Exception:
            pass  # disposable instance unreachable - individual tests' own
            # check_connectivity()-gated skipif markers handle this case
    yield


@pytest.fixture
def graph_prefix() -> str:
    import uuid

    return f"test-{uuid.uuid4().hex[:10]}"


# Every test that ingests a transaction through the real HTTP endpoint
# writes to the real, shared Neo4j instance unconditionally (the router
# does this on every successful ingest, docs/API_CONTRACT.md §1b) - even
# tests that only assert Postgres-derived values. Left uncleaned, repeated
# suite runs would grow this shared instance unboundedly with the same
# fixed literal account numbers several test files reuse. This autouse,
# session-wide fixture removes exactly those known literals after every
# test - harmless (zero rows matched) for tests that never touched Neo4j.
_KNOWN_TEST_ACCOUNT_NUMBERS = (
    [
        "FROM-ACCT-0001", "TO-ACCT-0001",  # valid_transaction_payload() defaults
        "VICTIM-0001",  # submitted_complaint fixture's victim account
        "9999000011", "9999000022", "RAW-FROM-ACCT", "RAW-TO-ACCT",
        "NEW-MULE-0001", "NEW-MULE-0002", "DEVICE-TEST-ACCT",
        "MULE-CHAIN-1", "MULE-CHAIN-2", "MULE-CHAIN-3",
        "CHAIN-MULE-1", "CHAIN-MULE-2", "NEVER-SEEN-BEFORE",
        "ACCOUNT-A", "ACCOUNT-B",
    ]
    + [f"DEEP-MULE-{i}" for i in range(12)]
)


@pytest.fixture(autouse=True)
def _cleanup_shared_neo4j_test_accounts():
    yield
    from app.db.neo4j_client import get_driver

    driver = get_driver()
    if driver is None:
        return
    hashes = [hash_pii(n) for n in _KNOWN_TEST_ACCOUNT_NUMBERS]
    try:
        with driver.session() as session:
            session.run("MATCH (n:Account) WHERE n.account_hash IN $hashes DETACH DELETE n", hashes=hashes)
    except Exception:
        pass  # best-effort cleanup only - never fail a test on teardown


@pytest.fixture
def _cleanup_graph_nodes(graph_prefix):
    yield graph_prefix
    from app.db.neo4j_client import get_driver

    driver = get_driver()
    if driver is None:
        return
    try:
        with driver.session() as session:
            session.run(
                """
                MATCH (n)
                WHERE any(prop IN ['complaint_id','account_hash','device_hash','phone_hash',
                                    'ip_hash','vpa_hash','channel_id'] WHERE
                          n[prop] IS NOT NULL AND n[prop] STARTS WITH $prefix)
                DETACH DELETE n
                """,
                prefix=graph_prefix,
            )
    except Exception:
        pass  # best-effort cleanup only - never fail a test on teardown
