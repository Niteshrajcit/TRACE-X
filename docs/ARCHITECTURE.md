# TRACE-X — System Architecture

> Depends on: [PRODUCT.md](PRODUCT.md) for the component legend (🟢🔵🟡🟠⚪) and persona list.

---

## 1. Architecture style

**Modular monolith with a service-shaped internal boundary**, not microservices. Reasoning: a hackathon prototype that splits into 8 deployed services multiplies operational risk (network calls, service discovery, partial failure) for zero demo benefit. Instead, the backend is one FastAPI process internally organized into the same modules a microservice split would use — each with its own router, service layer, and — critically — **no direct imports across module boundaries except through a defined interface function**. This means the Phase-2 (post-SIH) move to real microservices is a mechanical extraction, not a rewrite. This decision is itself 🟡 ALGO-grade deliberate engineering, not a shortcut: it is documented so nobody mistakes "one process" for "no boundaries."

The one component that *is* a separate process even in the prototype is the **synthetic data generator / simulation harness**, because it must be able to run standalone (to regenerate a dataset) and as a live feed (to drip transactions into the system during a demo) — see [DEMO_ARCHITECTURE.md](DEMO_ARCHITECTURE.md).

## 2. Layered view

```
┌────────────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER  (architecture only — not built this phase)    │
│  Investigator Console │ Risk Heatmap │ Alert Inbox │ Audit Viewer   │
└───────────────────────────────┬──────────────────────────────────┘
                REST (CRUD, queries)  │  WebSocket (live push)
┌───────────────────────────────┴──────────────────────────────────┐
│  API GATEWAY MODULE (FastAPI)                            🟢 REAL   │
│  Auth/RBAC middleware · request validation · rate limiting        │
└───────────────────────────────┬──────────────────────────────────┘
        ┌──────────────┬────────┴────────┬──────────────┬───────────┐
┌───────┴──────┐┌──────┴───────┐┌────────┴───────┐┌──────┴──────┐┌───┴────────┐
│  Intake &    ││  Case &      ││  Intelligence  ││  Action &   ││  Audit &   │
│  Ingestion   ││  Approval    ││  Pipeline      ││  Alerting   ││  Feedback  │
│  Module      ││  Module      ││  Orchestrator  ││  Module     ││  Module    │
│  🟢 REAL     ││  🟢 REAL     ││  (below)       ││  🟠 SIM out ││  🟢 REAL   │
└───────┬──────┘└──────┬───────┘└────────┬───────┘└──────┬──────┘└───┬────────┘
        │              │                 │               │           │
        └──────────────┴────────┬────────┴───────────────┴───────────┘
                                 │
┌────────────────────────────────┴──────────────────────────────────┐
│  INTELLIGENCE PIPELINE (invoked synchronously per complaint,       │
│  then re-invoked incrementally per new transaction event)          │
│                                                                     │
│  Graph Builder → Ring Detector → Corridor/Exit-Vector Predictor    │
│      →  Location+Time Scorer → Risk Field Fusion → Explainer       │
│      →  Intervention Optimizer                                    │
│  See AI_ML_ARCHITECTURE.md for the per-stage I/O contract          │
└────────────────────────────────┬──────────────────────────────────┘
                                 │
┌────────────────────────────────┴──────────────────────────────────┐
│  DATA LAYER                                                        │
│  PostgreSQL+PostGIS (system of record, geo queries)   🟢 REAL      │
│  Neo4j (fraud graph, multi-hop traversal)             🟢 REAL      │
│  In-process risk-field cache + event dispatcher       🟢 REAL      │
│  Feature snapshots (versioned Postgres tables)        🟢 REAL      │
│  Model registry (filesystem + metadata table)         🟢 REAL      │
│  Audit ledger (hash-chained Postgres table)           🟢 REAL      │
│  Object storage for evidence/explanation payloads     🟢 REAL (local disk/minio) │
└────────────────────────────────┬──────────────────────────────────┘
                                 │
┌────────────────────────────────┴──────────────────────────────────┐
│  INGESTION / EXTERNAL BOUNDARY                                    │
│  Complaint intake (own form)              🟢 REAL                  │
│  Synthetic transaction stream generator   🟢 REAL / drives 🔵 models│
│  Public ATM/branch registry (real data)   🟢 REAL                  │
│  NCRP live feed adapter                   ⚪ FUTURE                 │
│  Bank core transaction feed adapter       ⚪ FUTURE                 │
│  I4C notification adapter                 ⚪ FUTURE (🟠 SIM receiver built) │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. Backend modules

| Module | Responsibility | Depends on |
|---|---|---|
| **Intake & Ingestion** | Accepts complaint submissions, validates, hashes PII, assigns incident ID, emits `complaint.created` event | Postgres, event bus |
| **Case & Approval** | Case lifecycle (open/under-review/closed), assignment to investigator/jurisdiction, approval-gate state machine | Postgres, Auth |
| **Intelligence Pipeline Orchestrator** | Listens for `complaint.created` and `transaction.ingested`, runs the pipeline stages in order, persists outputs, emits the full `intelligence.started → ... → explanation.generated` sequence (§4) | Neo4j, Postgres, model registry |
| **Action & Alerting** | Builds alert payloads, routes to correct bank/I4C mock endpoint by jurisdiction/account, tracks delivery + read receipts | Postgres, SIM adapters |
| **Audit & Feedback** | Appends hash-chained audit events for every state change; captures outcomes; writes retraining-ready labeled rows | Postgres |
| **Auth/RBAC** (cross-cutting middleware, not a "module" with business logic) | JWT issuance/verification, role/jurisdiction scoping on every query | Postgres (users, roles) |

## 4. Event backbone

🟢 REAL. **[Revised after product review — see PRODUCT_EXPERIENCE.md §8.1]** A single **event bus abstraction** (interface: `publish(topic, payload)`, `subscribe(topic, handler)`) backed, for the prototype, by an **in-process `asyncio` publish/subscribe registry** rather than Redis Streams. The original design justified Redis Streams against Kafka; the relevant comparison for a single-process modular monolith (§1) is actually against no broker at all — every producer and consumer of these events lives in the same FastAPI process, so routing them through a network hop buys nothing and adds a container, a connection pool, and a live-demo failure mode. The interface is unchanged and deliberately broker-agnostic (topic name + payload only), so upgrading to Redis Streams or Kafka once a second backend process genuinely exists is a one-file swap, not a redesign — that upgrade path is named, not silently dropped.

Canonical event sequence (expanded to match the granularity the product experience needs — see [PRODUCT_EXPERIENCE.md §4](PRODUCT_EXPERIENCE.md) for the full producer/consumer/DB/WebSocket/UI table per event):

| Event | Producer | Consumers |
|---|---|---|
| `complaint.created` | Intake module | Intelligence orchestrator, Case module, WS gateway |
| `intelligence.started` | Intelligence orchestrator | WS gateway |
| `graph.updated` | Graph Builder | Ring Detector (next stage), WS gateway |
| `exit_prediction.completed` | Corridor/Exit-Vector Predictor | Location+Time Scorer (next stage), WS gateway |
| `spatiotemporal_prediction.completed` | Location/Exit-Channel + Time-Window Scorer | Risk Field Fusion, WS gateway |
| `risk_field.updated` | Risk Field Fusion | WS gateway (jurisdiction-wide channel) |
| `explanation.generated` | Explainer | WS gateway |
| `intervention.recommended` | Intervention Optimizer | WS gateway |
| `approval.required` | Case & Approval module | WS gateway |
| `intervention.approved` / `intervention.rejected` | Case & Approval module | Action module (approved only), Audit module, WS gateway |
| `action.dispatched` | Action module | Audit module, mock external receiver, WS gateway |
| `outcome.recorded` | Case & Approval module | Audit module, Feedback/retraining job, WS gateway |
| `feedback.created` | Feedback/retraining pipeline | Audit module, WS gateway |

## 5. Real-time architecture

🟢 REAL. WebSocket connections are terminated at the API gateway module; on connect, the client subscribes to a jurisdiction-scoped channel. The gateway itself subscribes to the in-process event dispatcher (§4) on the same topics and fans out to matching WebSocket connections. No polling anywhere in the design — this directly satisfies PROJECT.md §6's "live risk-field updates without polling."

```
Synthetic feed / real adapter → POST /v1/transactions/ingest → transaction.ingested (in-process)
    → Orchestrator recomputes affected H3 cells only (incremental, not full recompute)
    → graph.updated → exit_prediction.completed → spatiotemporal_prediction.completed
    → risk_field.updated (in-process dispatch)
    → API gateway WS handler → filtered by jurisdiction → pushed to connected investigators
