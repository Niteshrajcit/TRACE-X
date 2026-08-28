# TRACE-X — Product Experience

> This document is the product/UX companion to [ARCHITECTURE.md](ARCHITECTURE.md), [AI_ML_ARCHITECTURE.md](AI_ML_ARCHITECTURE.md), and [DATA_MODEL.md](DATA_MODEL.md). Where it changes a prior technical decision, the change is stated explicitly with a reason, and the source doc has been updated to match (see the diff notes at the end of each section marked **[updates applied]**). Visual language lives in [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md). The judge-facing script lives in [JUDGE_DEMO.md](JUDGE_DEMO.md).

---

## 1. The locked core journey

This is now the spine of the product. Every screen, every event, every demo scenario exists to serve this one journey — nothing is built that doesn't sit on this path or directly support it.

```
CITIZEN                                    INVESTIGATOR
  │                                              │
  ├─ opens Complaint Portal                      │
  ├─ submits complaint                           │
  ├─ receives incident ID  ─────────────────────►│ new incident appears in Command Center
  │  (complaint persisted immediately)           │   LIVE, no refresh
  │                                              ├─ opens the incident → Incident Workspace
  │                                              ├─ watches intelligence pipeline execute
  │                                              │   (progress steps ticking live, §4)
  │                                              ├─ sees fraud intelligence graph build
  │                                              ├─ sees predicted exit vector appear
  │                                              ├─ sees where + when prediction
  │                                              ├─ sees dynamic risk field on the map
  │                                              ├─ opens explanation — sees why
  │                                              ├─ sees optimized intervention recommendation
  │                                              ├─ approves / rejects
  │                                              ├─ sees the action event fire
  │                                              ├─ records the outcome
  │                                              ├─ sees the audit trail for this incident
  │                                              └─ sees "feedback returned to learning system"
```

Everything downstream of "submits complaint" happens on **one screen** — the Incident Workspace (§3) — not eight disconnected dashboard pages the investigator has to tab-hunt through. This is the single most important product decision in this document, because it's the difference between "a demo of eight AI features" and "an investigator using one tool."

---

## 2. Information architecture — navigation & screens

Five top-level destinations (not eight — see the note after the table). Everything intelligence-related lives *inside* one destination, the Incident Workspace, as tabs within a persistent shell — not as separate routes a user navigates away and back through.

| # | Screen | Route | Primary user | Purpose | Real/Sim content flag |
|---|---|---|---|---|---|
| 01 | **Citizen Complaint Portal** | `/report` (public, no login) | Citizen | Submit a complaint, get an incident reference, check status by reference | 🟢 REAL form, stands in for NCRP |
| 02 | **Investigator Command Center** | `/console` | Investigator, Supervisor | Live incident feed for their jurisdiction, filter/sort/search, jurisdiction-wide risk overview strip | 🟢 REAL |
| 03 | **Incident Workspace** | `/console/incidents/:id` | Investigator, Supervisor | The central investigation environment — see §3 | Mixed, labeled per-panel |
| — | *(04–08 below are tabs inside the Incident Workspace, not separate routes)* | | | | |
| 04 | Fraud Intelligence Graph | tab: `#graph` | within Workspace | Mule-network visualization | 🟢 REAL / 🔵 ring detection |
| 05 | Exit Prediction | tab: `#prediction` | within Workspace | Exit vector + where/when | 🔵 ML-PROTO |
| 06 | Spatio-Temporal Risk Map | tab: `#map` | within Workspace | Dynamic risk field, geospatial | 🟡 ALGO fused, 🔵 scored |
| 07 | Intervention & Approval | tab: `#intervention` | within Workspace | Optimizer output, approve/reject | 🟡 ALGO + 🟢 gate |
| 08 | Outcome / Audit / Learning | tab: `#audit` | within Workspace | Timeline, audit events, outcome form, feedback confirmation | 🟢 REAL |
| — | **Alert Inbox** (bank/I4C mock personas) | `/inbox` | Bank liaison | Receives alerts naming their own org only | 🟠 SIM |
| — | **Audit & Model Registry** | `/admin/audit`, `/admin/models` | Auditor/Admin | Cross-jurisdiction audit search, chain verification, model version history | 🟢 REAL |

