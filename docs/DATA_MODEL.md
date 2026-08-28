# TRACE-X — Data Model

> Depends on: [ARCHITECTURE.md](ARCHITECTURE.md) §8 for why the store split (Postgres/Neo4j) exists. **[Revised after product review]** Redis is no longer part of the prototype stack — see ARCHITECTURE.md §4 and PRODUCT_EXPERIENCE.md §8.1; the live risk-field cache and event fan-out described below now live in-process.

---

## 1. Storage split rationale

| Data | Store | Why not the other one |
|---|---|---|
| Complaints, cases, accounts, transactions, users, audit log, model registry, feature snapshots | PostgreSQL + PostGIS | Needs ACID, referential integrity, geospatial predicates — the system of record |
| Fraud graph (nodes/edges), multi-hop traversal, ring membership | Neo4j | Multi-hop path queries in SQL degrade past 2–3 joins; Cypher is the right tool and native to graph visualization |
| Live risk-field cache, WebSocket fan-out, event dispatch | In-process (`asyncio` registry + a plain in-memory dict, single backend process) | Ephemeral/hot-path data with exactly one process producing and consuming it in the prototype (ARCHITECTURE.md §4, PRODUCT_EXPERIENCE.md §8.1); the durable copy of every prediction still lands in Postgres. Redis/Kafka is the named upgrade once a second backend process exists |

Neo4j is a **derived, rebuildable** store — every node/edge it holds is reconstructable from Postgres's `transaction` and `account` tables. This matters operationally (Neo4j can be wiped and rebuilt) and matters to judges (there's one source of truth, not two disagreeing databases).

---

## 2. PostgreSQL schema (system of record)