```
See [PRODUCT_EXPERIENCE.md §4](PRODUCT_EXPERIENCE.md) for exactly what each event changes in the database and on screen.

Incremental recompute matters for the "scale to 8,000 complaints/day" judge question (PROJECT.md §16): only complaints tagged as active financial fraud with real money movement enter the pipeline at all, and only the H3 cells touched by a new transaction are rescored, not the whole risk field.

## 6. Geospatial indexing

🟡 ALGO. Uber H3, resolution 8 (~0.46 km² hexagons) as the default prediction unit, matching PROJECT.md §7.2. Resolution is configurable per district (denser urban districts may use resolution 9). All location-scoring and risk-field outputs are keyed by `h3_cell`, never raw lat/lon, so aggregation and multi-resolution rollups (for the dashboard's zoom levels) are index lookups, not re-computation.

## 7. Frontend architecture (documented, not built this phase)

Per PROJECT.md §10: React + TypeScript, Mapbox GL/Leaflet + deck.gl for H3 hex-layer rendering, WebSocket client for live updates, REST client for CRUD. **The full information architecture — screens, routes, and the Incident Workspace's internal layout — is now locked in [PRODUCT_EXPERIENCE.md §2–3](PRODUCT_EXPERIENCE.md); this section only records the technical shell that IA sits inside.** Visual language is specified in [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

State management: server state via React Query (cache + WebSocket-driven invalidation), no separate global store needed for this scope — the WebSocket event table in PRODUCT_EXPERIENCE.md §4 maps directly onto React Query cache invalidations, one event type to one query key family. This is documented now so the eventual frontend build has a settled contract; it is explicitly out of scope to implement in this phase.

## 8. Technology choices with reasons

| Layer | Choice | Why this over the alternatives |
|---|---|---|
| Backend framework | FastAPI (Python) | Same language as the ML stack (no serialization boundary between API and model code), native async for WebSocket + I/O concurrency, auto-generated OpenAPI doubles as living API docs |
| Relational DB | PostgreSQL + PostGIS | ACID system of record; PostGIS gives real geospatial predicates (distance, containment) needed by the risk-field and optimizer without a second geo-database |
| Graph DB | Neo4j Community | Multi-hop traversal (`shares_device_with`, ring membership) is a first-class query in Cypher; doing this in SQL means recursive CTEs that get unreadable past 2 hops. Alternative considered: Apache AGE (Postgres extension) — rejected because Cypher tooling/visualization maturity matters for the graph-view UI later |
| Event bus | In-process `asyncio` publish/subscribe (prototype); Redis Streams/Kafka documented as the production upgrade | The prototype backend is one process — every producer and consumer of an event lives in it, so a network-hop broker (Redis or Kafka) adds a container, a connection pool, and a live-demo failure mode for zero benefit at this scale. See PRODUCT_EXPERIENCE.md §8.1 |
| ML — tabular | XGBoost / LightGBM | Best-in-class on structured, fused feature vectors (the location scorer's actual input shape); native SHAP support |
| ML — graph | NetworkX + community detection (Louvain) for prototype; PyTorch Geometric GNN documented as the upgrade path | A GNN needs thousands of labeled ring examples to train meaningfully; we don't have that data honestly. Louvain community detection is real, unsupervised, and produces genuinely useful ring clusters from the graph structure alone — see [AI_ML_ARCHITECTURE.md](AI_ML_ARCHITECTURE.md) §2 |
| ML — time-to-event | `lifelines` (Cox proportional hazards) | Purpose-built survival analysis library; gives a real hazard curve for "time until cash-out" rather than faking a countdown |
| Explainability | SHAP (`TreeExplainer` on the XGBoost model) | Exact, fast attribution for tree ensembles; industry-standard, defensible to judges and, eventually, to courts |
| Optimization | Greedy submodular coverage maximization (own implementation); OR-Tools CP-SAT documented as exact-ILP upgrade | Greedy gives a provable (1 − 1/e) approximation bound for this class of coverage problem and runs in milliseconds — appropriate for a live re-optimize-on-team-count-change interaction; ILP is exact but slower and unnecessary at the team counts realistic here (2–10) |
| Geospatial index | Uber H3 | Uniform hex cells (no polar/latitude distortion like square grids), clean parent/child multi-resolution rollups |
| Auth | JWT (short-lived access + refresh) + RBAC | Stateless verification suits the module-boundary design; RBAC claims carry role + jurisdiction so every query can be scoped without a second lookup |
| Containerization | Docker Compose (prototype); Kubernetes manifests documented, not deployed | Compose is sufficient for a single-host demo; K8s adds no demo value and real operational cost |
| Audit ledger | Hash-chained Postgres table (own implementation) | See [SECURITY_AND_GOVERNANCE.md](SECURITY_AND_GOVERNANCE.md) — gives real tamper-evidence without standing up a distributed ledger we can't operate reliably during a live demo |

## 9. Service-to-service communication

Because this is a modular monolith, "service-to-service" mostly means **module-to-module contracts inside one process**, plus three real network boundaries:

1. **Frontend ↔ Backend**: REST (OpenAPI-documented) + one WebSocket endpoint per jurisdiction channel
2. **Backend ↔ Synthetic Data Harness**: the harness is a separate process; it talks to the backend the same way a real bank feed eventually would — POSTing to the same ingestion endpoint (`/v1/transactions/ingest`) a real adapter would use. This is the single most important design decision for judge credibility: **the demo's fake data enters through the exact same door a real feed would**, so "swap the source" is a literal true statement, not a slide claim.
3. **Backend ↔ Mock external systems**: signed HTTP webhooks (HMAC signature header), so the Action module's outward call is byte-for-byte what a real institutional integration would receive — only the receiving end is 🟠 SIM. **[Revised — see PRODUCT_EXPERIENCE.md §8.4]** Bank, I4C, crypto-exchange, and e-commerce-merchant mock receivers (the latter two needed for Scenarios B/C, PRODUCT_EXPERIENCE.md §7) are consolidated into **one** lightweight `mock-external-systems` service exposing one route per channel (`/mock/bank`, `/mock/i4c`, `/mock/exchange`, `/mock/merchant`), rather than a separate container per institution type — each route independently logs and independently surfaces in the Alert Inbox screen by `channel`, so the demo's "watch the external system receive it" moment is unaffected while container count stays flat as scenarios are added.

Internal module-to-module calls go through typed Python interfaces (e.g. `IntelligencePipeline.run(complaint_id) -> PredictionResult`), never raw dict-passing, so the eventual microservice extraction only has to turn a function call into an RPC call.

## 10. Deployment architecture

**Prototype/demo**: Docker Compose on a single host —
```
docker-compose.yml
  ├─ postgres (with PostGIS extension)
  ├─ neo4j
  ├─ backend (FastAPI, uvicorn — hosts the in-process event dispatcher, §4)
  ├─ synthetic-data-harness (own container, controllable via a small CLI/API)
  ├─ mock-external-systems (own container, 🟠 SIM — bank/I4C/exchange/merchant routes, see §9)
  └─ (frontend — future phase)
