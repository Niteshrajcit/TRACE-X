# TRACE-X — Implementation Plan

> Depends on: all preceding docs. This is where they become sequenced, buildable work. Expands PROJECT.md §14's roadmap into concrete tasks, owners-by-skill, and exit criteria.

---

## Build status (updated 2026-08-26 — final Phase 1 engineering closure)

### PHASE 0 — FOUNDATION: COMPLETE
### PHASE 1 — LIVE COMPLAINT PIPELINE: COMPLETE / 100% CLOSED

Verified against the **real Docker Compose stack** — PostgreSQL+PostGIS, Neo4j, FastAPI backend, React/TS frontend — through two verification passes. The first pass (migrations, seed, live complaint→WebSocket flow, 53 tests, frontend build) is recorded further down this file's history. This second, closing pass resolved every gap that first pass surfaced:

- **PostGIS is now self-provisioning.** The initial Alembic migration itself runs `CREATE EXTENSION IF NOT EXISTS postgis` (dialect-guarded, skipped on the SQLite fallback) — it no longer depends on the `postgis/postgis` Docker image's one-time init behavior. Verified against a database dropped and recreated from nothing: empty database → `alembic upgrade head` → PostGIS present with zero manual steps → backend starts and reports both dependencies up.
- **Neo4j constraints/indexes are now applied**, not just reachable. `scripts/init_neo4j.py` run against the live container; all 5 constraints (`complaint_id_unique`, `account_hash_unique`, `device_hash_unique`, `phone_hash_unique`, `exit_channel_id_unique`) and the `exit_channel_h3_cell` index confirmed `ONLINE` via `SHOW CONSTRAINTS`/`SHOW INDEXES`, and confirmed idempotent (safe to re-run).
- **Full clean-environment reproducibility verified**: `docker compose down -v` (containers, volumes, network all removed) → `docker compose up -d --build` from nothing → all 4 services `healthy` → migrations + PostGIS + Neo4j constraints + seed + frontend build + the full 53-test suite + a live two-browser-tab complaint→WebSocket test, all re-confirmed with zero manual workarounds. Nothing about this stack depends on state left over from an earlier run.
- **The `POST /v1/transactions/ingest` contract is frozen** (API_CONTRACT.md §1a) — cross-checked against DATA_MODEL.md, AI_ML_ARCHITECTURE.md, and DEMO_ARCHITECTURE.md, with four real ambiguities resolved in the docs (raw-vs-hashed account fields, server-computed `hop_index`, an added `idempotency_key`, and a newly-defined `service` JWT role — see SECURITY_AND_GOVERNANCE.md §3) and one cross-doc inconsistency fixed (DEMO_ARCHITECTURE.md's example scenario YAML was missing the required `channel` field). Not implemented — this is a documentation freeze so Phase 2 starts from a contract, not a guess.

**How this maps onto the phase checklists below**: the phases as actually executed (directed incrementally, turn by turn) grouped work differently than the original Phase 0–6 breakdown that follows. "Phase 0" above = the original **Phase 0** checklist below, in full. "Phase 1" above = original **Phase 1**'s intake + event-dispatcher items, *plus* the WebSocket gateway and RBAC/jurisdiction-scoping items originally scoped under **Phase 3** — pulled forward deliberately, because proving a live, authenticated, jurisdiction-scoped complaint→incident delivery end-to-end was the actual point of the first vertical slice, and it made no sense to build an unauthenticated WebSocket first and retrofit auth later. Transaction ingestion and the Graph Builder — the rest of original Phase 1's scope — were **not** built and remain exactly where Phase 2 starts (see item 7, "Exact starting point for Phase 2," in the closure report). The checklists below are left as originally written and checked off item-by-item rather than renumbered, so the history of what was planned vs. what shipped stays legible.

---

## Phase 0 — Environment & contracts (prerequisite, ~day 1)

- [x] Docker Compose skeleton: Postgres+PostGIS and Neo4j containers boot and are reachable (**[Revised after product review]** no Redis container — see ARCHITECTURE.md §4, PRODUCT_EXPERIENCE.md §8.1). Verified against the real stack: all 4 services (postgres, neo4j, backend, frontend) report `healthy`, on one Docker network, service-name DNS resolution confirmed from inside the backend container.
- [x] Postgres schema migration from DATA_MODEL.md §2 applied, including the `exit_channels` and `h3_cell_jurisdiction` tables. Verified: `alembic upgrade head` runs automatically on container start against real PostgreSQL (`Context impl PostgresqlImpl`), all 17 tables present in `\dt`.
- [x] Neo4j constraints/indexes from DATA_MODEL.md §3 applied (`:ExitChannel` label plus `:Complaint`/`:Account`/`:Device`/`:Phone` uniqueness constraints — `EXITED_VIA`/`HISTORICALLY_EXITED_VIA` are relationship types, not constrained separately). `scripts/init_neo4j.py` run and verified against the live container, confirmed idempotent. No graph *data* has been written yet — that's still exactly Phase 2 (the Graph Builder).
- [x] FastAPI skeleton with the module boundaries from ARCHITECTURE.md §3, auth middleware stubbed, in-process event dispatcher scaffolded (ARCHITECTURE.md §4)
- [x] OpenAPI spec generated matching API_CONTRACT.md — this is the contract everything else builds against. Verified via `/openapi.json` exposing exactly the Phase 1 endpoint set.

**Exit criteria**: `docker-compose up` produces a backend that answers `GET /health` and has empty-but-correct schemas in both databases. **Met** — `GET /health` returns `{"postgres":"up","neo4j":"up"}` against the real containers.

## Phase 1 — Foundation (data + intake)

- [x] Synthetic data harness: batch mode (historical cases, ATM/branch/exchange/merchant exit-channel registry — real public data where it exists, base accounts) — DEMO_ARCHITECTURE.md §2. Verified against real Postgres: 5 jurisdictions, 4 banks, 11 users, 40 exit channels, 6 mule rings, 10 historical complaints, re-run twice consecutively with no collisions after the determinism bug fix (see Technical debt).
- [x] Complaint intake endpoint + PII hashing at the boundary — API_CONTRACT.md §1, SECURITY_AND_GOVERNANCE.md §2. Verified end-to-end against the real Dockerized backend via direct submission and via the live browser flow.
- [ ] Transaction ingestion endpoint, writes to Postgres, triggers Graph Builder write to Neo4j — **not built; contract now frozen** (API_CONTRACT.md §1a). This is the literal starting point of Phase 2.
- [x] In-process event dispatcher wired for `complaint.created` (ARCHITECTURE.md §4). `intelligence.started` / `transaction.ingested` and the rest of the canonical sequence are not wired — there is no pipeline yet to emit them; they activate as each Phase 2+ stage is built.
- [x] *(Pulled forward from Phase 3, see "Build status" above)* WebSocket gateway with jurisdiction-scoped channels, JWT auth, RBAC-scoped REST endpoints. Verified: a live two-browser-tab test against the Dockerized frontend — citizen submits on `/report`, an already-open, never-refreshed investigator Command Center on `/console` receives the new incident instantly via WebSocket; cross-jurisdiction isolation and unauthorized-access rejection both covered by the automated suite.

**Exit criteria** (as originally written, spanning what's now Phase 1 + the start of Phase 2): posting a complaint and a chain of transactions through the API produces correct rows in Postgres *and* a correct subgraph in Neo4j, verified by an integration test. **Partially met**: the complaint half is done and verified against real Postgres; the transaction-chain-into-Neo4j half is Phase 2 work, not yet started.

## Phase 2 — Intelligence pipeline

**[Phase 2A — COMPLETE, verified against the real Docker stack, 2026-08-26]** `POST /v1/transactions/ingest`, the `service` JWT role, transaction idempotency, and the Graph Builder (bounded traversal + server-computed `hop_index`) are built and verified — see this session's Phase 2A report for the full detail (files changed, live verification trail, tests). Ring Detector/Louvain and everything below it in this phase remain untouched, per Phase 2A's explicit scope limit.

- [x] Graph Builder bounded-traversal query + hop-index computation — `app/graph/builder.py`, `app/modules/transactions/service.py::compute_hop_index`. Verified live: a real 4-hop mule chain submitted through the API, independently confirmed in Neo4j via `cypher-shell` (not application logs) at the correct depths, and reproduced identically by `scripts/rebuild_neo4j_graph.py` after a full wipe.
- [x] Ring Detector (Louvain) — AI_ML_ARCHITECTURE.md §2
- [x] Corridor/Exit-Vector Predictor — §3
- [x] Exit-Channel + Time-Window Scorer (XGBoost + Cox model, `channel_type` as a categorical feature), trained on the synthetic dataset — §4
- [x] Risk Field Fusion (decay + overlap logic) — §5
- [x] SHAP-based Explainer — §6
- [x] Model registry + feature snapshot persistence — §9
- [x] Evaluation harness computing top-K hit rate, calibration, Brier score on a held-out synthetic split, sliced per `channel_type` and per jurisdiction (the latter per SECURITY_AND_GOVERNANCE.md §6's fairness slice)

**Exit criteria**: for a held-out synthetic complaint, the pipeline produces a ranked exit-channel list with a computed top-K hit rate and calibration report — numbers, not vibes.

## Phase 3 — Real-time & interface contracts

- [x] WebSocket gateway with jurisdiction-scoped channels — ARCHITECTURE.md §5. **Done in Phase 1** (see "Build status" above), not deferred — verified live against the real Docker stack.
- [ ] Incremental recompute (only touched H3 cells/exit channels re-scored on new transaction) — depends on Phase 2's scoring existing at all
- [ ] Case & Approval module: state machine, assignment, RBAC scoping — basic RBAC scoping (jurisdiction-based read access) is done; case *assignment* and the approval state machine are not
- [ ] Full REST + WebSocket surface from API_CONTRACT.md implemented and contract-tested against the OpenAPI spec, emitting the full canonical event sequence (§4 of PRODUCT_EXPERIENCE.md) — only `complaint.created` exists; the rest of the sequence activates as Phase 2/4 stages are built

**Exit criteria**: a WebSocket client subscribed to a jurisdiction receives the full `intelligence.started → ... → explanation.generated` event sequence within 2 seconds of a transaction being ingested, with no polling anywhere in the client.

## Phase 4 — The differentiator (optimizer) & action layer

- [x] Greedy coverage-maximization optimizer (mode 7a) + ranked resource-allocation optimizer (mode 7b) + naive-baseline comparison for both — AI_ML_ARCHITECTURE.md §7a/§7b
- [x] Approval gate enforced server-side (no send path without an `approved` decision row) — USER_FLOWS.md Flow D
- [x] Action module: signed webhook builder, single `mock-external-systems` service with bank/I4C/exchange/merchant routes — DEMO_ARCHITECTURE.md §4
- [x] Outcome recording endpoint → labeled FeatureSnapshot write — Flow E

**Exit criteria**: changing `team_count` (mode 7a) or `request_slot_count` (mode 7b) on the same case produces a genuinely different, re-computed assignment with a coverage/expected-value-gain number, and an unapproved deployment cannot trigger an alert (verified by a test that asserts the send function raises without a decision row).

## Phase 5 — Audit, feedback, governance

- [x] Hash-chained audit_events table + append function + chain-verification endpoint — SECURITY_AND_GOVERNANCE.md §4
- [x] Retraining job: re-fit on accumulated FeatureSnapshot labels, champion/challenger evaluation, versioned promotion — AI_ML_ARCHITECTURE.md §8
- [x] RBAC matrix fully enforced across every endpoint (automated test per role × endpoint)
- [x] "Reality legend" metadata exposed via API so a future frontend can render the SIM/REAL badges without hardcoding

**Exit criteria**: `GET /v1/audit/verify-chain` correctly detects a deliberately corrupted row in a test fixture; a retraining run only promotes a new model version when it beats the current one on held-out metrics.

## Phase 6 — Demo assembly & rehearsal

- [ ] `demo_scenario_a_atm.yaml` authored and tuned for pacing — this is the primary judge run (JUDGE_DEMO.md), build and rehearse it to completion before starting B/C
- [ ] `demo_scenario_b_crypto.yaml`, `demo_scenario_c_ecommerce.yaml` — additive, secondary "generalizes" beat (PRODUCT_EXPERIENCE.md §7); cut first under time pressure
- [ ] Live-drip mode of the synthetic harness posts each scenario through the real API at demo pace
- [ ] Fallback recording captured from a live run of Scenario A (not staged separately) — JUDGE_DEMO.md §5
- [ ] Full rehearsal against the acceptance criteria in PRODUCT.md §6 and the minute-by-minute script in JUDGE_DEMO.md §2

**Exit criteria**: the complete 14-step flow (PRODUCT.md §4 / PRODUCT_EXPERIENCE.md §1) runs live on Scenario A, end to end, in under two minutes of system time within the 5-minute judge slot, at least three consecutive times without manual intervention.

---

## Testing strategy (applies across all phases, not a separate phase)

| Level | What it covers | Tooling |
|---|---|---|
| Unit | Graph traversal bounds, decay function math, greedy optimizer correctness on hand-built small cases, hash-chain append/verify logic | `pytest` |
| Integration | API → Postgres → Neo4j → event bus round-trips; a posted complaint produces the correct downstream state across all three stores | `pytest` + test containers (ephemeral Compose stack) |
| Model evaluation | Top-K hit rate, calibration reliability diagram, Brier score, coverage-gain vs. naive baseline — run against a held-out synthetic split, checked into the model registry's `metrics` field, not just eyeballed once | Python eval scripts, run per training/retraining job |
| Contract | Every endpoint's request/response validated against the OpenAPI spec generated from API_CONTRACT.md | `schemathesis` or equivalent |
| Security/RBAC | Every (role, endpoint) pair tested for expected allow/deny; jurisdiction/bank scoping tested with cross-tenant attempts that must fail | `pytest` parametrized matrix |
| Audit integrity | Deliberately corrupt a row in a test DB, assert `verify-chain` detects it at the correct `seq_no` | `pytest` |
| End-to-end / demo rehearsal | The full scripted scenario run against a fresh Compose stack, timed | Manual + scripted timing assertions |

No test level is skipped for "it's just a hackathon" — the model-evaluation and audit-integrity levels in particular are exactly what let the team answer judge questions with numbers instead of adjectives.

## Technical debt carried out of Phase 1 (updated 2026-08-26)

Recorded explicitly rather than left implicit, per the standing rule that nothing gets silently fixed or silently ignored. Ordered by what actually blocks later phases.

| # | Item | Must resolve before | Notes |
|---|---|---|---|
| 1 | Plain `lat`/`lon` floats instead of PostGIS `Geography` columns (`accounts.branch_lat/lon`, `exit_channels.geo_lat/lon`) | **Phase 3/4** (risk field, optimizer — the first things that need real spatial queries: `ST_DWithin`, distance/travel-time) | Confirmed during Docker verification that the infrastructure is fully ready — PostGIS 3.4.3 is installed and enabled in the real Postgres container right now. This is purely an ORM-layer decision made for Docker-less portability during Phase 0/1; migrating specific columns to `Geography(Point, 4326)` + GiST indexes is a small, mechanical Alembic migration, not a redesign. |
| 2 | ~~PostGIS extension not created by any migration~~ — **RESOLVED.** The initial migration now runs `CREATE EXTENSION IF NOT EXISTS postgis` itself (dialect-guarded), verified against a from-scratch database with zero manual steps. | — closed | Kept here, struck through, rather than deleted — this is exactly the kind of found-and-fixed item that should stay visible rather than vanish once resolved. |
| 3 | ~~Neo4j constraints/indexes applied but no graph data~~ — **RESOLVED (Phase 2A).** The Graph Builder now writes real data: a live 4-hop mule chain was submitted through the API and independently verified in Neo4j via `cypher-shell`, then reproduced identically by a full wipe + `scripts/rebuild_neo4j_graph.py`. | — closed | `SHARES_*_WITH`, `LINKED_TO_CASE`, `HISTORICALLY_EXITED_VIA`, `:Ring`/`MEMBER_OF_RING` remain unbuilt - that's Ring Detector/Louvain (Phase 2B), correctly out of Phase 2A's scope. |
| 4 | Audit hash-chain concurrency: `seq_no`/`prev_hash` are computed from the current max row inside the caller's transaction, not `SELECT ... FOR UPDATE`-locked | Before concurrent writers are realistic (not yet — current traffic is one request at a time) | See `app/audit/service.py`'s own docstring. Needs either row locking on Postgres or a dedicated atomic counter table. |
| 5 | Alembic's autogenerated `downgrade()` doesn't drop Postgres enum types, so `alembic downgrade base` followed by `alembic upgrade head` fails with `DuplicateObject` | Whenever downgrade is actually needed (not the normal lifecycle — only `upgrade head` runs today, via `docker-entrypoint.sh`) | Found during this session's Docker verification while manually resetting the database for a clean test. Workaround used: drop and recreate the whole database rather than `alembic downgrade`. |
| 6 | `run_full_seed`'s mule-ring/historical-incident generation used to be fully deterministic across separate invocations (`Faker.seed()`/`random.seed()` re-pinned every call), which collided on `accounts.account_hash`'s unique constraint the moment the seed script ran a second time against a non-empty database | **Fixed** during this session's Docker verification (see `app/synthetic/generator.py`) — recorded here only because it's exactly the kind of bug that would have resurfaced quietly if the fix weren't documented | Verified fixed by seeding three times consecutively against real Postgres with no collisions. |
| 7 | No file upload for citizen-submitted evidence — text notes only | Not blocking any phase; a deliberate Phase 1 scope cut | Would need storage + basic validation (size/type) before it's worth adding; no phase currently requires it. |
| 8 | Jurisdiction matching on intake is free-text `contains()` against seeded names, with a catch-all "Unassigned Queue" fallback and no reassignment UI | Phase 3 (Case & Approval module) | A supervisor triaging the fallback queue and reassigning jurisdiction is a natural Case & Approval feature, not built. |
| 9 | JWT: single moderate-TTL token, no refresh flow, no revocation list (docs/PRODUCT_EXPERIENCE.md §8.2) | Only if session lifetime becomes an actual problem | Deliberate simplification, not an oversight — revisit if demo/ops needs sessions longer than a few hours. |
| 10 | Supervisor escalation logic (docs/USER_FLOWS.md Flow F) — role exists in RBAC, the escalation *behavior* was deprioritized out of the build | Not blocking; pick up if/when supervisor workflows become a focus | |
| 11 | ~~Transaction-ingestion contract frozen but unimplemented~~ — **RESOLVED (Phase 2A).** `service` role, `transactions.idempotency_key`, and the endpoint itself are all built and verified against the real Docker stack. | — closed | |
| 12 | **New, found during Phase 2A live verification**: `Driver.verify_connectivity()` returns `None` on success (it only raises on failure) - `app/graph/rebuild.py::rebuild_all` originally checked `not driver.verify_connectivity()`, which was therefore always `True` and made the reachability check fail even when Neo4j was perfectly healthy | **Fixed** during this session | Caught immediately (the rebuild script errored on first real run) and fixed by reusing `app/db/neo4j_client.py`'s already-correct `check_connectivity()` (try/except, never a truthiness check on a `None`-returning call) instead of re-deriving the same logic a second, subtly wrong way. |
| 13 | **New**: per-transaction device/IP/phone/VPA context (`linked_entities`) has no dedicated dedup key beyond `(account_id, entity_type, entity_hash)` - a legitimate account switching devices frequently produces one `Device` node per distinct device, which is correct, but there is no retention/pruning policy yet for accounts with many such entities over a long history | Phase 2B+ if this becomes a real volume concern | Not a bug - just unbounded growth with no policy decided yet. Noted rather than silently assumed fine at scale. |

## Sequencing dependencies (why this order)

Phase 1 must precede Phase 2 (no graph without ingested data). Phase 2 must precede Phase 4 (no optimizer without a risk surface to optimize over). Phase 3 (real-time) can run **in parallel with** Phase 2 once the event contracts are fixed in Phase 0 — it doesn't need the models to be *good*, only to *emit events in the right shape*, so the two phases are not serialized in practice even though listed in order. Phase 5's audit logging should actually be threaded in from Phase 1 onward (every phase's state changes should append audit events as they're built, not bolted on at the end) — it is listed as Phase 5 only because that's when the *verification tooling and retraining* land, not because logging itself is deferred.