**Why 04–08 are tabs, not routes**: the brief warns against turning every intelligence layer into "a disconnected dashboard page." A route change reloads context and breaks the investigator's mental model of "I am looking at *this* incident." Tabs inside one persistent Incident Workspace shell keep the complaint, the graph, the map, and the approval control all one Alt-Tab away from each other, sharing the same header (incident ID, status, risk headline) at all times — see §3's layout.

**Navigation shell**: left rail with the five top-level destinations (icon + label, collapsible), persistent top bar showing role, jurisdiction, and connection status ("Live" indicator — see DESIGN_SYSTEM.md §9 for its exact states). No mega-menus, no nested dropdown navigation — a command center rewards speed, not exploration.

---

## 3. The Incident Workspace

This is the product. Everything else is a doorway into it.

### 3.1 Information hierarchy (what's visible immediately vs. progressively revealed)

**Tier 0 — Always visible, top of screen, never scrolls away (sticky header):**
- Incident ID, fraud type, amount, filed-at time
- Current pipeline status (`New → Building Graph → Predicting → Ready → Action Recommended → Closed`) as a live progress strip, not a static label
- The single headline number once available: *"87% probability · cash-out in 30–60 min · [channel type icon]"*
- Primary action button, contextual to state (`Review Recommendation`, `Awaiting Approval`, `Record Outcome`)

**Tier 1 — The main body, default tab (`#prediction`, becomes default once a prediction exists; `#graph` is default before that):**
- Exit vector summary card (direction, confidence, exit channel type)
- Predicted location/channel + time window, shown as a compact card, not the full map
- A condensed risk map preview (not full-screen) — clicking expands to the `#map` tab
- Top explanation factors (top 3 only) with a "see full evidence" link into deeper explanation