```
Redis is deliberately absent from this stack for the prototype (§4, §8) — one fewer container to keep healthy during a live demo, with the upgrade path to Redis/Kafka named for when a second backend process exists.
One `docker-compose up` must bring the full pipeline to a demoable state, including seeding synthetic base data (accounts, ATM registry, historical cases) via an init job.

**Production (documented, ⚪ FUTURE)**: Kubernetes, managed Postgres (RDS/Cloud SQL with PostGIS), managed Neo4j Aura, managed Redis, secrets in a vault, real feed adapters replacing the SIM containers, horizontal scaling of the intelligence orchestrator behind the event bus (consumer groups), observability stack (Prometheus/Grafana/structured logs) — named here so the phase boundary is explicit, not designed further in this document.

## 11. Non-functional requirements

| Concern | Prototype target | Notes |
|---|---|---|
| Latency: complaint → first prediction | < 5s | Drives incremental-recompute design (§5) |
| Latency: transaction → risk-field update on screen | < 2s | WebSocket push, not poll |
| Throughput | Handle a simulated burst of 500 complaints/hour without falling behind | Matches a scaled-down slice of the real 8,000/day volume, proportionally |
| Data integrity | Every state-changing action produces exactly one audit event, ordered, hash-linked | Verified by an automated audit-chain-verification test (see IMPLEMENTATION_PLAN.md testing strategy) |
| Availability | Single-host demo; no HA requirement this phase | Explicitly deferred to production phase |
