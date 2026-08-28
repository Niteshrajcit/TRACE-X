# TRACE-X — API Contract

> Depends on: [DATA_MODEL.md](DATA_MODEL.md) for entity shapes, [SECURITY_AND_GOVERNANCE.md](SECURITY_AND_GOVERNANCE.md) for the RBAC matrix these endpoints enforce.

All endpoints are versioned under `/v1`. Auth: `Authorization: Bearer <JWT>` except the citizen intake endpoint (public, rate-limited), the transaction-ingestion endpoint (service-token JWT — see §1's frozen contract below for what that means concretely), and the mock-institution webhook receivers (HMAC-signed, not JWT). Every request is logged as an audit event where it touches a case (see SECURITY_AND_GOVERNANCE.md §4).

## 1. Intake & Ingestion — 🟢 REAL

```
POST /v1/complaints
  auth: public (rate-limited, captcha in production; none in prototype)
  body: { fraud_type, amount, victim_account_number, victim_phone, description, jurisdiction_hint }
  → 201 { complaint_id, incident_reference, status: "new" }
  side effect: hashes PII, creates Complaint + Account rows, emits complaint.created

POST /v1/transactions/ingest
  auth: service token (used identically by the synthetic harness today and a real bank
        adapter tomorrow — see ARCHITECTURE.md §9)
  body: { complaint_id, from_account_number, to_account_number, amount, channel, occurred_at,
          idempotency_key?, device_id?, ip_address?, originator_phone?, originator_vpa?,
          exit_channel_id? }
  → 202 { txn_id, hop_index }
  side effect: hashes accounts/device/IP/phone/VPA if new, appends Transaction, links entities,
               emits transaction.ingested then graph.updated

GET /v1/cash-out-points?bbox=...    -- public ATM/branch registry, for map base layer
  → 200 [ { point_id, lat, lon, h3_cell, cash_limit, cctv_flag, footfall_tier } ]
```

### 1a. `POST /v1/transactions/ingest` — contract (implemented in Phase 2A)

**[Amended at Phase 2A implementation time]** The Phase 1 closure pass froze this contract *without* per-transaction device/IP/phone/VPA fields, on the reasoning that AI_ML_ARCHITECTURE.md's Graph Builder input reads that metadata from `accounts`/`linked_entities` rows established once at account-creation time, not carried on every transaction. Phase 2A's own instructions explicitly required the fuller transaction structure (device, IP, phone, VPA, exit location) per-transaction — a deliberate, direct contradiction of the prior freeze, not an oversight, and resolved in favor of the newer, more specific instruction. Recorded here so the contradiction is visible rather than silently papered over: **the reasoning in the previous paragraph was wrong** — a real fraud transaction's device/IP/phone/VPA context is a property of *that specific transfer* (an account can transact from different devices at different times during layering), not a fixed property of the account, so capturing it per-transaction is the more accurate design. The table below reflects the amended, implemented contract.

This subsection exists so Phase 2 starts from a contract already checked for internal consistency against DATA_MODEL.md, AI_ML_ARCHITECTURE.md, and DEMO_ARCHITECTURE.md, rather than one improvised at implementation time.

**Field-by-field, cross-checked against `transactions` in DATA_MODEL.md §2:**

| Request field | Maps to | Resolution |
|---|---|---|
| `complaint_id` | `transactions.complaint_id` (nullable FK) | **Required on this endpoint**, even though the column itself is nullable (nullable to also allow the synthetic batch-mode seeder's reference-data transactions, which belong to no live complaint — see DEMO_ARCHITECTURE.md §2's "batch mode" and app/synthetic/generator.py). A transaction arriving with no known complaint context (a raw, uncorrelated bank-feed event) is explicitly ⚪ FUTURE — out of scope for the prototype's ingestion contract, not silently dropped or guessed at. |
| `from_account_number`, `to_account_number` | `transactions.from_account_id` / `to_account_id`, via `accounts.account_hash` | **Raw account numbers in, exactly like `POST /v1/complaints`'s `victim_account_number`** — hashed server-side at the same ingestion boundary (SECURITY_AND_GOVERNANCE.md §2), never pre-hashed by the caller. This is not a style choice: DEMO_ARCHITECTURE.md's core credibility mechanism ("the demo's fake data enters through the exact same door a real feed would," ARCHITECTURE.md §9) only holds if the synthetic harness has no privileged shortcut around the hashing step a real bank adapter would also go through. |
| `amount`, `channel`, `occurred_at` | direct columns | `channel` must be one of DATA_MODEL.md's `transactions.channel` enum (`upi`, `imps`, `neft`, `card`, `cash_withdrawal`) — **DEMO_ARCHITECTURE.md §3's example `demo_scenario_a_atm.yaml` was missing this field on each hop; corrected there to include it** (see below), so the documented scenario format actually satisfies this contract. |
| `hop_index` | `transactions.hop_index` | **Server-computed, never client-supplied** — the response's `hop_index` is the Graph Builder's BFS distance from the complaint's victim account (AI_ML_ARCHITECTURE.md §1), bounded at the configured max depth. Consistent with the response already being `{txn_id, hop_index}` rather than an echo of the request. |
| `idempotency_key` (optional) | `transactions.idempotency_key` (nullable unique) | Consistent with `POST /v1/complaints`'s idempotency handling. Unlike a complaint, a transaction has no natural unique key a retried bank-feed call could collide on (the same two accounts can legitimately transfer the same amount twice), so silently deduping by content is wrong — an explicit caller-supplied key is required for dedup to apply at all. **Reused-key-with-different-payload is a `409 Conflict`, not a silent overwrite or a silent accept of either payload** — the two idempotency semantics (replay vs. conflict) are distinguishable by comparing every other field against the stored row. |
| `device_id`, `ip_address`, `originator_phone`, `originator_vpa` (all optional) | `linked_entities` rows on the **from-account** (`entity_type` = device/ip/phone/vpa respectively) | **Amended field, see note above.** Raw values in, hashed server-side (`hash_pii`, same pepper as every other identifier) — never a pre-hashed value accepted as authoritative, same rule as the account numbers. Optional because a real bank feed won't always have all four; omitted fields simply create no `linked_entities` row for that transaction. |
| `exit_channel_id` (optional) | `transactions.exit_channel_id` (nullable FK to `exit_channels.channel_id`) | Identifies which *already-seeded* exit channel (ATM/exchange/merchant) this transaction cashed out through, when applicable. Must reference a real, existing `exit_channels` row (`404` if not) — the Graph Builder `MATCH`es this node, it never invents one; exit channels are reference data owned by the synthetic seeder / a future real registry feed, not something a transaction can create by naming it. |
| `hop_index` | `transactions.hop_index` | **Server-computed, never client-supplied.** Computed from Postgres alone (the source of truth — see §4 below), not from a Neo4j graph query: `1` if `from_account` is the complaint's victim account; otherwise `1 + max(hop_index)` among prior transactions in the same complaint that deposited into `from_account`; capped at the configured max depth (`settings.max_hop_depth`, default 6, matching AI_ML_ARCHITECTURE.md §1) rather than growing unbounded. |

**Auth — resolving "service token"**: no such mechanism existed before Phase 2A anywhere in SECURITY_AND_GOVERNANCE.md or the implemented RBAC matrix (`UserRole` before this phase was `citizen_portal | investigator | supervisor | bank_liaison | auditor | admin` — no `service` value). **Implemented in Phase 2A**: `UserRole.service` added, issued the same way every other role's JWT is (same `create_access_token` call, same claim shape — `sub`, `role`, no `jurisdiction_id`/`bank_id`), minted out-of-band via `scripts/mint_service_token.py` rather than through the interactive `/v1/auth/login` (there is no human to log in as the synthetic harness or a future bank adapter). One auth mechanism in the system — JWT + `require_roles(...)` — not a second, parallel scheme for machine callers. `require_roles(UserRole.service)` is the only dependency this endpoint accepts; no other endpoint accepts that role, and the service role can access no other endpoint (SECURITY_AND_GOVERNANCE.md §3).

**Event payload** (`transaction.ingested`, emitted after the Postgres commit): `{txn_id, complaint_id, from_account_hash, to_account_hash, amount, channel, hop_index, occurred_at}` — matches AI_ML_ARCHITECTURE.md §1's stated Graph Builder input (*"transaction records (from/to account hashes, amount, channel, timestamp)"*) field-for-field. `graph.updated` is emitted separately, after the Neo4j write attempt (§4 below), carrying `{complaint_id, node_count_delta, edge_count_delta}` — deliberately two events, not one, because the Postgres write and the Neo4j write are not one atomic operation (Neo4j failure never rolls back the Postgres row — see §4).

### 1b. Graph write semantics — Postgres is authoritative, Neo4j is best-effort-then-rebuildable

The Neo4j write happens **after** the Postgres commit, in its own try/except: if Neo4j is unreachable or the write fails, the transaction is still fully persisted in Postgres (a real financial transaction record must never be lost because a derived intelligence store is down) and a warning is logged. `scripts/rebuild_neo4j_graph.py` exists precisely to recover from this drift — it rebuilds the entire graph from Postgres from scratch, so a Neo4j outage during ingestion is a recoverable operational event, not data loss. This is the concrete implementation of ARCHITECTURE.md's "Neo4j is a derived/rebuildable intelligence graph" for this endpoint specifically.

### 1c. Neo4j node/relationship types created (Phase 2A scope only)

| Element | Shape | Written by |
|---|---|---|
| `(:Complaint {complaint_id})` | node | `ensure_complaint_victim_link`, once per complaint |
| `(:Account {account_hash})` | node | every transaction (`MERGE`, both sides) |
| `(:Device {device_hash})`, `(:Phone {phone_hash})`, `(:IP {ip_hash})`, `(:VPA {vpa_hash})` | nodes | when the corresponding optional field is present on a transaction |
| `(:ExitChannel {channel_id, channel_type, h3_cell, lat, lon})` | node | synced from Postgres `exit_channels` (`MATCH`ed, never created, by the ingestion path — only the rebuild script's `sync_exit_channel` step creates/updates these) |
| `(:Complaint)-[:INVOLVES]->(:Account)` | relationship | once per complaint, to the victim account |
| `(:Account)-[:TRANSFERRED_TO {txn_id, amount, channel, hop_index, occurred_at}]->(:Account)` | relationship | every transaction, skipped if `hop_index` would exceed `max_hop_depth` (bounded traversal — see §1a) |
| `(:Account)-[:HAS_DEVICE]->(:Device)`, `(:Account)-[:HAS_PHONE]->(:Phone)`, `(:Account)-[:HAS_IP]->(:IP)`, `(:Account)-[:HAS_VPA]->(:VPA)` | relationships | when the corresponding field is present, from the transaction's `from_account` |
| `(:Account)-[:EXITED_VIA {amount, occurred_at}]->(:ExitChannel)` | relationship | when `exit_channel_id` is present, from the transaction's `to_account` |

**Explicitly not created in Phase 2A** (per this phase's scope): `SHARES_DEVICE_WITH`, `SHARES_PHONE_WITH`, `LINKED_TO_CASE`, `HISTORICALLY_EXITED_VIA`, `MEMBER_OF_RING`/`:Ring` nodes. DATA_MODEL.md §3's original schema description called `SHARES_DEVICE_WITH` "derived from shared Device node" — Phase 2A builds the raw structure (`HAS_DEVICE` edges) that *makes that derivation possible*; computing the derived sharing/ring relationships themselves is Ring Detector / Louvain work (Phase 2B), deliberately not built now.

## 2. Case & Approval — 🟢 REAL

```
GET  /v1/cases?jurisdiction_id&status&assigned_to_me     -- role/jurisdiction-scoped
  → 200 [ { complaint_id, fraud_type, amount, status, filed_at, top_risk_cell, top_probability } ]

GET  /v1/cases/{complaint_id}
  → 200 { complaint, latest_prediction, graph_summary, deployment_history }

POST /v1/cases/{complaint_id}/assign
  body: { investigator_id }  → 200

POST /v1/cases/{complaint_id}/close
  body: { reason }  → 200
```

## 3. Intelligence — 🟢 REAL orchestration over 🔵 ML-PROTO / 🟡 ALGO stages

```
GET /v1/cases/{complaint_id}/graph
  → 200 { nodes: [...], edges: [...], rings: [ { ring_id, member_accounts, cohesion_score } ] }
  -- backs AI_ML_ARCHITECTURE.md §1–2's graph view

GET /v1/cases/{complaint_id}/prediction         -- latest, or ?prediction_id= for a specific run
  → 200 {
      prediction_id, generated_at,
      exit_vector: { bearing_deg, distance_range_km, confidence_cone_deg, exit_channel_type },
      ranked_locations: null,        -- Phase 2D (Exit-Channel + Time-Window Scorer, §4) not yet
                                      -- built - explicitly null, never a fabricated or placeholder
                                      -- list, so a client can distinguish "not computed yet" from
                                      -- "computed, zero results"
      model_versions: { ring, corridor, exit_channel: null, time_window: null },
      disclaimer: "This is an investigative lead based on automated pattern analysis, not a
                   definitive determination of wrongdoing."
    }
  -- backs AI_ML_ARCHITECTURE.md §3 only as of Phase 2C (corridor/exit-vector prediction);
  -- §4's ranked_locations/exit-channel scoring is Phase 2D, not yet implemented - this response
  -- shape is the frozen, honest Phase 2C contract, not a preview of Phase 2D's eventual shape.
  -- `channel_type` inside `exit_vector.exit_channel_type` is one of atm_cash/crypto_p2p/
  -- ecommerce_merchant (PRODUCT_EXPERIENCE.md §7), derived heuristically from any exit channels
  -- already observed among the ring's members (majority vote, default atm_cash if none) - not a
  -- trained classifier; that level of exit-channel prediction is Phase 2D's job (§4), not this
  -- stage's. `optimize-deployment` below cannot run yet without Phase 2D's channel-type scoring -
  -- this is documented, not silently broken.
  -- SECURITY_AND_GOVERNANCE.md §6 requires the `disclaimer` field on every response where a
  -- prediction appears - previously named there but missing from this contract; now reconciled.

GET /v1/cases/{complaint_id}/explanation?prediction_id=&exit_channel_id=
  → 200 {
      top_factors: [ { feature, weight, direction } ],
      graph_path: [ node_ids... ],
      comparable_cases: [ { complaint_id, similarity_score, summary } ],
      plain_language: "Ranked #1 because..."
    }
  -- backs AI_ML_ARCHITECTURE.md §6

GET /v1/jurisdictions/{jurisdiction_id}/risk-field?at=<timestamp>
  → 200 { h3_cells: [ { h3_cell, score } ], generated_for: <timestamp> }
  -- backs AI_ML_ARCHITECTURE.md §5; the `at` param drives historical replay
```

## 4. Intervention Optimization & Action — 🟡 ALGO / 🟠 SIM

```
POST /v1/cases/{complaint_id}/optimize-deployment
  -- mode auto-selected server-side from the top-ranked exit channel's intervention_action_type
  -- (AI_ML_ARCHITECTURE.md §7); the caller supplies whichever constraint applies to that mode
  body (coverage_maximization / atm_cash): { team_count, team_locations: [ {lat,lon} ] }
  body (resource_allocation / crypto_p2p, ecommerce_merchant): { request_slot_count }
  → 200 {
      deployment_id, optimizer_mode,
      assignment: [ { team_id, exit_channel_id, expected_coverage, travel_time_min } ]
        -- coverage_maximization shape; resource_allocation returns
        -- [ { exit_channel_id, priority_rank, expected_value, hazard_at_request_time } ] instead,
      expected_coverage_total, naive_baseline_coverage
    }
  -- re-callable with a different constraint; each call is a new deployment_id (never overwritten)

POST /v1/deployments/{deployment_id}/decision
  auth: investigator or supervisor only
  body: { decision: "approved" | "rejected", justification }
  → 200
  side effect: emits intervention.approved or intervention.rejected, writes audit event, if approved triggers Action module (which emits action.dispatched)

POST /v1/deployments/{deployment_id}/outcome
  body: { result, notes }
  → 200
  side effect: emits intervention.outcome, writes FeatureSnapshot label row (feeds retraining)

GET /v1/alerts?jurisdiction_id | GET /v1/alerts/{alert_id}
  → 200 { channel, recipient_ref, payload, sent_at, delivered_at, read_at }
```

Alert payload sent to the mock bank/I4C receivers (🟠 SIM endpoint, real payload shape):
```json
{
  "alert_id": "...",
  "complaint_id": "...",
  "issued_by_jurisdiction": "...",
  "risk_summary": "87% probability of cash withdrawal at H3 cell ... within 30-60 min",
  "recommended_action": "flag_account_for_review",
  "evidence_ref": "/v1/cases/{id}/explanation?...",
  "requires_human_approval": true,
  "signature": "HMAC-SHA256(...)"
}
```

## 5. Audit & Governance — 🟢 REAL

```
GET /v1/audit/events?subject_id=&from=&to=      -- auditor/admin only
  → 200 [ { event_id, seq_no, event_type, actor_id, occurred_at, this_hash } ]

GET /v1/audit/verify-chain?from_seq=&to_seq=
  → 200 { valid: true|false, broken_at_seq: null | <seq_no> }

GET /v1/models
  → 200 [ { model_id, stage, version, trained_at, metrics, is_active } ]
```

## 6. Auth

```
POST /v1/auth/login        body: { email, password } → { access_token }
```
**[Simplified after product review — PRODUCT_EXPERIENCE.md §8.2]** A single moderate-TTL (few hours) access token, no refresh endpoint and no server-side revocation list, for the prototype — a judged demo runs a handful of known accounts for minutes, not sessions across days. Refresh-token rotation + revocation is named as a stated production requirement, not silently dropped: production reintroduces `POST /v1/auth/refresh` backed by a real session store once that store exists for other reasons.

JWT claims: `{ sub: user_id, role, jurisdiction_id, bank_id, exp }`. Every non-public endpoint's handler resolves scope from these claims server-side — the client never supplies `jurisdiction_id` as a trusted filter.

## 7. WebSocket

Event names match the canonical sequence in [PRODUCT_EXPERIENCE.md §4](PRODUCT_EXPERIENCE.md) exactly — that table is the authoritative producer/consumer/DB/UI mapping; this is just the wire shape.

```
WS /v1/ws?jurisdiction_id=<id>            -- auth via token query param or subprotocol header
  server → client events:
    { type: "complaint.created", complaint_id, status }
    { type: "intelligence.started", complaint_id, status }
    { type: "graph.updated", complaint_id, node_count, edge_count }
    { type: "exit_prediction.completed", complaint_id, bearing_deg, distance_range_km, exit_channel_type }
    { type: "spatiotemporal_prediction.completed", complaint_id, prediction_id, top_probability, time_window_min }
    { type: "risk_field.updated", jurisdiction_id, changed_cells: [...] }
    { type: "explanation.generated", complaint_id, prediction_id }
    { type: "intervention.recommended", complaint_id, deployment_id, expected_coverage_total }
    { type: "approval.required", complaint_id, deployment_id }
    { type: "intervention.approved" | "intervention.rejected", complaint_id, deployment_id }
    { type: "action.dispatched", complaint_id, alert_id, channel }
    { type: "outcome.recorded", complaint_id, deployment_id, result }
    { type: "feedback.created", complaint_id, feature_snapshot_id }
```
One connection per investigator session; server enforces the same jurisdiction scoping as REST — a client cannot subscribe to a jurisdiction outside its claim.

## 8. Error shape (consistent across all endpoints)

```json
{ "error": { "code": "FORBIDDEN_JURISDICTION", "message": "...", "request_id": "..." } }
```
`request_id` is included in the corresponding audit event where applicable, so a judge (or a real investigator) can trace a UI error back to a specific audit row.
