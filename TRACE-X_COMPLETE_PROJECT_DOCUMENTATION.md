# TRACE-X — Complete Project Documentation

**Predictive Cybercrime Cash-Withdrawal Intelligence Platform**
Smart India Hackathon 2026 · Problem Statement SIH 26184 · Ministry of Home Affairs · Blockchain & Cybersecurity

> This document is the master explanation of TRACE-X — what it is, why it exists, how it works end to end, what has actually been built and verified, and what remains future scope. It is written from the actual implemented backend (independently verified against a real Docker stack — PostgreSQL+PostGIS, Neo4j, FastAPI) and the project's locked architecture documents in `docs/`, not from aspiration. Every claim in this document is labeled **COMPLETED**, **CURRENT PROTOTYPE SCOPE**, or **FUTURE SCOPE** so a reader never has to guess what is real.

---

## Table of Contents

1. [TRACE-X in Very Simple English](#part-1--trace-x-in-very-simple-english)
2. [The Project Idea as One Story](#part-2--the-project-idea-as-one-story)
3. [Complete Backend Explanation, Stage by Stage](#part-3--complete-backend-explanation-stage-by-stage)
4. [AI / ML Explanation](#part-4--ai--ml-explanation)
5. [Graph Explanation](#part-5--graph-explanation)
6. [Data Architecture](#part-6--data-architecture)
7. [End-to-End Example](#part-7--end-to-end-example)
8. [What the Investigator Should See](#part-8--what-the-investigator-should-see-intended-frontend)
9. [Three Primary SIH Deliverables](#part-9--three-primary-sih-deliverables)
10. [SIH Problem Statement Alignment](#part-10--sih-problem-statement-alignment)
11. [Security & Governance](#part-11--security--governance)
12. [Real-Time System](#part-12--real-time-system)
13. [What Has Actually Been Verified](#part-13--what-has-actually-been-verified)
14. [Completed vs Future — The Master Table](#part-14--completed-vs-future--the-master-table)
15. [What We Should Not Claim](#part-15--what-we-should-not-claim)
16. [Final System Block Diagram](#part-16--final-system-block-diagram)
17. [Final Project Summary](#part-17--final-project-summary)

---

## PART 1 — TRACE-X in Very Simple English

### What is TRACE-X?

TRACE-X is a system that takes a cybercrime complaint — the kind a citizen files after being defrauded online — and instead of just filing it away for a human to investigate later, it **actively figures out where the stolen money is likely to be withdrawn as cash, when that is likely to happen, and why**, and then helps a human investigator decide what to do about it, with every decision recorded and auditable.

### What problem does it solve?

When someone is defrauded through UPI, a fake investment app, or a phishing call, the stolen money doesn't sit still. It gets moved through a chain of "mule" bank accounts — accounts opened by people who are paid (or coerced) to let their account be used as a relay — before it is finally withdrawn as physical cash at an ATM, sold on a crypto exchange, or spent on goods. Once the cash is out of the banking system, there is no transaction to reverse and usually no account left to freeze. **The window to act is measured in minutes, and today the system only starts investigating after the complaint is filed — by which point the money is often already gone.**

### Why is looking at individual transactions not enough?

A single transaction — "₹95,000 moved from Account A to Account B" — tells you almost nothing on its own. It doesn't tell you if Account B is a one-off recipient or a serial mule account already used in five other frauds. It doesn't tell you if Account B and Account C, which look unrelated in a transaction table, are actually run by the same person because they share a phone number or a device. A spreadsheet of transactions is a list of facts; it is not a network.

### Why does a graph help?

A **graph** is just a way of storing "who is connected to whom, and how." Instead of a flat table, TRACE-X stores accounts, devices, phone numbers, and complaints as **nodes**, and the relationships between them (money transferred, same device used, same phone used) as **edges**. Once the data is a graph, questions that were nearly impossible in a spreadsheet become a straightforward traversal: *"Show me every account connected to this victim's money, no matter how many hops away."* This is exactly how real mule networks get discovered — not one transaction at a time, but as a connected cluster.

### Why do we need prediction?

Knowing the network today only tells you what has already happened. The actionable question an investigator actually needs answered is: **"Given this network's behaviour so far, where is the money going to surface next, and roughly when?"** If you can answer that even approximately — this general direction, this kind of exit channel, this general time window — you can alert a bank, position a response team, or ask an exchange to hold a withdrawal *before* it happens instead of writing a report about it *after*.

### How does this move cybercrime investigation from reactive to proactive?

| Today (reactive) | TRACE-X (proactive) |
|---|---|
| Complaint filed → an investigator manually starts looking | Complaint filed → the system automatically builds the network and starts scoring it |
| Money withdrawn → the trail goes cold | A predicted exit window exists → a team or institution can be alerted *before* the withdrawal |
| "Something suspicious happened" | "Here is the network, here is where it's probably headed, here is why, and here is the recommended response" |
| A wrong guess costs nothing because there was no guess | A wrong prediction costs a wasted team-hour — never an accusation, because nothing happens without a human's explicit approval |

### A simple worked example

> A victim loses ₹1,25,000 to a fake investment scheme. The money lands in Mule Account A, moves to Mule Account B, then to Mule Account C. TRACE-X notices that Accounts B and C were also used in a phone-linked device with two other recent complaints — that's the "ring." It looks at how fast and how far the money is moving to predict a rough direction and distance ("the money is heading roughly north-east, likely surfacing 3–7 km away"). It then scores actual candidate ATMs/exchanges/merchants in that direction against a time window ("most likely within the next 30–60 minutes"). It shows an investigator *why* it thinks so — the actual contributing factors — and recommends where to send the two available response teams for maximum coverage. A human investigator reviews this and approves or rejects it. Only after approval does an alert go out. The outcome (did it work?) is recorded and feeds back into the system's own track record.

That is TRACE-X in one paragraph. Everything else in this document is the detail behind each of those steps.

---

## PART 2 — The Project Idea as One Story

The system is one continuous pipeline. Every stage below is covered in full technical detail in **Part 3**; here is the narrative shape of it, complaint to audit.

```
COMPLAINT
   ↓
TRANSACTIONS  (the money's actual movement, hop by hop)
   ↓
NETWORK  (accounts + shared devices/phones become one connected graph)
   ↓
RING  (which cluster of accounts is acting together)
   ↓
CORRIDOR  (which general direction + distance the money is moving)
   ↓
EXIT PREDICTION + TIME WINDOW  (which real ATM/exchange/merchant, and roughly when)
   ↓
RISK  (how this fuses into the jurisdiction's live risk map)
   ↓
EXPLANATION  (why the system believes what it believes)
   ↓
INTERVENTION  (what deployment/action would help most, given limited resources)
   ↓
APPROVAL  (a human decides — nothing happens automatically)
   ↓
ACTION  (the approved alert is actually sent, to a channel appropriate to the case)
   ↓
OUTCOME  (what actually happened, recorded honestly)
   ↓
AUDIT / FEEDBACK  (every step is permanently logged; the outcome becomes a future training signal)
```

For every stage, this document gives both a **Simple explanation** (what's happening, in plain words) and a **Technical explanation** (what the system is actually doing internally) — because the goal is for this document to work for a judge, a teammate, and an engineer, all at once.

---

## PART 3 — Complete Backend Explanation, Stage by Stage

Everything in this section is **COMPLETED** and independently verified against a real PostgreSQL+PostGIS and Neo4j Docker stack — not just unit-tested against a mock. Each stage names the actual libraries, actual database tables, and actual event names used in the running system.

### 2A — Ingestion & Graph Builder

**Simple explanation:** This is the front door. A citizen's complaint comes in, and every subsequent money-movement transaction reported for that complaint gets recorded and turned into a small piece of a bigger network graph.

**Technical explanation:**
- **Input:** `POST /v1/complaints` (public, unauthenticated — stands in for a citizen intake portal / NCRP) and `POST /v1/transactions/ingest` (authenticated with a dedicated `service` JWT role, used by a bank/NCRP-style feed).
- **Processing:** Raw account numbers, phone numbers, device IDs, IPs, and VPAs are **hashed at the ingestion boundary** (SHA-256 with a server-side pepper) — the raw values never touch any downstream table. A `hop_index` (distance from the victim's own account) is computed **server-side, from PostgreSQL alone**, bounded at a configurable max depth (default 6) so graph traversal cost never grows unbounded.
- **Database:** PostgreSQL is authoritative — `complaints`, `accounts`, `transactions`, `linked_entities` tables. Neo4j is written **after** the PostgreSQL commit, in a best-effort step: `Account`, `Device`, `Phone`, `IP`, `VPA` nodes and `TRANSFERRED_TO` / `HAS_DEVICE` / `HAS_PHONE` / `HAS_IP` / `HAS_VPA` / `EXITED_VIA` relationships. If Neo4j is briefly unreachable, the real financial record in Postgres is never lost — the graph is fully rebuildable from Postgres at any time.
- **Events produced:** `complaint.created`, `transaction.ingested`, `graph.updated`.
- **Why it matters:** Every later stage depends on this being correct and honest — PII never leaking downstream, and the graph never silently diverging from the real transaction ledger.

### 2B — Ring Intelligence

**Simple explanation:** This is where the system asks, "which accounts are actually working together as one criminal operation, even if they don't obviously look connected?"

**Technical explanation:**
- **Input:** The account graph built in 2A, restricted to accounts within the bounded hop depth.
- **Processing:** **Louvain community detection** (`networkx`, deterministic via a fixed random seed) over a weighted, undirected projection of the graph. The edge weight formula is explicit and documented — direct transfers count once per transaction (repeated transfers are additive, not deduplicated), shared device/phone/VPA usage is weighted 2×, shared IP is weighted 1× (because shared public IPs are common between genuinely unrelated people, so it's deliberately the weakest signal). This is **unsupervised clustering, not a trained classifier** — it finds dense clusters from structure alone, with no labelled "this is a ring" data required.
- **Output:** A `ring_id` per detected community, plus transparent, individually-reported features per ring — cohesion score, entity-sharing density, fan-in/fan-out amount ratio, transaction velocity, burst ratio, exit-channel concentration, geographic spread. **No single arbitrary "risk score" is fabricated here** — each signal is reported on its own.
- **Database:** `detected_rings` / `detected_ring_members` / `detected_ring_complaints` in PostgreSQL (the durable record); `MEMBER_OF_RING` relationships and `SHARES_DEVICE_WITH` / `SHARES_PHONE_WITH` / `SHARES_IP_WITH` / `SHARES_VPA_WITH` edges materialized as real, inspectable Neo4j relationships.
- **Events:** `ring.detected`.
- **API:** `GET /v1/complaints/{id}/rings`.
- **Why it matters to the investigator:** The single strongest predictor of what happens next is often not this complaint alone — it's a sibling account in the same ring that already cashed out somewhere last week. Only a graph surfaces that.

### 2C — Corridor / Exit-Vector Predictor

**Simple explanation:** Given how the money has moved so far — how many hops, how fast, in what direction — this stage predicts a rough direction and distance for where it's headed next, like a compass bearing rather than a pinpoint.

**Technical explanation:**
- **Input:** The ring's hop sequence (account-to-account transitions, each with amount, channel, elapsed time, and each account's known geolocation).
- **Processing:** Engineered lag features (direction vector, distance per hop, velocity, channel-switch pattern) feed a **gradient-boosted classifier** (`scikit-learn`) over 8 discretized bearing buckets (N, NE, E, SE, S, SW, W, NW). This is a deliberately simpler, honest choice over a full sequence model (LSTM/Transformer), which would overfit at this data volume.
- **Output:** A predicted **exit vector** — bearing in degrees, an expected distance range in km, a confidence cone, and a channel-type guess (ATM cash / crypto P2P / e-commerce), persisted on the `predictions` table's `exit_vector` JSON field.
- **Evaluated on:** held-out synthetic corridors, reported as hit-rate at ±30° and ±60° cones — never a fabricated accuracy number.
- **Events:** `corridor_prediction.completed`.
- **API:** exposed as part of `GET /v1/complaints/{id}/prediction`.
- **Why it matters:** This narrows the search from "the entire city" to "this specific corridor," which is what makes the next stage's scoring computationally and practically sane.

### 2D — Exit-Channel + Time-Window Scorer

**Simple explanation:** Now that we know the general direction, this stage looks at the *actual* real ATMs, exchange accounts, or merchant channels in that direction and scores each one: how likely is *this specific* one, and roughly when?

**Technical explanation:**
- **Input:** The exit vector from 2C, restricted to real candidate `exit_channels` (real seeded ATM/branch/exchange/merchant location data) that are geographically plausible for that corridor.
- **Processing:** Two coupled, real trained models over one fused feature vector (transaction signals, historical signals, geographic signals, temporal signals, channel-specific attributes): an **XGBoost binary classifier** for `P(exit at this channel within horizon)`, and a **Cox proportional-hazards survival model** (`lifelines`) for the expected time-to-exit, converted into an actionable minute-range window.
- **Output:** A ranked list of `(exit_channel_id, h3_cell, channel_type, probability, time_window_min, confidence_interval)`, persisted on `predictions.ranked_locations`. **Critically, the exact feature vector behind every ranked candidate is now also persisted** (`predictions.feature_snapshot`) — this is what makes real, non-fabricated explanation possible three stages later.
- **Evaluated on:** top-K hit rate, time-window calibration, Brier score — computed per channel type, never a single misleading aggregate "accuracy."
- **Events:** `exit_prediction.completed`.
- **API:** `GET /v1/complaints/{id}/prediction` (full response, `ranked_locations` populated).
- **Why it matters:** This is the concrete, checkable "87% probability, 30–60 minutes" number an investigator actually acts on.

### 2E — Dynamic Risk Field Fusion

**Simple explanation:** Individual predictions are about one complaint. This stage combines *every active complaint's* predictions into one continuously-updating risk map for a whole jurisdiction, so an investigator can see "which parts of the city are hot right now" — not just their own case.

**Technical explanation:**
- **This stage is deliberately NOT machine learning.** It is a deterministic fusion formula: `risk(cell, t) = Σ score(cell, complaint) · decay(t − t_generated)`, where `decay` is a simple exponential half-life function. Overlapping complaints on the same H3 hex cell combine additively; risk that isn't realized fades over time.
- **Processing:** Lives entirely **in-process** — a plain Python dictionary (`risk_field_cache[jurisdiction_id]`), refreshed incrementally (only the touched H3 cells are recomputed) whenever a `transaction.ingested` event fires and a complaint's active predictions change. No Redis, no separate cache service — a deliberate architecture decision for a single-process prototype (see Part 6).
- **Output & API:** `GET /v1/jurisdictions/{id}/risk-field?at=<timestamp>` — the live surface, or, via the `at` parameter, a **historical replay**, deterministically re-derived from the durable `predictions` table (never a separate snapshot store).
- **Events:** `risk_field.updated`.
- **Why it matters:** This is what makes the risk map "continuously updated," not a static heatmap generated once a day.

### 2F — Explainability

**Simple explanation:** No investigator should ever act on a number they can't question. This stage answers, in plain language and with real evidence, "*why* did the system rank this location so high?"

**Technical explanation:**
- **Input:** The exact XGBoost model and exact feature vector (persisted in 2D) behind one specific ranked candidate, plus the real account-to-account graph from stage 2A/2B.
- **Processing:** `shap.TreeExplainer` computes **exact** Shapley values (not an approximation) for that specific prediction — the top contributing features with signed weights. A real Neo4j graph-path query traces the actual `TRANSFERRED_TO` chain from the victim account forward. A nearest-neighbor search over other resolved complaints' own persisted feature vectors surfaces comparable historical cases — honestly returning an empty list when no comparable case with real feature data exists yet, never a fabricated placeholder.
- **A deliberate, disclosed design decision:** because a predicted exit channel hasn't happened yet, TRACE-X **never invents a fake `EXITED_VIA` graph edge** to it. The real graph path stops at the last known real account; the predicted destination is returned as a clearly separate field, never merged into the real path.
- **Output:** `top_factors` (`{feature, weight, direction}`, direction derived deterministically from the SHAP sign), `graph_path`, `comparable_cases`, and a deterministic plain-language sentence built only from real computed values.
- **Events:** `explanation.generated`.
- **API:** `GET /v1/complaints/{id}/explanation`.
- **Why it matters:** "The model said so" is not evidence a court, a judge, or an investigator's own conscience will accept. A real SHAP attribution and a real graph path are.

### 2G — Intervention Optimizer

**Simple explanation:** If you only have two response teams but five risky-looking ATMs, which two locations actually cover the most risk — accounting for the fact that three of those ATMs might be close enough together that one team covers all three?

**Technical explanation:**
- **This is an optimisation algorithm, not machine learning.** No model is trained; it consumes the already-produced ranked predictions from 2D.
- **Two genuinely different algorithms**, branched automatically by the top-ranked candidate's real-world action type:
  - **Coverage maximization** (physical ATM team deployment): a classic **greedy maximum-coverage algorithm** — iteratively picks the candidate adding the most *uncovered* probability mass within a configurable team coverage radius, giving a provable (1 − 1/e) ≈ 63% approximation guarantee. Reported against a naive "just send teams to the top-N by score" baseline, so the investigator sees the actual coverage gain, not an assumed one.
  - **Resource allocation** (exchange freeze / merchant hold requests): a **ranked knapsack** — `expected_value = probability × amount_at_risk × urgency`, taking the top-N candidates by request-slot capacity.
- **Output & API:** `POST /v1/complaints/{id}/optimize-deployment` — persists a `recommended_deployments` row (`status='proposed'`), returns the assignment, `expected_coverage_total`, and the naive baseline for comparison. Re-callable with a different team count/slot count; every call creates a new row, never overwrites a previous recommendation.
- **Events:** `intervention.recommended`.
- **Why it matters:** This is the concrete answer to "you have limited people — where do you actually send them?" — not simply "here is a sorted list."

### Case & Approval

**Simple explanation:** A case needs an owner, and no automated recommendation should ever turn into a real-world action without a human explicitly saying yes.

**Technical explanation:**
- **Case management:** `POST /v1/complaints/{id}/assign` (validates the target user is a real investigator/supervisor in the *same jurisdiction* as the case), `POST /v1/complaints/{id}/close` (terminal state transition, reason recorded in the permanent audit trail).
- **The approval gate — a hard architectural invariant, not a UI nicety:** `POST /v1/deployments/{id}/decision`, restricted by role to **investigator or supervisor only** (narrower than every other endpoint — auditor/admin cannot approve). A deployment already decided cannot be re-decided (409 Conflict) — a decision, once made, is permanent and audit-visible, exactly like a real approval record should be.
- **Events:** `approval.required` (fires the instant a recommendation is proposed), `intervention.approved` / `intervention.rejected`.
- **Why it matters:** This is the literal mechanism behind "a wrong prediction costs a wasted team-hour, never an accusation" — nothing downstream can happen without this gate passing.

### Action & Alerting

**Simple explanation:** Once a human approves a deployment, the system actually sends the alert — to the right kind of receiver for the situation — and honestly records whether it was actually delivered.

**Technical explanation:**
- **Trigger:** entirely event-driven — subscribes to `intervention.approved` (never a separate "dispatch" button; this mirrors the documented architecture exactly: approval itself triggers the Action module).
- **Re-verifies the approval status itself**, server-side, before building any outbound payload — never trusting the event alone (the same hard invariant named above).
- **Builds a signed alert payload** (HMAC-SHA256, matching the documented shape: risk summary, recommended action, evidence reference, `requires_human_approval: true`) and sends it to the correct **prototype/mock receiver** based on the case type: `/mock/bank`, `/mock/i4c`, `/mock/exchange`, or `/mock/merchant` — each one genuinely verifies the signature and acknowledges receipt, exactly as a real integration endpoint would, just not connected to any real institution.
- **Never fabricates delivery:** the `alerts` table records `sent_at` always, and `delivered_at` only when the receiver genuinely acknowledged it — a receiver failure is honestly recorded as sent-but-undelivered, not silently marked successful.
- **Idempotent:** re-triggering never creates a duplicate alert for the same approved deployment.
- **Events:** `action.dispatched`.
- **Why it matters:** "Prototype" does not mean "fake." The signature verification, the audit trail, and the honest success/failure distinction are all real; only the receiving institution is simulated.

### Outcome / Feedback

**Simple explanation:** What actually happened after the alert went out? This gets recorded honestly, and it becomes a real, usable training signal for the future — not just a note in a file.

**Technical explanation:**
- **API:** `POST /v1/deployments/{id}/outcome` — records a real, structured result (`cash_out_prevented`, `cash_out_occurred_elsewhere`, `no_activity`, `funds_recovered_partial`, `funds_recovered_full`), restricted to an already-**approved** deployment, one outcome per deployment ever (a second attempt is a 409, never silently overwritten).
- **Feeds retraining honestly:** reuses the **exact same feature vector** 2D already persisted for the acted-upon exit channel and writes it, labeled with the real outcome, into the `feature_snapshots` table — the first real use of that table in the project. Never recomputes or fabricates a feature vector for this purpose.
- **Events:** `outcome.recorded`, and — only when a real feature snapshot was actually written — `feedback.created`.
- **Why it matters:** This is the literal mechanism behind "every wrong prediction becomes a training label that improves the model," made real rather than asserted.

### Audit + Model Surfaces

**Simple explanation:** Every meaningful action anyone takes in this system — filing a complaint, assigning a case, approving a deployment, dispatching an action, recording an outcome — is permanently, tamper-evidently logged. Anyone with the right authorization can look up that history and cryptographically prove it hasn't been altered.

**Technical explanation:**
- **The audit ledger:** a hash-chained, append-only PostgreSQL table (`audit_events`). Every row commits to the entire history before it — `this_hash = SHA256(prev_hash || payload || occurred_at || seq_no)` — the same core mechanism a blockchain uses, honestly described as tamper-*evident* (you can prove it was altered), not tamper-*resistant against the database operator themselves* (that would need external anchoring, which is explicitly not attempted in this prototype — see Part 15).
- **API:** `GET /v1/audit/events` (filterable by subject, with role-appropriate jurisdiction scoping), `GET /v1/audit/verify-chain` (recomputes every hash and reports the exact point of tampering if any exists — auditor/admin only), `GET /v1/models` (the model registry read surface — honestly returns an empty list today, since no phase has yet run a formal retraining job to register a model version; the table and the read endpoint exist and work correctly, waiting for real data).
- **Why it matters:** In a law-enforcement-adjacent system, "trust us" is not good enough. This is the mechanism that lets an auditor or a court independently verify that nothing was quietly altered after the fact.

---

## PART 4 — AI / ML Explanation

### Simple explanation

TRACE-X is not "one big AI model." It's a small pipeline of narrow, honest tools, each doing one job it's actually good at — the same way a real investigation uses different specialists rather than one person who claims to know everything.

### Technical explanation — what each component actually is

| Component | What it is | Learned from data? |
|---|---|---|
| **Louvain community detection** (2B) | Unsupervised graph clustering (`networkx`) | No — structural, no training data needed |
| **Gradient-boosted classifier** (2C) | `scikit-learn` classifier over 8 bearing buckets | Yes — trained on synthetic corridor examples |
| **XGBoost** (2D) | Binary classifier, `P(exit at this channel)` | Yes — trained on synthetic exit-channel examples |
| **Cox proportional-hazards model** (2D) | Survival analysis (`lifelines`), time-to-exit | Yes — fitted on synthetic timing data |
| **SHAP `TreeExplainer`** (2F) | Exact feature attribution over the already-fitted 2D model | No new training — derives from 2D's model |
| **Risk-field fusion** (2E) | Deterministic exponential decay formula | **Not ML at all** — no learned parameters |
| **Intervention optimizer** (2G) | Greedy maximum-coverage / ranked knapsack | **Not ML at all** — a classical optimisation algorithm |

### What is explicitly NOT AI/ML — stated plainly, because this matters for honest engineering credit

- **Graph construction (2A)** is deterministic ETL — upserting nodes and edges. It is software, not a prediction.
- **Risk-field fusion (2E)** is a fixed formula with a tunable half-life constant — no model is fit to data.
- **The intervention optimizer (2G)** is a textbook optimisation algorithm (maximum coverage / knapsack) — it does not learn from data, it computes an assignment given the numbers it's handed.
- **Approval** is a human decision. The system never approves its own recommendation.
- **Action dispatch** is an operational, rule-following system (build payload → sign → send → record) — no model runs here.
- **Audit** is governance/infrastructure — hashing and verification, not intelligence.

### Why the system doesn't use one big model

The target isn't a single label — it's a joint answer to "where, when, and why," which no single classifier honestly produces. Each stage hands a typed, checkable output to the next, so a weak stage (inevitable with synthetic training data) degrades the pipeline gracefully instead of hiding inside one opaque black box.

---

## PART 5 — Graph Explanation

### Simple explanation

Picture the money's journey as a chain of arrows:

```
Victim  →  Mule Account A  →  Mule Account B  →  Mule Account C  →  Possible Exit Channel
```

Now imagine that Mule Account B and Mule Account C, on paper, look like two unrelated accounts — different names, different banks. But both were opened with the **same phone number**, or both transacted from the **same device**. That single shared fact is often the strongest evidence that one person or group controls both accounts. A plain list of transactions would never surface that; a graph does, because a "shared phone" is just another kind of connection (edge) sitting right alongside "money transferred."

### Technical explanation

**Node types actually in the Neo4j graph today:** `Complaint`, `Account`, `Device`, `Phone`, `IP`, `VPA`, `ExitChannel`, `Ring`.

**Relationship types actually written by the running backend:**

| Relationship | Meaning | Written by |
|---|---|---|
| `(:Complaint)-[:INVOLVES]->(:Account)` | victim account link | 2A |
| `(:Account)-[:TRANSFERRED_TO]->(:Account)` | real, observed money movement | 2A |
| `(:Account)-[:HAS_DEVICE\|HAS_PHONE\|HAS_IP\|HAS_VPA]->(...)` | raw linkage per transaction | 2A |
| `(:Account)-[:EXITED_VIA]->(:ExitChannel)` | a **real, observed** cash-out | 2A, only when a transaction actually names an exit channel |
| `(:Account)-[:SHARES_DEVICE_WITH\|SHARES_PHONE_WITH\|SHARES_IP_WITH\|SHARES_VPA_WITH]->(:Account)` | derived common-control signal | 2B |
| `(:Account)-[:MEMBER_OF_RING]->(:Ring)` | detected community membership | 2B |

**Why ring detection matters:** it is the process (Louvain, described in Part 3/4) that turns "a pile of connected accounts" into "this specific cluster of accounts is very likely operating together," using real graph-theoretic signal (density, shared-entity ratio, fan-in/fan-out) rather than a guess.

**Why TRACE-X does NOT invent a predicted `EXITED_VIA` edge:** `EXITED_VIA` in this graph means "this money was actually, observably withdrawn here." A predicted future exit hasn't happened — writing a fake edge for it would corrupt the one thing that makes this graph trustworthy: every edge in it is real, or it doesn't exist. When the Explainer (2F) needs to show "where the money is predicted to go," it deliberately returns the real graph path (up to the last known real account) and the predicted destination as two separate, clearly labeled pieces of information — never merged into one dishonest edge.

---

## PART 6 — Data Architecture

### Simple explanation

Two databases are used because they are good at two different things: **PostgreSQL** is good at "give me the exact record for this case, reliably, forever" (like a bank's ledger); **Neo4j** is good at "show me everyone connected to this account, no matter how many steps away" (like a social network's friend-of-a-friend search). Using a spreadsheet-style database for deep network questions gets slow and awkward past 2–3 hops; using a graph database for "what is this complaint's exact amount" would be overkill. TRACE-X uses each one for what it's actually good at.

### Technical explanation

**What lives in PostgreSQL (+PostGIS) — the system of record:**
`users`, `jurisdictions`, `banks`, `complaints`, `accounts`, `transactions`, `linked_entities`, `exit_channels`, `predictions`, `recommended_deployments`, `alerts`, `intervention_outcomes`, `audit_events`, `model_registry`, `feature_snapshots`, `response_units`, `h3_cell_jurisdiction`. Every financial and case fact is authoritative here.

**What lives in Neo4j — the derived, rebuildable fraud graph:**
The node/relationship structure described in Part 5. Neo4j is **never** the only copy of anything — every node and edge in it is reconstructable from PostgreSQL's `transactions` and `accounts` tables via a real rebuild script. If Neo4j were wiped tomorrow, nothing would be permanently lost.

**Why both, together:** a transaction is written to PostgreSQL first (committed, durable) and to Neo4j second (best-effort). If the Neo4j write fails, the real financial record is never lost — it's just temporarily out of sync with the graph, which is a known, recoverable, and disclosed operational state, not silent data loss.

**Everything else lives in-process, in the one backend server:**
- The **live risk-field cache** (`risk_field_cache[jurisdiction_id]`, Part 3's 2E) — a plain Python dictionary.
- The **event dispatcher** — an `asyncio` publish/subscribe registry connecting every stage above to the next.
- The **WebSocket connection manager** — jurisdiction-scoped live push to connected investigators.

This is a deliberate architecture decision, not a shortcut: the prototype is one FastAPI process, so routing events through a network hop (Redis/Kafka) would add a container, a connection pool, and a live-demo failure mode for zero benefit at this scale. The interface (`publish(topic, payload)`) is broker-agnostic, so upgrading to Redis Streams or Kafka once a second backend process genuinely exists is a one-file change — named as the production upgrade path, not silently dropped.

### Simple textual architecture diagram

```
        Investigator / Citizen
                 ↓
        Frontend (React/TS)
                 ↓
   REST API  +  WebSocket (live push)
                 ↓
        TRACE-X Backend (FastAPI)
                 ↓
   Event Dispatcher + Intelligence Pipeline
        ↙                        ↘
PostgreSQL + PostGIS          Neo4j
(system of record:            (derived fraud graph:
 complaints, transactions,     accounts, devices, phones,
 predictions, deployments,     rings, real relationships)
 alerts, outcomes, audit)
        ↘                        ↙
     Predictions · Risk · Recommendations · Actions
                 ↓
        Audit Ledger + Feedback Labels
```

---

## PART 7 — End-to-End Example

> **Note:** this example follows the real shape of the system's actual output fields. Specific numbers below are **ILLUSTRATIVE** unless explicitly noted as a real value observed during this project's own verification runs.

### The scenario

A citizen reports: *"I lost ₹1,25,000 to a fake investment app that convinced me to transfer money via UPI."*

### Step 1 — Complaint (real field shape)
```json
{
  "victim_account_number": "raw number, hashed at the boundary — never stored raw",
  "amount": "125000.00",
  "fraud_type": "investment_scam",
  "incident_datetime": "2026-08-27T09:00:00+00:00",
  "jurisdiction_hint": "Chennai"
}
```
→ Returns a real, public incident reference (e.g. `TX-2026-2E10ABB2`, an actual example generated during this project's own verification).

### Step 2 — Transactions (real chain shape)
```
Victim → Mule A  (T1: ₹1,25,000)
Mule A → Mule B  (T2: ₹1,20,000)
Mule B → Mule C  (T3: ₹1,15,000)
```
Each hop is submitted via `POST /v1/transactions/ingest`, server-computes its own `hop_index`, and immediately triggers graph construction.

### Step 3 — Network discovered (ILLUSTRATIVE)
> Ring detected: 3 members, cohesion score 0.67, one shared device across two accounts.

### Step 4 — Corridor predicted (ILLUSTRATIVE, real field shape)
> Bearing: 42° (roughly north-east), distance range: 3–7 km, confidence cone: 30°, likely channel type: ATM cash.

### Step 5 — Exit + time window scored (ILLUSTRATIVE, real field shape)
> Top candidate: a real seeded ATM location, probability 0.65, time window 15–40 minutes, confidence interval [0.4, 0.8].

### Step 6 — Risk field
> This complaint's contribution fuses into Chennai Central's live jurisdiction-wide risk map — the affected H3 hex cells light up for every connected investigator watching that jurisdiction, not just this case.

### Step 7 — Explanation (real mechanism, illustrative values)
> Top factors: `past_exits_via_channel` (decreases risk), `distance_km` (decreases risk), `hop_count` (increases risk). Graph path: victim → Mule A → Mule B (a real, Neo4j-verified chain). Comparable cases: honestly empty if none exist yet with real comparable data.

### Step 8 — Intervention recommended
> `POST /v1/complaints/{id}/optimize-deployment` with 1 available team → coverage-maximization mode selected automatically (physical ATM deployment) → one real recommended deployment persisted, `expected_coverage_total` and a naive-baseline comparison returned.

### Step 9 — Human approval
> An investigator or supervisor in the same jurisdiction reviews the recommendation and calls `POST /v1/deployments/{id}/decision` with `{"decision": "approved", "justification": "..."}`. Nothing before this point has taken any real-world action.

### Step 10 — Action dispatched
> The moment approval is recorded, the system automatically builds a signed alert payload and sends it to the mock bank-webhook receiver. The receiver verifies the signature and acknowledges. `delivered: true` is recorded honestly — never assumed.

### Step 11 — Outcome recorded
> `POST /v1/deployments/{id}/outcome` with `{"result": "cash_out_prevented"}` — a real result, permanently recorded, and the exact feature vector behind this prediction is written as a labeled training row for future use.

### Step 12 — Audit trail
> The complete real sequence — `deployment.recommended → intervention.approved → action.dispatched → outcome.recorded` — sits as consecutive, cryptographically-chained rows in the audit ledger, independently verifiable at any time via `GET /v1/audit/verify-chain`.

---

## PART 8 — What the Investigator Should See (Intended Frontend)

> **Status: FUTURE SCOPE.** Everything in this section describes the **intended** design already locked in `docs/PRODUCT_EXPERIENCE.md`. The actual frontend today (see Part 14) is a minimal Phase-1 skeleton: a citizen complaint form, a login page, a live incident feed, and a basic incident detail view with no graph, map, prediction, explanation, intervention, or audit visualization yet. This section is the blueprint for what should be built next, not a description of what exists.

The intended experience is **one investigation screen**, not eight disconnected dashboard pages an investigator has to tab-hunt through.

| # | Screen | What the investigator sees | What they can do | Backend capability behind it |
|---|---|---|---|---|
| 1 | **Dashboard / Mission Control** | Live incident feed for their jurisdiction, a jurisdiction-wide risk overview strip | Filter/sort/search cases, jump into any incident | `GET /v1/complaints`, `risk_field.updated` over WebSocket |
| 2 | **Complaint / Case Intake** | The raw complaint as filed — victim details (hashed), amount, description | Assign the case to themselves or a colleague | `POST /v1/complaints`, `POST .../assign` |
| 3 | **Network Investigation** | The fraud graph — victim, mule accounts, shared-device links, animating in as hops are added | Click a node for details, click a ring to highlight all members | 2A/2B, `GET .../rings` |
| 4 | **Ring + Corridor Intelligence** | Ring cohesion/velocity/burst metrics; the predicted exit vector as a directional cone on a map | See the "watch the corridor ignite" moment live | 2B/2C |
| 5 | **Risk Heatmap** | The jurisdiction-wide H3 hex risk surface, with a time slider for historical replay | Scrub back in time to see how the risk looked minutes ago | 2E, `GET .../risk-field?at=` |
| 6 | **Exit Prediction + Explanation** | The headline number ("65% probability, 15–40 minutes"), and a click-through to the real SHAP factor chart + graph path + comparable cases | Understand *why*, not just *what* | 2D, 2F |
| 7 | **Intervention + Approval** | The optimizer's recommended deployment, a naive-vs-optimized coverage comparison, an approve/reject control with a mandatory justification field | Make the one human decision the whole system waits on | 2G, Case & Approval |
| 8 | **Action + Outcome + Audit** | The dispatched alert, its delivery status, the outcome form, and the full chronological audit timeline for this case | Record what actually happened; verify nothing was altered | Action & Alerting, Outcome, Audit |

This is a coherent investigation story — one incident, five zones of a single screen (sticky header, left rail with case summary, main tab content, contextual right panel for evidence) — not a list of raw API endpoints bolted onto a page each.

---

## PART 9 — Three Primary SIH Deliverables

### A. Predictive Analytics Engine

- **What SIH asks for:** AI/ML on historical cybercrime and financial data, pattern detection, geospatial risk modelling.
- **What TRACE-X already provides (COMPLETED, backend):** the full 2A→2E pipeline — graph-based pattern detection (Louvain), corridor prediction (gradient boosting), exit-channel + time-window scoring (XGBoost + Cox), and geospatial risk fusion (H3-indexed, jurisdiction-wide). All independently verified against a real Docker stack.
- **What the frontend will visually demonstrate (FUTURE SCOPE):** the graph animating live, the corridor cone, the ranked exit-channel list with real probabilities and time windows.
- **What remains future scope:** training on real (not synthetic) historical data — explicitly deferred, disclosed everywhere in this project's own documentation, and by design (real cybercrime data is restricted).

### B. Risk Heatmap Dashboard

- **What SIH asks for:** a GIS interface showing real-time/potential risk zones, filterable by time, location, and crime category.
- **What TRACE-X already provides (COMPLETED, backend):** `GET /v1/jurisdictions/{id}/risk-field?at=<timestamp>` — a real, continuously-updating H3 hex risk surface with historical replay, backed by a real fusion formula, not a static image.
- **What the frontend will visually demonstrate (FUTURE SCOPE):** the actual hex layer on a real map, a time slider, jurisdiction and category filters.
- **What remains future scope:** the map UI itself; the data source behind it already exists and works.

### C. Law Enforcement Interface

- **What SIH asks for:** a secure investigator interface for alerts, intelligence reports, and evidence documentation.
- **What TRACE-X already provides (COMPLETED, backend):** full RBAC/jurisdiction-scoped case APIs (list/detail/assign/close), the approval gate, the explanation API (the "evidence" layer), and the audit trail.
- **What the frontend will visually demonstrate (FUTURE SCOPE):** the eight-screen Incident Workspace described in Part 8.
- **What remains future scope:** the console UI itself; a minimal login + live-feed skeleton exists today, not the full workspace.

### Alert & Notification System (addressed separately, as instructed)

- **What SIH asks for:** real-time notifications to law enforcement, banks, and I4C via SMS, email, APIs, and dashboard triggers.
- **What TRACE-X already provides (COMPLETED, prototype-scope):** a real, working, event-driven, HMAC-signed dispatch mechanism, with genuine signature verification and honest delivery tracking, routed to the correct **mock** receiver (`/mock/bank`, `/mock/i4c`, `/mock/exchange`, `/mock/merchant`) based on the case type.
- **What remains future scope:** connecting those same signed-webhook receivers to real bank/I4C/SMS/email systems — an integration point, not an architecture change (the mock and a real receiver would accept the identical payload shape).

---

## PART 10 — SIH Problem Statement Alignment

| SIH requirement | How TRACE-X addresses it today |
|---|---|
| **Prediction of likely cash withdrawal locations** | 2C (corridor/direction) + 2D (specific ranked exit channels + time window) — real, working, independently verified |
| **Proactive cybercrime mitigation** | The entire pipeline runs automatically from the moment a transaction is ingested, ahead of any human request — the system does not wait to be asked |
| **Pattern detection** | 2B's Louvain-based ring detection over real graph structure |
| **Geospatial risk modelling** | 2E's H3-indexed, jurisdiction-wide dynamic risk field |
| **Real-time intelligence** | The full event chain (Part 12) pushed live over WebSocket, zero polling, verified firing in the correct order end to end |
| **Law enforcement coordination** | Case assignment, jurisdiction-scoped access, the audit trail |
| **Financial institution coordination** | The Action & Alerting module's bank-webhook channel — **currently a verified mock, not a real bank connection** |
| **Actionable intervention** | 2G's optimizer — a genuinely different algorithm class per scenario, not a relabeled sort |
| **Faster response** | The human-approval gate is the *only* step between a prediction and a real alert — everything before it is automatic |

**Being precise about "prototype" vs "production":** every stage above is a real, working implementation against real infrastructure (PostgreSQL, Neo4j, a real HMAC-signed webhook mechanism). What is explicitly *not* production yet is the data source (synthetic, not real historical cybercrime data — by necessity, since real data is restricted) and the receivers on the other end of an alert (mock, not a live bank/I4C connection). The architecture is built so that swapping either of those in is an integration change, not a redesign — a fact this project's own documents state repeatedly and this document repeats honestly rather than overclaims.

---

## PART 11 — Security & Governance

### Authentication & RBAC

**Simple explanation:** Not everyone who can log in can see or do everything. An investigator sees their own jurisdiction's cases; an auditor sees everything but can't approve anything; nothing happens without the right role.

**Technical explanation:** JWT-based auth (`sub`, `role`, `jurisdiction_id`, `bank_id`, `exp` claims). The RBAC matrix, enforced in code and independently verified live:

| Role | Can see | Can approve/reject | Can assign/close cases | Can view full audit log | Can view model registry |
|---|---|---|---|---|---|
| **Investigator** | Own jurisdiction | Yes | Yes | Own case's trail only | No |
| **Supervisor** | Own jurisdiction (+ subordinates') | Yes | Yes | Own case's trail only | No |
| **Auditor** | All (read-only) | No | No | Yes, full, cross-jurisdiction | Yes |
| **Admin** | All | No | Yes | Yes, full, cross-jurisdiction | Yes |
| **Service** (machine-to-machine) | Nothing — can only ingest transactions | No | No | No | No |

- **Jurisdiction restrictions** are resolved **only from the verified JWT claim**, never from a client-supplied parameter — a request for another jurisdiction's data is a 403, tested explicitly and verified live.
- **The human-approval gate** (Part 3, Case & Approval) is the single most important governance mechanism in the system: no alert can be built or sent without an `approved` decision row that the Action module itself re-verifies server-side.
- **The audit trail** (Part 3) makes every state-changing action — who viewed what, who approved what, what was dispatched, what the outcome was — permanently, cryptographically checkable.
- **Explainability** (2F) is itself a governance control: an investigator is never asked to act on an unexplained number.

**Why this matters for a law-enforcement-oriented system specifically:** the cost of a wrong prediction in this domain isn't "a bad ad recommendation" — it can be a wasted police response, or worse, a false accusation. Every one of the controls above exists specifically to make sure a wrong prediction costs exactly a wasted team-hour, and nothing more, and that every actual action taken is traceable to a specific, accountable human decision.

---

## PART 12 — Real-Time System

### Simple explanation

Instead of an investigator refreshing a page to see if anything new happened, the system pushes updates to them the instant they occur — the same way a chat app shows a new message without you refreshing.

### Technical explanation

Every event below **actually exists and actually fires** in the running backend — verified in a single live run, in this exact order, over a real WebSocket connection, during this project's own final verification pass:

```
complaint.created
intelligence.started
graph.updated
ring.detected
corridor_prediction.completed
exit_prediction.completed
risk_field.updated
explanation.generated
intervention.recommended
approval.required
intervention.approved  /  intervention.rejected
action.dispatched
outcome.recorded
feedback.created
```

- **Mechanism:** an in-process `asyncio` publish/subscribe dispatcher — one producer, one or more subscribers per topic, all within the single backend process (see Part 6 for why). Every event is jurisdiction-scoped when pushed to WebSocket clients, so an investigator only ever sees live updates for their own jurisdiction.
- **WebSocket:** `WS /v1/ws` — one connection per investigator session, auth via the same JWT, no polling anywhere in the design.
- **A named, disclosed naming note:** `docs/ARCHITECTURE.md` also names a `spatiotemporal_prediction.completed` event; the actual implementation uses `exit_prediction.completed` for this exact stage instead (a documented, deliberate naming reconciliation made during Phase 2D, not an inconsistency introduced silently) — this document lists only the event names that are **actually emitted** by the running code.

---

## PART 13 — What Has Actually Been Verified

This is not a claim — it is a summary of independent verification performed against the real Docker stack (PostgreSQL+PostGIS, Neo4j, FastAPI backend) in this project's own most recent sessions.

- **Infrastructure:** real PostgreSQL (confirmed via live config inspection — `postgresql://...`, never SQLite in the running container), PostGIS 3.4 active, real Neo4j, Alembic migrations at head, all 20 API routes registered and reachable.
- **Complete pipeline, live:** a fresh complaint, submitted through the real public API, produced real transactions, a real Neo4j graph (independently confirmed via a direct Cypher query), and real ring detection — all in one continuous run. A second, already-geolocated real complaint was carried live through prediction → risk-field → explanation → optimization → approval → **real signed dispatch to a real mock receiver** → outcome → a real feature-snapshot write for feedback — with every step independently re-verified by direct, read-only PostgreSQL queries, not by trusting the API's own response.
- **Events/WebSocket:** all six of the case's live-triggered events — `intervention.recommended → approval.required → intervention.approved → action.dispatched → outcome.recorded → feedback.created` — were captured, in that exact order, over one real WebSocket connection.
- **RBAC/security:** verified live across investigator, supervisor, auditor, admin, and unauthenticated requests — cross-jurisdiction access correctly denied, role-inappropriate actions correctly denied, correct actions correctly allowed.
- **Database consistency:** independently confirmed that PostgreSQL's ring records exactly match the real Neo4j graph structure for the same complaint.
- **Regression testing:** **370 out of 370 automated tests passed, on three consecutive full runs**, executed against an isolated, disposable `neo4j-test` instance (never the shared development Neo4j — an isolation guard actively enforces this and would halt the entire test session if it were ever violated).
- **Frontend compatibility:** `tsc --noEmit` and `vite build` both completed cleanly against the current backend contract.

**Why this matters:** every number and every claim in this document about backend behaviour is something that was actually run and actually observed on real infrastructure in this project — not a description of what the code is *supposed* to do.

---

## PART 14 — Completed vs Future — The Master Table

| Capability | Status | Explanation |
|---|---|---|
| Complaint intake, PII hashing | **COMPLETED** | Real, verified against Postgres |
| Transaction ingestion + Graph Builder (2A) | **COMPLETED** | Real Postgres + Neo4j, bounded traversal, verified |
| Ring detection (2B) | **COMPLETED** | Real Louvain clustering, real features, verified |
| Corridor prediction (2C) | **COMPLETED** | Real trained gradient-boosted classifier |
| Exit-channel + time-window scoring (2D) | **COMPLETED** | Real XGBoost + Cox model, feature vectors persisted |
| Dynamic risk field fusion (2E) | **COMPLETED** | Real deterministic fusion, historical replay working |
| Explainability (2F) | **COMPLETED** | Real SHAP, real graph path, honest comparable-case gap |
| Intervention optimizer (2G) | **COMPLETED** | Real greedy coverage-max + ranked knapsack |
| Case assignment / closure | **COMPLETED** | Real, jurisdiction-validated |
| Human approval gate | **COMPLETED** | Real, role-restricted, one-time, audited |
| Action dispatch (mock receivers) | **CURRENT PROTOTYPE SCOPE** | Real signing/verification/audit mechanism; receiver is a verified mock, not a real institution |
| Outcome recording + feedback labeling | **COMPLETED** | Real, reuses real persisted feature vectors |
| Audit event log + chain verification | **COMPLETED** | Real hash chain, independently verified |
| Model registry read surface | **COMPLETED (empty by design)** | Endpoint works; no model has been formally registered yet |
| **Retraining / champion-challenger promotion job** | **FUTURE SCOPE** | Explicitly named in the architecture as "a separate, non-live batch job" — not built |
| **Real bank/I4C/SMS/email integrations** | **FUTURE SCOPE** | Only signed-webhook mocks exist; the payload contract is real and integration-ready |
| **Dedicated `GET /v1/alerts` list/detail endpoints** | **FUTURE SCOPE** | Alert state exists and is fully queryable via audit + direct persistence; no dedicated read endpoint yet |
| **Bank-liaison-scoped Alert Inbox** | **FUTURE SCOPE** | Requires a schema link (`Alert` → `bank_id`) not present in the frozen schema |
| **Investigator Incident Workspace (8-screen UI)** | **FUTURE SCOPE** | Backend fully supports it; frontend is currently a Phase-1 skeleton only |
| **Risk Heatmap Dashboard UI** | **FUTURE SCOPE** | Backend `risk-field` API works; no map UI built yet |
| **Real historical cybercrime training data** | **FUTURE SCOPE / by design** | Synthetic data used deliberately (real data is restricted); architecture is designed so a real feed can replace it without changing the model interface |
| **Merkle-root / external audit anchoring** | **FUTURE SCOPE** | Explicitly decided against for this prototype phase (a live testnet dependency was judged too risky for a demo) |

### Known limitations, stated plainly

- A brand-new complaint cannot progress past ring detection without account geolocation, which real transaction ingestion does not currently set — a known, disclosed architecture gap, not a bug discovered in this document's writing.
- Comparable-case retrieval in the Explainer will legitimately return an empty list until enough resolved cases exist with real persisted feature vectors — this is correct, honest behaviour, not a defect.
- The synthetic data generator produces structurally realistic but entirely synthetic fraud rings, exit channels, and timing distributions — calibrated against published aggregate statistics, but not real cases.
- The `alerts` table has no dedicated success/failure status column; delivery state is represented honestly via `sent_at`/`delivered_at`, not a richer status enum.

---

## PART 15 — What We Should Not Claim

This section exists because honesty about scope is a feature of this project, not an afterthought.

- **TRACE-X must never claim a predicted exit "has already happened."** It is a prediction — an investigative lead, not a fact, and every response surface must say so.
- **A probability number is not a certainty.** "65% probability, 15–40 minutes" means exactly that — a calibrated estimate, reported alongside its own evaluation metrics, never presented as a guarantee.
- **The mock receivers (`/mock/bank`, `/mock/i4c`, `/mock/exchange`, `/mock/merchant`) are not real bank or government systems.** They genuinely verify a cryptographic signature and genuinely log receipt — but they are simulations, and must always be labeled as such in any demo or presentation.
- **No retraining or champion/challenger model promotion currently exists.** The `model_registry` table and its read endpoint are real and working; they are honestly empty, because no training job has populated them.
- **Synthetic-data evaluation metrics (hit-rate, calibration, coverage gain) prove the pipeline is internally consistent and honestly measured — they do not prove real-world accuracy on real cybercrime data**, which this project has never had access to.
- **The system predicts locations and time windows — never a person.** No feature, schema field, or output anywhere in this system names or profiles an individual by identity or demographic attribute.

---

## PART 16 — Final System Block Diagram

```
                         DATA SOURCES
        (citizen complaint intake, synthetic transaction feed,
                 public ATM/branch/exchange registry)
                              │
                              ▼
                    ┌───────────────────┐
                    │     INGESTION      │   PostgreSQL (system of record)
                    │  (2A: PII hashing,  │◄──────────────┐
                    │   hop_index)        │                │
                    └─────────┬──────────┘                │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │   GRAPH BUILDER    │──────► Neo4j (derived fraud graph)
                    │       (2A)         │                 │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │  RING DETECTION    │  Louvain (unsupervised)
                    │       (2B)         │                 │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │     CORRIDOR       │  Gradient-boosted classifier
                    │       (2C)         │                 │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │ EXIT + TIME SCORE  │  XGBoost + Cox survival model
                    │       (2D)         │──────────────────┤
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │    RISK FIELD      │  Deterministic fusion (in-process)
                    │       (2E)         │                 │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │   EXPLANATION      │  SHAP + real graph path
                    │       (2F)         │                 │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │ INTERVENTION       │  Greedy coverage-max / knapsack
                    │  OPTIMIZER (2G)    │                 │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │  HUMAN APPROVAL    │  ◄── the only human-gated step
                    │ (Case & Approval)  │                 │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │      ACTION        │  Signed webhook → mock receiver
                    │  (Action & Alert)  │                 │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │     OUTCOME        │  Real result recorded            │
                    └─────────┬──────────┘                 │
                              ▼                            │
                    ┌───────────────────┐                 │
                    │ AUDIT / FEEDBACK   │◄────────────────┘
                    │  (hash-chained)    │  Labeled training rows
                    └─────────┬──────────┘
                              │
                              ▼
              Event Dispatcher (in-process asyncio pub/sub)
                              │
                              ▼
                    WebSocket Layer (live push)
                              │
                              ▼
              Frontend (Investigator Console — future scope
                    for the full 8-screen workspace)
```

---

## PART 17 — Final Project Summary

TRACE-X takes raw financial cybercrime information — a complaint, a chain of transactions — and turns it into:

```
UNDERSTANDING  →  PREDICTION  →  RISK  →  EXPLANATION  →  ACTION
```

This is more than a conventional dashboard because a conventional dashboard stops at the first arrow — it shows you what happened. TRACE-X keeps going: it predicts what is *about* to happen, fuses that into a live, jurisdiction-wide risk picture, explains its own reasoning in terms a human can actually check, and only then — after an explicit, permanent, accountable human decision — takes real action and honestly records the result.

**The proactive core of this project is not any single model — it is the combination:**

- **Graph intelligence** finds the real network a spreadsheet would hide.
- **Predictive analytics** turns "something is happening" into "here, roughly, and here, roughly when."
- **Geospatial risk fusion** turns one case's prediction into a shared, living picture for an entire jurisdiction.
- **Explainability** makes every one of those predictions defensible, not just plausible.
- **Human-approved intervention** is what turns a prediction into a responsible, accountable action rather than an unchecked automated system.

Every one of those five pieces is real, working, and independently verified against a real database and a real graph engine today. The gaps that remain — real institutional integrations, a full investigator workspace UI, and a real production data source — are named honestly in this document precisely because the credibility of a system like this depends on never confusing "designed for" with "already built." TRACE-X's actual claim, right now, is a real, tested, end-to-end intelligence pipeline from complaint to audited outcome — and that claim, this document has shown, is true.

---

*This document was produced by inspecting the actual repository, the actual implemented backend code, the actual database schemas, and the project's own locked architecture documents (`docs/`), cross-referenced against this project's own independent Docker-based verification evidence. No source code, schema, migration, or architecture file was modified in the production of this document.*