**Tier 2 — One click away, via tabs (progressive disclosure of technical depth):**
- `#graph` — full interactive fraud graph, ring highlighting, hop distances, sibling-case links
- `#map` — full H3 risk surface, time slider, corridor/exit overlay, historical replay
- `#intervention` — team-count control, optimizer output, naive-baseline comparison toggle, approve/reject controls with mandatory justification field on reject
- `#audit` — chronological timeline of every event on this incident (mirrors §4's event list) plus the outcome-recording form once a decision has been acted on, plus a "feedback recorded" confirmation once an outcome closes the loop

**Tier 3 — Deepest technical detail, revealed only on explicit request (never auto-shown):**
- Raw feature vector values behind a prediction (SHAP contribution table beyond the top 3)
- Full model version metadata (`model_version_ring`, `_corridor`, `_location`, `_time_window`)
- Raw graph path node IDs / Cypher-level detail
- Hash-chain values for individual audit rows

This tiering is the direct answer to "the most important information should be visible immediately, deep technical information should be progressively revealed" — an investigator glancing at the header for two seconds gets the decision-relevant headline; a judge who wants to probe legitimacy can drill to Tier 3 without that clutter ever being on-screen by default.

### 3.2 Layout — a single case, five zones

```
┌─────────────────────────────────────────────────────────────────────┐
│ STICKY HEADER: incident ID · status strip · headline · primary CTA  │
├───────────────┬─────────────────────────────────┬───────────────────┤
│ LEFT RAIL      │  MAIN TAB CONTENT               │ RIGHT PANEL       │
│ (complaint +   │  (whichever of graph/prediction/ │ (contextual,      │
│  txn summary,  │   map/intervention/audit is      │  changes per tab: │
│  always        │   active — this is the "deep"    │  explanation      │
│  present,      │   area, Tier 1–2 content lives    │  evidence on      │
│  collapsible)  │   here)                           │  prediction/map;  │
│                │                                   │  response units   │
│ - victim acct  │                                   │  on intervention; │
│   (hashed)     │                                   │  timeline preview │
│ - hop count    │                                   │  on audit)        │
│ - amount/type  │                                   │                   │
│ - intelligence │                                   │                   │
│   status chips │                                   │                   │
└───────────────┴─────────────────────────────────┴───────────────────┘
```
The **left rail** (complaint + transaction summary) never disappears regardless of which tab is active — an investigator should never lose sight of *whose* case this is while exploring the graph or map. The **right panel** is contextual: it always carries the "why" (explanation) alongside whatever "what" is in the main area, so evidence is never more than a glance away from the prediction it supports — this is the direct fix against a floating unexplained AI number.

---

## 4. The live experience — canonical event sequence

🟢 REAL mechanism throughout. This supersedes the shorter event list in the original [ARCHITECTURE.md §4](ARCHITECTURE.md) — the granular sequence below is what actually drives the Incident Workspace's live progress strip (§3.1, Tier 0), so each pipeline stage becomes a visible tick, not a silent black box the investigator waits on.

**[updates applied — see §8.1]**: the backend event bus changes from Redis Streams to an **in-process async event dispatcher** (a plain `asyncio`-based publish/subscribe registry inside the single FastAPI process). Reasoning is in §8. This does not change any event name, producer, or consumer below — only *how* the event physically travels, which is invisible to the product.

| Event | Producer | Consumer(s) | DB state change | WebSocket push | UI response |
|---|---|---|---|---|---|
| `complaint.created` | Intake module | Intelligence Orchestrator, Case module, WS gateway | Insert `complaints`, `accounts(victim)` | `{type, complaint_id, status:"new"}` | New card appears in Command Center feed; if already open, Workspace header shows status `New` |
| `intelligence.started` | Orchestrator (on receiving `complaint.created` or first `transaction.ingested`) | WS gateway | Update `complaints.status = 'graph_building'` | `{type, complaint_id, status:"graph_building"}` | Progress strip lights step 1; graph tab shows a loading skeleton, not a blank tab |
| `graph.updated` | Graph Builder | Orchestrator (triggers Ring Detector), WS gateway | Neo4j nodes/edges upserted; no Postgres change | `{type, complaint_id, node_count, edge_count}` | `#graph` tab animates new nodes/edges in; left-rail hop-count chip increments |
| `exit_prediction.completed` | Corridor/Exit-Vector Predictor | Orchestrator (feeds scorer), WS gateway | Insert into `feature_snapshots` (stage=corridor) | `{type, complaint_id, bearing_deg, distance_range_km, exit_channel_type}` | Directional cone/wedge animates onto the map preview; `#prediction` tab's exit-vector card populates |
| `spatiotemporal_prediction.completed` | Location/Exit-Channel + Time-Window Scorer | Orchestrator (feeds fusion), WS gateway | Insert `predictions` row (ranked_locations, time_window) | `{type, complaint_id, prediction_id, top_probability, time_window_min}` | Headline banner in sticky header populates with the real number; `#prediction` tab's location/time card fills in |
| `risk_field.updated` | Risk Field Fusion | WS gateway (jurisdiction-wide channel, not just this incident) | Update in-process risk-field cache (keyed by jurisdiction) | `{type, jurisdiction_id, changed_cells:[...]}` | `#map` tab hex layer recolors only the changed cells; jurisdiction-wide risk overview strip on Command Center updates for every connected investigator, not just this case's |
| `explanation.generated` | Explainer | WS gateway | Update `predictions.explanation` JSONB | `{type, complaint_id, prediction_id}` | Right panel's "why" section fills in top-3 factors; full evidence becomes clickable |
| `intervention.recommended` | Intervention Optimizer (auto-runs once a prediction exists, at a default team count; investigator can re-run with a different count) | WS gateway | Insert `recommended_deployments` row (`status='proposed'`) | `{type, complaint_id, deployment_id, expected_coverage_total}` | `#intervention` tab populates with assignment + naive-baseline comparison; sticky header CTA changes to `Review Recommendation` |
| `approval.required` | Case & Approval module (fires the instant a deployment is `proposed`) | WS gateway | No new row — this is a derived state, not stored | `{type, complaint_id, deployment_id}` | CTA becomes `Approve / Reject`; a badge appears on the Command Center card for this incident so it surfaces above cases with no pending decision |
| `intervention.approved` / `intervention.rejected` | Case & Approval module | Action module (only on approved), Audit module, WS gateway | Update `recommended_deployments.status`, `decided_by`, `decided_at` | `{type, complaint_id, deployment_id, decision}` | `#intervention` tab locks the decision in with actor/timestamp; `#audit` timeline gets a new entry live |
| `action.dispatched` | Action module (only follows an `approved` decision — see SECURITY_AND_GOVERNANCE.md §5's hard invariant) | Audit module, mock external receiver, WS gateway | Insert `alerts` row | `{type, complaint_id, alert_id, channel}` | `#audit` timeline shows "Alert sent to [Bank/I4C mock]"; Alert Inbox screen (bank liaison persona) gets its own live push |
| `outcome.recorded` | Case & Approval module (investigator submits outcome form) | Audit module, Feedback/Retraining job, WS gateway | Insert `intervention_outcomes`; update `feature_snapshots.label` | `{type, complaint_id, deployment_id, result}` | `#audit` tab shows the outcome; sticky header status becomes `Closed` |
| `feedback.created` | Feedback/Retraining pipeline (writes the labeled row; full re-training is a separate, non-live batch job — see AI_ML_ARCHITECTURE.md §8) | WS gateway, Audit module | Insert/confirm `feature_snapshots` row is retraining-eligible | `{type, complaint_id, feature_snapshot_id}` | `#audit` tab shows a final confirmation line: *"Outcome recorded as a training label for the next model update"* — this is the visible close of the loop the brief asks for |

Every row above writes at least one `audit_events` entry in addition to whatever domain table changes — the audit trail (§08 screen) is therefore a strict superset/reordering of this same event list, filtered to one incident, which is why `#audit`'s timeline and this table will always agree with each other in the demo.

---

## 5. The AI visualization contract

For every intelligence layer, exactly what the backend returns, what's shown, what's interactive, and what evidence backs it. This is the enforcement mechanism behind "the UI must never display an AI result that does not correspond to an actual backend result" — every row below names the literal API field (from [API_CONTRACT.md](API_CONTRACT.md)) driving the UI element next to it, so there is no UI element in this spec without a named data source.

| Layer | Backend returns | UI displays | Interaction | Explanation shown | Evidence |
|---|---|---|---|---|---|
| Fraud graph | `GET .../graph` → nodes, edges, rings | Force-directed graph, nodes colored by `ring_id`, victim highlighted | Click a node → side panel with account metadata (hashed), hop distance; click a ring → highlights all members | "N accounts in this ring, M already implicated in other cases" | Direct node/edge count from Neo4j, no synthetic overlay |
| Exit vector | `exit_prediction.completed` payload / `GET .../prediction` → `exit_vector` | Directional cone on the map, labeled with bearing + distance range | Hover cone → confidence percentage tooltip | "Predicted based on N hops covering X km in Y minutes toward this bearing" | Hit-rate-at-cone-width metric shown in Tier 3 detail, not hidden |
| Location + time | `GET .../prediction` → `ranked_locations` | H3 hex highlight for top cell(s), headline banner text, time-window pill | Click a ranked cell → opens explanation for *that* cell specifically (not just the top one) | Full explanation object (below) | `model_versions` field always shown in Tier 3 |
| Dynamic risk field | `GET .../risk-field?at=` | Colored hex layer across the jurisdiction, time slider | Drag time slider → replays `at` param against historical snapshots | Legend explaining the decay/fusion logic in one sentence, full formula in Tier 3 | Every visible cell's score is a real fused value — no illustrative/placeholder gradient ever ships |
| Explanation | `GET .../explanation` → `top_factors`, `graph_path`, `comparable_cases`, `plain_language` | Horizontal SHAP bar chart, graph path overlay, comparable-case mini-cards | Click a comparable case → opens that case's own Workspace (read-only if closed) | The `plain_language` sentence, generated not authored (AI_ML_ARCHITECTURE.md §6) | SHAP is exact for tree ensembles — stated once in Tier 3, not re-argued per screen |
| Intervention optimizer | `POST .../optimize-deployment` → `assignment`, `expected_coverage_total`, `naive_baseline_coverage` | Deployment pins on map with per-pin coverage contribution; toggle switch "Naive top-N ↔ TRACE-X optimized" | Change team count slider → re-POSTs, re-renders live | Coverage-gain percentage shown inline, not just in a report | Every pin's `expected_coverage_contribution` is the literal optimizer output |
| Audit/feedback | `GET /v1/audit/events?subject_id=` | Chronological timeline, one row per event | Click a row → expand to full payload + hash values | N/A (audit is the evidence layer itself) | Chain-verify button calls `GET /v1/audit/verify-chain` live, on demand |

---

## 6. The three data modes — UI representation

Per [PRODUCT.md §2](PRODUCT.md) and [DEMO_ARCHITECTURE.md §1](DEMO_ARCHITECTURE.md), three modes must be visually distinguishable without making the product look unfinished. The mechanism: a small, consistent **provenance chip**, never a big red "FAKE DATA" banner (which would look unfinished) and never silence (which would be dishonest).

| Mode | Chip label | Chip color/icon (see DESIGN_SYSTEM.md §4 for exact tokens) | Where it appears |
|---|---|---|---|
| **Demo / Synthetic** | `Synthetic data` | Neutral slate, small database icon | Anywhere a value traces back to `is_synthetic = true` — e.g. a small chip near the complaint header, and in the graph legend ("this network is generated for demonstration") |
| **Simulated External** | `Simulated — [Bank name] / I4C` | Amber outline, small broadcast icon | On every alert card, the Alert Inbox screen's own header, and the `action.dispatched` timeline entry |
| **Future Production** | `Not yet connected` (shown only where a real integration point exists in the design but isn't wired) | Muted outline, plug icon | Settings/admin screen listing planned integrations (NCRP live feed, bank core feed, I4C direct API) — deliberately *not* shown on the main investigator path, because an investigator mid-case doesn't need to see a roadmap item; an auditor/admin reviewing system capabilities does |

**Why this doesn't look unfinished**: the chip is small, consistently placed, and reads as a *provenance label* (like "Verified" or "Draft" in any serious enterprise tool) rather than a disclaimer. A government platform that's honest about data provenance reads as *more* credible, not less — this is the same argument PROJECT.md §16 already makes for the pitch, applied to pixels instead of words. The rule from DEMO_ARCHITECTURE.md §1 holds without exception: **no screen ever implies a live NCRP/I4C/bank/ATM connection that does not exist.**

---

## 7. The three demo scenarios

The brief requires genuinely different interventions, not a text swap over an identical pipeline. This requires one architectural generalization, applied now: **[updates applied — see §8.2 and DATA_MODEL.md]** the `cash_out_points` entity generalizes to **`exit_channels`**, carrying a `channel_type` that changes what "where" and "intervention" mean. All three scenarios still resolve to a geospatial anchor point (so the Risk Map tab is never empty), but the anchor means something different per channel, and the optimizer branches into a genuinely different algorithm per type.

| | **A — ATM Cash-Out** | **B — Crypto P2P Exit** | **C — E-commerce Exit** |
|---|---|---|---|
| Fraud pattern | UPI fraud → 2–3 mule accounts → physical ATM withdrawal | UPI fraud → mule account → P2P sale on a crypto exchange → off-ramp | UPI fraud → mule account → high-value goods/gift-card purchase on a marketplace |
| Graph shape | Short, fast hop chain, high velocity | Chain includes an `ExitChannel(type=crypto_p2p)` node with exchange KYC-tier attributes | Chain ends at a `ExitChannel(type=ecommerce_merchant)` node with order/SKU attributes |
| Exit vector meaning | Geographic bearing + distance toward likely ATM cluster | "Channel vector" — likelihood of routing to a small set of known exchange nodal accounts, geography is secondary | Merchant/category vector — likelihood of a specific marketplace + product category, geography is the delivery/pickup address |
| Where + when output | H3 cell + 30–60 min window | Exchange counterparty + narrower window (crypto off-ramps are typically faster) | Merchant + longer window (order processing/delivery lag) |
| Risk map anchor | ATM/branch coordinates (primary use case) | Exchange's nodal settlement bank branch coordinates | Delivery address or merchant fulfillment-center coordinates |
| Intervention type | **Physical team deployment** — coverage-maximization optimizer (AI_ML_ARCHITECTURE.md §7, unchanged) | **Exchange freeze-request** — a prioritization/knapsack problem: limited compliance-request slots ranked by expected-value-of-freezing-in-time given the hazard curve, not a travel-time coverage problem | **Merchant hold-request** — rank open orders by hazard + amount, request a shipment hold before dispatch |
| Approval action | "Approve team deployment to [H3 cell]" | "Approve freeze-request to [Exchange] for account [hash]" | "Approve hold-request to [Merchant] for order [ref]" |
| Action payload | Bank/I4C webhook (as originally specified) | Exchange compliance webhook (new mock receiver, same signed-webhook shape) | Marketplace merchant-ops webhook (new mock receiver, same shape) |
| Outcome options | prevented / occurred elsewhere / no activity / recovered | frozen in time / off-ramped before freeze / no activity | held before dispatch / shipped before hold / cancelled by buyer |

This is a genuine pipeline branch, not three copies of scenario A with different labels: the optimizer stage literally runs a different algorithm class (geographic set-cover vs. a ranked resource-allocation knapsack) depending on `channel_type`, which is exactly the kind of difference a technically literate judge will probe for and find real.

**Sequencing recommendation**: build and rehearse Scenario A completely first (it's the PS's literal example and exercises every pipeline stage in its original, simplest form). Scenarios B and C are additive — same pipeline skeleton, same Incident Workspace, only the exit-channel scorer's feature set and the optimizer's branch differ. If time runs short, A alone still satisfies the full locked journey in §1; B and C are the "we thought about generality" answer to a judge who asks "does this only work for ATMs?" — valuable, but correctly sequenced *after* A is solid.

---

## 8. Simplifications applied after this review (overengineering pass)

Full reasoning for each, following the brief's rule: **only remove/replace something if it fails to materially improve the demo, can't be implemented reliably, adds unnecessary operational complexity, or creates a credibility problem.** Anything not listed here was considered and kept — see §8.5.

### 8.1 Redis Streams event bus → in-process async dispatcher — **REMOVED from prototype scope**
Original ARCHITECTURE.md justified Redis Streams *against Kafka*, but never against the actually-relevant alternative: **no broker at all.** The prototype backend is one FastAPI process (ARCHITECTURE.md §1's own modular-monolith decision). An event published by the Intelligence Orchestrator and consumed by the WebSocket gateway are both function calls within that one process — routing them through a network hop to Redis and back adds a container, a connection pool, a failure mode ("Redis is down mid-demo"), and zero product value, since there is no second consumer process to justify a broker. Replacement: a plain `asyncio`-based publish/subscribe registry (a dict of topic → list of async callbacks) inside the backend. The synthetic harness and mock external receivers are unaffected — they were never Redis clients, they talk over real HTTP (ARCHITECTURE.md §9), which is unchanged. **Why this doesn't hurt the production story**: the interface (`publish(topic, payload)`) is identical; swapping the in-process registry for Redis Streams or Kafka when a second backend process actually exists is a one-file change, and that upgrade path is stated explicitly rather than silently dropped.

### 8.2 JWT refresh-token flow + Redis session denylist — **SIMPLIFIED for prototype**
A revocation-list-backed refresh flow exists to handle long-lived user sessions across days/weeks. A judged demo involves a handful of known accounts logged in for minutes. Prototype uses a single moderate-TTL access token (a few hours) with no refresh endpoint and no revocation list; the refresh flow is named in SECURITY_AND_GOVERNANCE.md as a stated production requirement, not quietly forgotten. This also falls out naturally from removing Redis (§8.1) — there's no longer an obvious place to store a denylist without adding infrastructure back for a feature the demo doesn't need.

### 8.3 Merkle-root blockchain anchoring — **explicitly decided: do not attempt in this phase**
This was left as an open question in the prior architecture pass. Decision now: **no.** A live testnet interaction is one more thing that can fail during a judged demo (network dependency on a public chain, gas/fee handling, key management for a hackathon team), and the theme is already honestly served by the real, working hash-chained ledger (SECURITY_AND_GOVERNANCE.md §4) — a judge who asks "is this really blockchain" gets a precise, defensible answer either way, and that answer doesn't require the anchoring to exist. It remains a named future paragraph, not a build target.

### 8.4 Two mock-receiver containers → **merged into one "mock external systems" service**
Originally `mock-bank-receiver` and `mock-i4c-receiver` were separate containers. With Scenario B/C (§7) adding exchange and merchant receivers, four near-identical tiny services would exist. Merged into one lightweight service exposing four routes (`/mock/bank`, `/mock/i4c`, `/mock/exchange`, `/mock/merchant`), each independently logging and independently visible in the Alert Inbox screen by `channel` — the demo's "watch the external system receive it" moment is unaffected, container count drops from a growing list to one.

### 8.5 Reviewed and explicitly kept (considered for removal, retained with reason)

| Component | Considered because | Kept because |
|---|---|---|
| **Neo4j** (separate graph DB) | Small graph size might fit in-memory NetworkX, avoiding a second database | The Fraud Intelligence Graph is a named top-level screen and one of the strongest "wow" moments in the locked journey (§1); Neo4j's traversal and (future) visualization tooling materially improves that screen, is reliably deployable in one Docker container, and creates no credibility problem — it fails all four removal tests |
| **PostGIS** | Jurisdiction polygon containment queries looked like unnecessary runtime cost | Kept, but **narrowed**: jurisdiction membership is now precomputed once at seed time (`h3_cell → jurisdiction_id` stored as a column) instead of a live polygon-containment join on every risk-field request — same database, smaller hot-path query. PostGIS itself stays, because distance/travel-time queries for the optimizer genuinely need it |
| **Cox survival model** (`lifelines`) for time-window | Might be simplified to empirical historical quantiles | Kept — it's one small, purpose-built library call, not infrastructure, and gives a real hazard curve rather than a bucketed guess; it doesn't fail any of the four removal tests |
| **ILP optimizer (OR-Tools)** as a "stretch" path | Ambiguous "maybe if there's time" status in the original plan created scope risk | Resolved, not removed: **greedy-only for this phase**, full stop — it already gives a provable approximation bound and sub-second re-optimization, which is what the live team-count-slider interaction (§3, §5) actually needs. ILP stays a named production paragraph, not a stretch task competing for time against demo polish |
| **Supervisor escalation flow** (USER_FLOWS.md Flow F) | Not part of the locked core journey in §1 | Role and RBAC entry kept (harmless, needed for the persona set), but the escalation *logic/UI* is deprioritized out of the build plan — it doesn't serve the primary journey and shouldn't compete for build time against it |
| **Five-role RBAC matrix** | Might be trimmed to just investigator + auditor for the demo | Kept in full — the bank-liaison Alert Inbox and the audit/admin views are both named screens in §2 and both appear in the judge demo (JUDGE_DEMO.md), so every role earns its place |