```sql
-- Identity & access
users (
  user_id UUID PK, email, password_hash, role ENUM('citizen_portal','investigator','supervisor',
    'bank_liaison','auditor','admin'), jurisdiction_id FK NULL, bank_id FK NULL,
  created_at, is_active
)

jurisdictions ( jurisdiction_id PK, name, state, district, boundary GEOMETRY(POLYGON,4326) )
-- boundary is retained for map rendering/admin use only. Runtime jurisdiction lookups do NOT
-- perform a live polygon-containment query — see the precomputed h3_cell_jurisdiction table below.
-- [Revised after product review — PRODUCT_EXPERIENCE.md §8.5]

h3_cell_jurisdiction ( h3_cell TEXT PK, jurisdiction_id FK )
-- populated once at seed time via a single polygon-containment pass over every H3 cell in scope;
-- every hot-path query (risk-field fetch, WebSocket channel routing) becomes an indexed lookup
-- against this table instead of a runtime ST_Contains join against `jurisdictions.boundary`

banks ( bank_id PK, name, ifsc_prefix )

-- Complaint intake
complaints (
  complaint_id UUID PK,            -- the "incident ID" returned to the citizen
  filed_at TIMESTAMPTZ,
  fraud_type ENUM('upi_fraud','phishing','investment_scam','loan_app_fraud','other'),
  amount NUMERIC,
  victim_account_id FK -> accounts,
  jurisdiction_id FK,
  status ENUM('new','graph_building','predicted','action_recommended',
              'approved','rejected','closed'),
  assigned_investigator_id FK -> users NULL,
  source ENUM('own_intake_form','ncrp_feed_future') DEFAULT 'own_intake_form'
)

-- Accounts & transactions (PII-hashed at ingestion boundary — see SECURITY_AND_GOVERNANCE.md)
accounts (
  account_id UUID PK,
  account_hash TEXT UNIQUE,        -- irreversible hash; no raw account number stored
  bank_id FK,
  branch_geo GEOGRAPHY(POINT,4326),
  kyc_risk_tier ENUM('low','medium','high'),
  opened_at
)

transactions (
  txn_id UUID PK,
  from_account_id FK -> accounts,
  to_account_id FK -> accounts,
  amount NUMERIC,
  channel ENUM('upi','imps','neft','card','cash_withdrawal'),
  hop_index INT,                   -- distance from victim account, denormalized from graph
  complaint_id FK -> complaints,    -- nullable: NULL for synthetic batch-mode reference
                                     -- transactions (DEMO_ARCHITECTURE.md §2), required on the
                                     -- POST /v1/transactions/ingest request itself
                                     -- (API_CONTRACT.md §1a)
  occurred_at TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ,
  idempotency_key TEXT UNIQUE NULL, -- [frozen in API_CONTRACT.md §1a, added at Phase 2
                                     -- implementation time] mirrors complaints.idempotency_key -
                                     -- a transaction has no natural unique key a retried
                                     -- bank-feed call could dedupe against otherwise
  exit_channel_id FK -> exit_channels NULL, -- [added Phase 2A, API_CONTRACT.md §1a] which
                                     -- already-seeded ATM/exchange/merchant this transaction
                                     -- cashed out through, when applicable - must reference an
                                     -- existing row, never created by naming it
  is_synthetic BOOLEAN DEFAULT TRUE  -- explicit, queryable, never silently true in prod
)

linked_entities (
  entity_id UUID PK, account_id FK, entity_type ENUM('device','phone','address_cluster'),
  entity_hash TEXT
)

-- Exit geography — generalized from a prototype that assumed every cash-out was a physical ATM.
-- [Revised after product review — PRODUCT_EXPERIENCE.md §7] Renamed CashOutPoint -> ExitChannel so
-- the three demo scenarios (ATM / crypto P2P / e-commerce) are genuinely different data, not a
-- text relabel of the same row shape. Every channel still carries a geo_anchor so the Risk Map
-- tab is never empty, but what that anchor MEANS differs by channel_type (see table below).
exit_channels (
  channel_id UUID PK,
  channel_type ENUM('atm_cash', 'crypto_p2p', 'ecommerce_merchant'),
  external_ref TEXT,              -- atm_or_branch_id | exchange_account_id | merchant_order_id
  geo_anchor GEOGRAPHY(POINT,4326),  -- ATM/branch location | exchange's nodal settlement bank
                                      -- branch | delivery/pickup address at order time
  h3_cell TEXT,
  channel_attributes JSONB,       -- atm: {cash_limit, cctv_flag, footfall_tier}
                                   -- crypto_p2p: {exchange_name, kyc_tier, wallet_address_hash}
                                   -- ecommerce_merchant: {merchant_name, sku_category, order_value}
  intervention_action_type ENUM('physical_team_deployment', 'exchange_freeze_request',
                                 'merchant_hold_request'),
  historical_incident_count INT
)

-- Predictions (one row per pipeline run, immutable/append-only)
predictions (
  prediction_id UUID PK, complaint_id FK, generated_at TIMESTAMPTZ,
  model_version_ring TEXT, model_version_corridor TEXT,
  model_version_location TEXT, model_version_time TEXT,
  exit_vector JSONB,               -- [Phase 2C] {bearing_deg, distance_range_km,
                                    --   confidence_cone_deg, exit_channel_type} - AI_ML_ARCHITECTURE.md
                                    -- §3's Corridor/Exit-Vector Predictor output. A single JSONB
                                    -- field, not four scalar columns, since these four values are
                                    -- always read/written together as one structured prediction
                                    -- output, never queried individually.
  ranked_locations JSONB,          -- [{h3_cell, exit_channel_id?, channel_type, probability,
                                    --   time_window_min, ci}] -- exit_channel_id is populated once
                                    -- a specific channel (ATM/exchange/merchant) is scored, not
                                    -- just a bare H3 cell — see PRODUCT_EXPERIENCE.md §7.
                                    -- [Phase 2C status] NULL until Phase 2D (§4, Exit-Channel +
                                    -- Time-Window Scorer) is built - explicitly null, never a
                                    -- fabricated/placeholder list.
  explanation JSONB,               -- [{feature, weight, evidence_ref}], graph_path, comparable_cases
  feature_snapshot JSONB           -- exact feature vector used, for reproducibility
)

recommended_deployments (
  deployment_id UUID PK, prediction_id FK,
  optimizer_mode ENUM('coverage_maximization','resource_allocation'),  -- branches by the
    -- exit_channel's intervention_action_type (AI_ML_ARCHITECTURE.md §7): physical_team_deployment
    -- runs coverage_maximization; exchange_freeze_request/merchant_hold_request run
    -- resource_allocation (a ranked knapsack over limited request slots, not a geo-coverage problem)
  team_count INT NULL,             -- populated only for coverage_maximization
  request_slot_count INT NULL,     -- populated only for resource_allocation
  assignment JSONB,                -- coverage_maximization: [{team_id, h3_cell, expected_coverage,
                                    --   travel_time_min}]
                                    -- resource_allocation: [{exit_channel_id, priority_rank,
                                    --   expected_value, hazard_at_request_time}]
  expected_coverage_total NUMERIC, naive_baseline_coverage NUMERIC,
  status ENUM('proposed','approved','rejected'), decided_by FK -> users, decided_at
)

-- Action / alerting
alerts (
  alert_id UUID PK, prediction_id FK, channel ENUM('dashboard','sms_sim','email_sim',
    'bank_webhook_sim','i4c_webhook_sim','exchange_webhook_sim','merchant_webhook_sim'),
    -- last two added for Scenarios B/C (PRODUCT_EXPERIENCE.md §7); all route through the single
    -- mock-external-systems service (ARCHITECTURE.md §9) distinguished by this channel value
  recipient_ref TEXT,
  payload JSONB, sent_at, delivered_at, read_at
)

intervention_outcomes (
  outcome_id UUID PK, deployment_id FK, recorded_by FK -> users, recorded_at,
  result ENUM('cash_out_prevented','cash_out_occurred_elsewhere','no_activity',
              'funds_recovered_partial','funds_recovered_full'),
  notes TEXT, feeds_retraining BOOLEAN DEFAULT TRUE
)

-- Audit (hash-chained, append-only — see SECURITY_AND_GOVERNANCE.md for chain mechanics)
audit_events (
  event_id UUID PK, seq_no BIGSERIAL,      -- strict ordering
  event_type TEXT, actor_id FK -> users NULL, subject_type TEXT, subject_id UUID,
  payload JSONB, occurred_at TIMESTAMPTZ,
  prev_hash TEXT, this_hash TEXT           -- this_hash = H(prev_hash || canonical(payload) || occurred_at)
)

-- ML operations
model_registry (
  model_id UUID PK, stage ENUM('ring_detector','corridor_predictor','location_scorer',
    'time_window_model'), version TEXT, trained_at, metrics JSONB, artifact_path TEXT,
  is_active BOOLEAN
)

feature_snapshots (
  snapshot_id UUID PK, complaint_id FK, stage TEXT, feature_vector JSONB,
  label JSONB NULL,                -- filled in once an outcome is recorded — this is the retraining row
  created_at
)
```

