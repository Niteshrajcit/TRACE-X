# TRACE-X — Phase 0/1/2A Foundation

Predictive Cybercrime Cash-Withdrawal Intelligence Platform · SIH 26184.

**PHASE 0 — FOUNDATION: COMPLETE** · **PHASE 1 — LIVE COMPLAINT PIPELINE: COMPLETE** · **PHASE 2A — TRANSACTION INGESTION + GRAPH BUILDER: COMPLETE**

See `docs/` for the full locked architecture, product experience, and demo design; see `docs/IMPLEMENTATION_PLAN.md`'s "Build status" and "Technical debt" sections for exactly what's done, what's deliberately deferred, and what Phase 2B starts with. This README covers only what's needed to run what's built so far.

**What works right now, verified against the real Docker Compose stack** (PostgreSQL+PostGIS, Neo4j, FastAPI, React/TS — not just the SQLite fallback): a citizen submits a complaint through `/report`, it's validated, hashed, persisted to real PostgreSQL, and given a `TX-YYYY-XXXXXXXX` incident reference; an investigator watching `/console` (WebSocket-connected, no polling) sees the new incident appear live with zero refresh, opens it, and sees the stored complaint and its pipeline status. Every state-changing action writes a hash-chained audit event, verified intact against real Postgres.

As of Phase 2A, a `service`-role caller (`scripts/mint_service_token.py`) can `POST /v1/transactions/ingest` a mule-chain transaction — hashing accounts/device/IP/phone/VPA server-side, computing `hop_index` from Postgres alone (bounded, never client-supplied), and writing a derived subgraph to Neo4j (Account/Device/Phone/IP/VPA/ExitChannel nodes, `TRANSFERRED_TO`/`HAS_*`/`EXITED_VIA` relationships). The graph is fully rebuildable from Postgres via `scripts/rebuild_neo4j_graph.py` — verified by wiping Neo4j and reproducing an identical structure. 99/99 automated tests pass against real Postgres+Neo4j. No ring detection, exit-channel prediction, risk field, or optimizer is implemented yet — see `docs/IMPLEMENTATION_PLAN.md` for what's next.

---

## Option A — Docker Compose (the documented, canonical stack — verified)

Brings up PostgreSQL+PostGIS, Neo4j, the backend, and the frontend dev server.

```bash
docker compose up --build
```

Then, in a separate terminal, apply migrations (the backend container already runs `alembic upgrade head` on boot via `backend/docker-entrypoint.sh`, so this is only needed if you restart just the backend) and seed synthetic base data:

```bash
docker compose exec backend python scripts/seed_synthetic.py
```

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Option B — Local, without Docker (SQLite fallback)

Option A above is the verified, canonical path — used for the actual Phase 0/1 closure verification against real PostgreSQL+PostGIS and Neo4j. This option remains documented and supported for Docker-less environments (CI runners without Docker, quick local iteration): see `backend/app/db/session.py` and `backend/tests/conftest.py` for the deliberate, disclosed SQLite fallback this enables. It's a genuine fallback, not a stand-in pretending to be the real thing — the app itself is unaware which database it's talking to.

**Backend**

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt

# Seed a local SQLite dev database with jurisdictions, banks, demo users,
# exit channels, response units, and synthetic mule rings:
python scripts/seed_synthetic.py

# Run the API (reads DATABASE_URL from .env if present, else defaults to
# sqlite:///./tracex_dev.db):
uvicorn app.main:app --reload
```

**Frontend** (separate terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173/report (citizen) and http://localhost:5173/login (investigator) in two different browser windows/tabs.

**Demo investigator credentials** (seeded by `scripts/seed_synthetic.py`, see `backend/app/synthetic/generator.py`):

| Email | Password | Role | Jurisdiction |
|---|---|---|---|
| `investigator.chennai_central@tracex-demo.com` | `TraceX@Demo123` | investigator | Chennai Central |
| `supervisor.chennai_central@tracex-demo.com` | `TraceX@Demo123` | supervisor | Chennai Central |
| `auditor@tracex-demo.com` | `TraceX@Demo123` | auditor | all jurisdictions |
| `admin@tracex-demo.com` | `TraceX@Demo123` | admin | all jurisdictions |

(Other jurisdictions - Coimbatore City, Bengaluru South, Hyderabad Central - have their own `investigator.<slug>@tracex-demo.com` / `supervisor.<slug>@tracex-demo.com` accounts, same password.)

**Seed the canonical demo complaint through the real API** (not inserted directly - see `docs/DEMO_ARCHITECTURE.md` §3):

```bash
cd backend
python scripts/seed_demo_complaint.py --base-url http://localhost:8000
```

## Running the backend test suite

```bash
cd backend
./.venv/Scripts/python -m pytest -q
```

53 tests: complaint validation, incident ID generation, persistence, PII hashing/provenance, idempotency, RBAC/auth, the event dispatcher, live WebSocket delivery (including cross-jurisdiction isolation), the hash-chained audit log, API contract/schema checks, the synthetic generator, and one full end-to-end test (`tests/test_e2e_complaint_flow.py`) that walks submit → DB row → event → live investigator delivery in a single pass.

Runs against an in-memory SQLite database by design (`backend/tests/conftest.py` explains why - no Docker/Postgres dependency to run the suite). Pointing `DATABASE_URL` at the docker-compose Postgres service before running `pytest` exercises the identical suite against the canonical database.

## Running database migrations directly

```bash
cd backend
alembic upgrade head      # apply
alembic downgrade base    # roll back everything (destructive - local/dev only)
alembic revision --autogenerate -m "description"   # after changing a model
```

## Frontend build/typecheck

```bash
cd frontend
npm run typecheck
npm run build
```

---

## Repository layout

```
docs/                          Locked architecture, product experience, demo design (see PRODUCT.md first)
backend/
  app/
    core/                      config, logging, security (JWT/hashing)
    db/                        SQLAlchemy models (full docs/DATA_MODEL.md schema) + session + Neo4j client
    events/                    in-process async event dispatcher (docs/ARCHITECTURE.md §4)
    ws/                        WebSocket connection manager + route
    auth/                      login endpoint, JWT dependencies, RBAC
    audit/                     hash-chained audit log (docs/SECURITY_AND_GOVERNANCE.md §4)
    modules/complaints/        the Phase 1 vertical slice: schemas, service, router
    synthetic/                 batch-mode synthetic data generator (docs/DEMO_ARCHITECTURE.md §2)
    health/                    /health endpoint
  alembic/                     migrations (autogenerated from app/db/models)
  scripts/                     seed_synthetic.py, seed_demo_complaint.py, init_neo4j.py
  tests/                       53 tests, see above
frontend/
  src/
    api/client.ts               typed fetch wrapper
    types/domain.ts              TS types mirrored from the backend Pydantic schemas
    hooks/useComplaintFeed.ts    the WebSocket live-feed hook
    context/AuthContext.tsx      token/role/jurisdiction storage
    pages/                       ComplaintPortal, Login, CommandCenter, IncidentDetail
docker-compose.yml              Postgres+PostGIS, Neo4j, backend, frontend (no Redis - see docs/ARCHITECTURE.md §4)
```