Indexing notes: `transactions(complaint_id, hop_index)`, `predictions(complaint_id, generated_at DESC)`, GIST index on `exit_channels.geo_anchor` (used by the optimizer's travel-time/distance queries) and `jurisdictions.boundary` (used only at seed time to populate `h3_cell_jurisdiction`, not on the hot path), a plain B-tree index on `h3_cell_jurisdiction.h3_cell`, and `audit_events(seq_no)` as the chain-verification scan path.

---

## 3. Neo4j graph schema

```
(:Complaint {complaint_id, fraud_type, amount, filed_at})
(:Account {account_hash, bank, kyc_risk_tier})
(:Device {device_hash})
(:Phone {phone_hash})
(:IP {ip_hash})                                                -- [added Phase 2A]
(:VPA {vpa_hash})                                               -- [added Phase 2A]
(:ExitChannel {channel_id, channel_type, h3_cell, lat, lon})   -- generalized from :CashOutPoint,
                                                                 -- see DATA_MODEL.md §2

(:Complaint)-[:INVOLVES]->(:Account)                       -- victim account
(:Account)-[:TRANSFERRED_TO {txn_id, amount, channel, hop_index, occurred_at}]->(:Account)
(:Account)-[:EXITED_VIA {amount, occurred_at}]->(:ExitChannel)   -- was :WITHDREW_AT; renamed
                                                                   -- because not every exit is a
                                                                   -- physical withdrawal (§2)
(:Account)-[:HAS_DEVICE]->(:Device)                        -- [added Phase 2A] raw structure;
(:Account)-[:HAS_PHONE]->(:Phone)                          -- these four make the *derived*
(:Account)-[:HAS_IP]->(:IP)                                -- SHARES_*_WITH edges below
(:Account)-[:HAS_VPA]->(:VPA)                              -- computable, not built directly
(:Account)-[:SHARES_DEVICE_WITH]->(:Account)                -- derived from shared Device node -
                                                              -- Ring Detector computes this
                                                              -- (Phase 2B), Phase 2A does not
(:Account)-[:SHARES_PHONE_WITH]->(:Account)                 -- same - Phase 2B, not built yet
(:Complaint)-[:LINKED_TO_CASE {reason}]->(:Complaint)       -- sibling-case linkage (Phase 2B+)
(:Account)-[:HISTORICALLY_EXITED_VIA {count, last_seen}]->(:ExitChannel)   -- was
                                                                             -- :HISTORICALLY_CASHED_OUT_AT
                                                                             -- (Phase 2B+)
(:Account)-[:MEMBER_OF_RING {cohesion_score}]->(:Ring {ring_id, detected_at, model_version})
                                                                             -- (Phase 2B+, Louvain)
```

**Phase 2A builds**: both `:IP`/`:VPA` node types, all four `HAS_*` edges, `TRANSFERRED_TO`, `EXITED_VIA`, and the `Complaint`-`INVOLVES`-`Account` victim link — see API_CONTRACT.md §1c for exactly which module writes each. Everything else in the block above (`SHARES_*_WITH`, `LINKED_TO_CASE`, `HISTORICALLY_EXITED_VIA`, `:Ring`/`MEMBER_OF_RING`) is derived/computed intelligence output, deliberately not built until the Ring Detector (Phase 2B, Louvain).

Canonical traversal query (bounded, per ARCHITECTURE.md §5's scaling answer):
```cypher
MATCH path = (c:Complaint {complaint_id: $id})-[:INVOLVES]->(v:Account)
  -[:TRANSFERRED_TO*1..6]->(a:Account)
OPTIONAL MATCH (a)-[:EXITED_VIA]->(p:ExitChannel)
RETURN path, p LIMIT 500
```

---

## 4. In-process structures (prototype)

**[Revised after product review — replaces the prior Redis-backed design, see PRODUCT_EXPERIENCE.md §8.1–8.2]** These live as plain in-memory Python data structures inside the single backend process — no separate store, no separate container:

| Structure | Shape | Purpose |
|---|---|---|
| `risk_field_cache[jurisdiction_id]` | dict (h3_cell → score) | Live risk surface cache, source of WebSocket pushes |
| Event dispatcher's subscriber registry | dict (topic → list of async callbacks) | Event backbone (§4 of ARCHITECTURE.md) |
| `ws_connections[jurisdiction_id]` | set of active WebSocket connections | WebSocket fan-out |

No JWT revocation list exists in the prototype (SECURITY_AND_GOVERNANCE.md §3) — access tokens are short/moderate-TTL and simply expire; a revocation store is named as a production requirement once refresh-token rotation is reintroduced.

---

## 5. Entity relationship summary

```
Complaint 1──1 Account(victim)
Complaint 1──* Transaction
Account   1──* Transaction (as from/to)
Complaint 1──* Prediction
Prediction 1──1 RecommendedDeployment (per team-count run; re-running creates a new row, never overwrites)
Prediction 1──* Alert
RecommendedDeployment 1──1 InterventionOutcome
Every state-changing action ──1 AuditEvent (append-only, hash-linked to the previous)
Prediction/Outcome ──* FeatureSnapshot (training rows for retraining)
```

## 6. PII handling in the data model

Raw account numbers, phone numbers, and citizen identity fields **never** persist past the ingestion boundary — they are hashed (see SECURITY_AND_GOVERNANCE.md §2) before the `accounts`/`linked_entities` rows are written. `complaints` intentionally has no `victim_name`/`victim_phone` column: predictions and audit records attach to `complaint_id`/`account_hash`, never to a named individual, which is the concrete schema-level enforcement of PROJECT.md §13's "predictions are attached to cases, not to named individuals."
