# TRACE-X

### Predictive Cybercrime Cash-Withdrawal Intelligence Platform

> **Smart India Hackathon 2026 · Problem Statement SIH 26184**
> Ministry of Home Affairs · Software · Blockchain & Cybersecurity

---

## Table of Contents

1. [One-Line Summary](#1-one-line-summary)
2. [The Problem](#2-the-problem)
3. [Why the Obvious Solution Isn't Enough](#3-why-the-obvious-solution-isnt-enough)
4. [Our Solution — TRACE-X](#4-our-solution--trace-x)
5. [How It Works (End to End)](#5-how-it-works-end-to-end)
6. [System Architecture](#6-system-architecture)
7. [The Six Core Modules](#7-the-six-core-modules)
8. [Data Model](#8-data-model)
9. [The ML Approach](#9-the-ml-approach)
10. [Tech Stack](#10-tech-stack)
11. [Mapping to the Official PS Requirements](#11-mapping-to-the-official-ps-requirements)
12. [Demo Flow](#12-demo-flow)
13. [Security, Privacy & Ethics](#13-security-privacy--ethics)
14. [Build Roadmap](#14-build-roadmap)
15. [Team & Pitch](#15-team--pitch)
16. [Anticipated Judge Questions](#16-anticipated-judge-questions)
17. [Glossary](#17-glossary)

---

## 1. One-Line Summary

**TRACE-X turns a cybercrime complaint into a live prediction of *where*, *when*, and *why* the stolen money will be withdrawn as cash — and tells authorities exactly where to send their limited response teams.**

---

## 2. The Problem

### The situation today

India's **National Cybercrime Reporting Portal** is the central place where citizens report cyber fraud, police act on it, and banks take financial action.

- It receives roughly **8,000 complaints per day**
- That volume is **expected to keep rising**

### Where it breaks

When money is stolen in a financial cyber fraud, it does **not** sit still. It moves:

```
Victim's account
      ↓
Mule account #1
      ↓
Mule account #2  →  Mule account #3
      ↓
        💵 CASH WITHDRAWAL — money leaves the banking system
```

Once cash is withdrawn, the trail effectively ends. There is no account to freeze, no transaction to reverse.

The problem is **timing**. Today the system is *reactive*:

| Today | What we need |
|---|---|
| Complaint filed → investigation begins | Complaint filed → **prediction** generated |
| Money already withdrawn → trail cold | Withdrawal **forecast** → teams pre-positioned |
| Reacting to what happened | Acting on what is *about to* happen |

### The central question

> **"Given what we know about a cyber-fraud complaint and its financial behaviour — where is the money most likely to surface next?"**

If investigators can answer this *before* the withdrawal happens, they can alert the bank or ATM operator, deploy a local team, coordinate across state jurisdictions, and block or recover funds while there is still something to recover.

---

## 3. Why the Obvious Solution Isn't Enough

A minimum-effort team would build this:

1. Collect historical fraud and transaction data
2. Train a classifier or hotspot model
3. Show red and green dots on a GIS map
4. Fire an alert when a risk score crosses a threshold

This technically satisfies the shape of the PS. **It is also what everyone else will build.** Public examples of earlier SIH-style work already demonstrate fraud prediction using Random Forest plus hotspot visualisation.

### The gap

That approach answers exactly one question — *"Which place is risky?"* — and leaves the four questions an investigator actually needs unanswered:

| Question an investigator asks | Basic hotspot model | TRACE-X |
|---|---|---|
| Where will the cash-out happen? | ✅ Yes | ✅ Yes |
| **When** will it happen? | ❌ No | ✅ Yes |
| **How** did the money get there? | ❌ No | ✅ Yes |
| **Why** is this location ranked high? | ❌ Black box | ✅ Explainable |
| **Where do I send my 2 teams?** | ❌ No | ✅ Yes |

A red dot on a map is information. **An investigator needs a decision.**

---

## 4. Our Solution — TRACE-X

TRACE-X is a **spatio-temporal cash-out intelligence and intervention system**.

The core shift: instead of predicting one ATM in isolation, TRACE-X models a likely **cash-out journey** — the account relationships, the geographic movement corridor, the time window, and a *ranked set* of candidate withdrawal locations.

### The six things that make it different

**1. Fraud Intelligence Graph**
Complaint → accounts → transactions → related entities → historical cash-out behaviour, all connected as one queryable graph. A complaint stops being a row in a table and becomes a network.

**2. Spatio-Temporal Prediction**
Predicts **where** *and* **when**. Time windows are as actionable as locations — a team deployed at the right ATM three hours late is a team wasted.

**3. Dynamic Risk Field**
A continuously updated risk surface, not a static heatmap. It fuses transaction signals, historical patterns, geography, time-of-day and intrinsic location risk, and it re-computes as new transactions land.

**4. Explainable Risk**
Every ranked location comes with its evidence: *which* factors pushed it up, and by how much. Investigators act on reasons, not on scores they cannot defend in court.

**5. Intervention Optimizer**
The differentiator. Given that authorities have **limited teams**, TRACE-X recommends the deployment that maximises *expected intervention coverage* — not simply the top-N riskiest points.

**6. Action Layer**
Structured alerts to authorised investigators, banks and I4C via secure channels, with **full audit trails** and **mandatory human approval** before any action is taken.

---

## 5. How It Works (End to End)

```
   ┌─────────────┐
   │  COMPLAINT  │  Citizen reports fraud on the portal
   └──────┬──────┘
          ↓
   ┌─────────────────┐
   │  INTELLIGENCE   │  Build the graph: accounts, transactions,
   │                 │  linked entities, historical behaviour
   └──────┬──────────┘
          ↓
   ┌─────────────────┐
   │   PREDICTION    │  Where + When the cash-out is likely
   └──────┬──────────┘
          ↓
   ┌─────────────────┐
   │      RISK       │  Ranked candidate locations + corridors,
   │                 │  each with an explanation
   └──────┬──────────┘
          ↓
   ┌─────────────────────────┐
   │  RECOMMENDED ACTION     │  Optimal deployment for the teams
   │                         │  actually available
   └──────┬──────────────────┘
          ↓
   ┌─────────────┐
   │   ALERT     │  Investigator / bank / I4C — human approves
   └──────┬──────┘
          ↓
   ┌───────────────┐
   │ INTERVENTION  │  Block, freeze, deploy, recover
   └───────────────┘
```

**The old model:** `complaint → investigation`
**TRACE-X:** `complaint → prediction → intervention`

---

## 6. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                       │
│  Risk Heatmap Dashboard  │  Investigator Console  │  Alerts   │
│  (GIS, filters, replay)  │  (case view, evidence) │  (multi-  │
│                          │                        │  channel) │
└────────────────────┬─────────────────────────────────────────┘
                     │  REST + WebSocket (live risk updates)
┌────────────────────┴─────────────────────────────────────────┐
│                     APPLICATION LAYER                        │
│  Auth & RBAC │ Case Mgmt │ Alert Router │ Audit Log │ Approval│
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│                     INTELLIGENCE LAYER                       │
│  ┌────────────┐ ┌────────────┐ ┌───────────┐ ┌─────────────┐ │
│  │   Graph    │ │  Spatio-   │ │   Risk    │ │Intervention │ │
│  │  Builder   │→│  Temporal  │→│   Field   │→│  Optimizer  │ │
│  │            │ │ Predictor  │ │  Engine   │ │             │ │
│  └────────────┘ └────────────┘ └───────────┘ └─────────────┘ │
│                        ↓ Explainability (SHAP / graph paths)  │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│                        DATA LAYER                            │
│  Complaint Store │ Transaction Store │ Graph DB │ Geospatial  │
│  (PostgreSQL)    │ (time-series)     │ (Neo4j)  │ (PostGIS)   │
│                                                              │
│  Feature Store  │  Model Registry  │  Audit / Evidence Vault  │
└──────────────────────────────────────────────────────────────┘
                     ↑
      Ingestion: complaint feed, bank transaction feed,
      ATM/branch registry, historical case archive
```

---

## 7. The Six Core Modules

### 7.1 Fraud Intelligence Graph

**Job:** Turn flat records into a connected network.

- **Nodes:** complaints, victims, mule accounts, transactions, devices, phone numbers, ATMs/branches, geographic cells
- **Edges:** `transferred_to`, `withdrew_at`, `shares_device_with`, `linked_to_case`, `historically_cashed_out_at`
- **Why it matters:** the strongest predictor of a future cash-out is often not the current complaint at all — it is a *sibling* account in the same fraud ring that already cashed out somewhere last week. Only a graph surfaces that.

**Key outputs:** money-flow path, ring membership, hop depth, velocity of movement.

---

### 7.2 Spatio-Temporal Prediction Engine

**Job:** Answer *where* and *when*, together.

- **Space:** the map is divided into H3 hexagonal cells; the model outputs a probability distribution over cells rather than a single point
- **Time:** the model outputs a time window (e.g. *next 30–60 minutes*), because layering-to-cash-out delays follow learnable patterns
- **Output shape:** `P(cash-out | cell, time-bucket)` — a full surface, not one prediction

---

### 7.3 Dynamic Risk Field Engine

**Job:** Fuse everything into one continuously updated risk surface.

Signal groups combined:

| Signal group | Examples |
|---|---|
| Transaction | amount, velocity, hop count, structuring/splitting behaviour |
| Historical | past cash-outs by this ring, this corridor, this account cluster |
| Geographic | distance from victim, corridor direction, border/jurisdiction proximity |
| Temporal | hour of day, day of week, ATM replenishment cycles |
| Location-intrinsic | ATM cash limits, CCTV coverage, footfall, prior incident density |

The field is **decayed and refreshed** — risk that is not realised fades, and new transactions push it back up.

---

### 7.4 Explainable Risk

**Job:** Make every ranking defensible.

For each ranked location the investigator sees:
- The **top contributing factors** with weights (SHAP-style attribution)
- The **graph path** that connects this complaint to this location
- **Comparable historical cases** that followed the same pattern
- A **plain-language reason**: *"Ranked #1 because funds moved 3 hops in 18 minutes toward this district, and two accounts in the same ring cashed out within 4 km in the last 30 days."*

No black-box scores. Ever.

---

### 7.5 Intervention Optimizer

**Job:** Convert prediction into deployment.

**Input:** ranked risk surface + number of available teams + team locations + travel times
**Output:** the assignment that maximises **expected intervention coverage**

Why this is not just "pick the top N":

> Three adjacent high-risk ATMs in one street may be covered by **one** team. Sending all three teams there wastes two. The optimizer accounts for coverage radius, travel time, and overlapping probability mass — a coverage-maximisation problem, not a sorting problem.

---

### 7.6 Action Layer

**Job:** Get the intelligence to the right human, safely.

- **Channels:** dashboard trigger, SMS, email, secure API to banks and I4C
- **Human-in-the-loop:** no automated freezing or blocking — every action requires an authorised approval
- **Audit trail:** who saw the alert, who approved, what was done, what the outcome was
- **Feedback loop:** the outcome is written back as a training label, so the model improves with every real case

---

## 8. Data Model

### Core entities

```
Complaint
  ├── complaint_id, filed_at, amount, fraud_type
  ├── victim_account_ref
  └── → Transactions[]

Transaction
  ├── txn_id, from_account, to_account, amount, timestamp
  ├── channel (UPI / IMPS / NEFT / card)
  └── hop_index

Account
  ├── account_hash, bank, branch_geo, kyc_risk_tier
  └── → linked entities (device, phone, address cluster)

CashOutPoint
  ├── atm_id / branch_id, lat, lon, h3_cell
  ├── cash_limit, cctv_flag, footfall_tier
  └── historical_incident_count

Prediction
  ├── prediction_id, complaint_id, generated_at
  ├── ranked_locations[] (h3_cell, probability, time_window)
  ├── explanation[] (factor, weight, evidence_ref)
  └── recommended_deployment[]
```

### Data sourcing for the prototype

Real cybercrime data is restricted, so the prototype runs on:
- **Synthetic transaction graphs** generated to match published fraud-typology statistics
- **Public ATM/branch location data** for the geospatial layer
- **Published aggregate cybercrime statistics** (NCRB, I4C reports) for calibrating base rates

The pipeline is built so that a real feed can replace the synthetic one **without changing the model interface** — a point worth stating explicitly to judges.

---

## 9. The ML Approach

### Why a single classifier is the wrong tool

The target is not a label. It is a **joint distribution over space and time**. So the system is a small ensemble, each part doing what it is good at:

| Stage | Model | Purpose |
|---|---|---|
| Ring detection | Graph Neural Network / community detection | Find accounts that belong to the same fraud operation |
| Corridor prediction | Sequence model (LSTM / Transformer) over hop sequences | Learn how money typically travels geographically |
| Location scoring | Gradient boosting (XGBoost / LightGBM) over fused features | Score each candidate H3 cell |
| Time-window estimation | Survival analysis / hazard model | Estimate *time until cash-out*, not just whether |
| Explanation | SHAP + graph path extraction | Attribute the score to human-readable evidence |
| Deployment | Constrained coverage optimisation (greedy + ILP) | Assign limited teams to maximise coverage |

### Honest evaluation

Accuracy is the wrong headline metric. What we report:

- **Top-K hit rate** — was the true cash-out cell in our top 5 / top 10?
- **Time-window calibration** — when we say *45 minutes*, how often is it 45 minutes?
- **Expected coverage gain** — how much better is our deployment than "send teams to the top N"?
- **Lead time** — how many minutes of warning did we actually buy?

**Lead time is the metric that matters.** A prediction that arrives after the withdrawal is worth zero.

---

## 10. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + TypeScript | Component-heavy dashboard, strong typing for case data |
| Mapping | Mapbox GL / Leaflet + deck.gl | H3 hex rendering, smooth large-scale geospatial layers |
| Backend | FastAPI (Python) | Same language as the ML stack, async, auto-documented APIs |
| Realtime | WebSocket | Live risk-field updates without polling |
| Relational DB | PostgreSQL + PostGIS | Cases, users, audit log, geospatial queries |
| Graph DB | Neo4j | Fraud ring traversal, multi-hop path queries |
| ML | scikit-learn, XGBoost, PyTorch Geometric | Boosting + GNN + sequence models |
| Explainability | SHAP | Standard, defensible feature attribution |
| Geospatial indexing | Uber H3 | Uniform hex cells, clean multi-resolution aggregation |
| Alerts | Twilio / SMTP / signed webhooks | Multi-channel delivery to police, banks, I4C |
| Auth | JWT + RBAC | Role separation: investigator, supervisor, bank, admin |

---

## 11. Mapping to the Official PS Requirements

| PS asks for | TRACE-X delivers | Where |
|---|---|---|
| **Predictive Analytics Engine** — AI/ML on historical cybercrime and financial data, pattern detection, geospatial risk modelling | Fraud Intelligence Graph + Spatio-Temporal Predictor + Dynamic Risk Field | §7.1–7.3 |
| **Risk Heatmap Dashboard** — GIS interface, real-time/potential risk zones, filters by time, location, crime category | H3 risk surface with time-slider, category and jurisdiction filters, historical replay | §6, §12 |
| **Law Enforcement Interface** — secure investigator interface for alerts, intelligence reports, evidence documentation | Investigator Console with case view, explainable evidence panel, exportable intelligence report | §7.4, §7.6 |
| **Alert & Notification System** — real-time notifications to law enforcement, banks and I4C via SMS, email, APIs, dashboard triggers | Action Layer, multi-channel, human-approved, fully audited | §7.6 |
| *(Beyond the PS)* | **Intervention Optimizer** — resource-aware deployment recommendation | §7.5 |

Every mandatory component is covered. The optimizer is the extra that separates us from a compliant-but-ordinary submission.

---

## 12. Demo Flow

A tight, judge-friendly walkthrough:

**1. The complaint arrives** *(10s)*
A ₹2 lakh fraud complaint lands on the dashboard. Right now it is just a record.

**2. The graph builds itself** *(20s)*
Watch the intelligence graph expand live — victim account, three mule accounts, and a link to an existing case from last month.

**3. The risk field ignites** *(20s)*
The map lights up. Not one dot — a corridor, with a probability gradient across hex cells.

**4. The prediction** *(15s)*
> **"87% risk of cash withdrawal in this corridor within the next 45 minutes."**

**5. The explanation** *(20s)*
Click the top-ranked cell. Show the factors, the weights, the money-flow path, and the two comparable historical cases.

**6. The optimizer** *(20s)*
Set available teams to **2**. The system recomputes and recommends two deployment points — deliberately *not* the top two cells, and it explains why coverage beats ranking.

**7. The alert** *(15s)*
Generate the alert. Show the approval gate, the bank notification payload, and the audit entry.

**Close:** *"Complaint to actionable deployment in under two minutes. The money is still in the system."*

---

## 13. Security, Privacy & Ethics

This system touches financial data, location data, and law enforcement action. That demands explicit safeguards — and stating them earns credibility with judges rather than costing time.

**Privacy**
- Account identifiers are hashed; raw PII never leaves the ingestion boundary
- Predictions are attached to **cases**, not to named individuals
- Role-based access: an investigator sees their jurisdiction, a bank sees only its own accounts

**Preventing harm**
- The system predicts **locations and time windows**, never "this person will commit a crime"
- Outputs are investigative leads, **not** evidence of guilt, and are labelled as such in the UI
- Deliberate guard against geographic bias: the model is audited for over-flagging specific districts, and location-intrinsic features are monitored for proxy effects

**Accountability**
- Mandatory human approval before any bank-side action
- Immutable audit log of every alert, view, approval and outcome
- Every prediction is reproducible: model version, feature values and explanation are stored with it

**Security**
- Encryption in transit and at rest, signed webhooks for institutional integrations
- Session and action logging on the investigator console

---

## 14. Build Roadmap

### Phase 1 — Foundation
- [ ] Synthetic data generator (fraud rings, transaction chains, cash-out events)
- [ ] Core schema: PostgreSQL + PostGIS, Neo4j graph
- [ ] Ingestion pipeline and feature store skeleton

### Phase 2 — Intelligence
- [ ] Graph builder + ring detection
- [ ] Baseline location scorer (XGBoost) with H3 features
- [ ] Time-window model
- [ ] SHAP explanation pipeline

### Phase 3 — Interface
- [ ] Risk heatmap dashboard with time slider and filters
- [ ] Investigator console: case view, evidence panel, graph visualisation
- [ ] Live WebSocket risk updates

### Phase 4 — The Differentiator
- [ ] Intervention optimizer (greedy baseline → constrained optimisation)
- [ ] Deployment recommendation UI with team-count control

### Phase 5 — Action & Polish
- [ ] Alert routing, approval gate, audit log
- [ ] Bank/I4C API integration mock
- [ ] Evaluation dashboard: top-K hit rate, calibration, lead time
- [ ] Demo script rehearsal and fallback recording

---

## 15. Team & Pitch

### The 2-minute pitch

**FAZIL — 0:00 to 1:00**

> Good morning judges.
>
> Imagine a citizen reports that ₹2 lakh has been stolen through a cyber fraud. The complaint reaches the system, but there is a critical question: **where will that stolen money be withdrawn next?**
>
> If we only react after the cash is withdrawn, the opportunity to recover the money may already be gone. SIH 26184 asks us to change that by forecasting likely cash-withdrawal locations in advance.
>
> Our solution is **TRACE-X** — a Predictive Cybercrime Cash-Out Intelligence Platform.
>
> TRACE-X converts a cybercrime complaint into a living intelligence graph. It connects transaction behaviour, historical fraud patterns, time and geography, and then identifies where the money is most likely to surface next.

**OSHO — 1:00 to 2:00**

> But we don't stop at putting a red dot on a map.
>
> TRACE-X predicts **where, when and why** a cash-out is likely. It may tell an investigator: *"This corridor has an 87% risk of a cash withdrawal within the next 45 minutes."*
>
> Then comes our key difference: **intervention optimization**. If authorities have only two response teams, TRACE-X recommends where those teams can create the highest expected intervention coverage. Investigators receive an explainable alert, while banks and authorized agencies can be notified through secure channels.
>
> So instead of complaint → investigation, we create **complaint → prediction → intervention**.
>
> Our goal is simple: don't wait for stolen money to disappear. Predict where it will surface next — and give authorities time to act.
>
> This is TRACE-X. Thank you.

---

## 16. Anticipated Judge Questions

**"Where does your training data come from? Real cybercrime data is confidential."**
The prototype runs on synthetic transaction graphs calibrated against published fraud typologies and aggregate NCRB/I4C statistics. The ingestion interface is built so a real I4C or bank feed drops in without touching the model layer. We are demonstrating the *system*, and the system is deployment-ready for real data.

**"87% — is that number real?"**
It is a calibrated model output, and we report calibration explicitly. Our headline metrics are top-K hit rate, time-window calibration, and lead time — not accuracy, because accuracy is meaningless for a spatio-temporal distribution.

**"Isn't this predictive policing? Doesn't it profile people?"**
No. We predict *where money will move*, driven by transaction behaviour, not by demographics of any area or person. Outputs are attached to cases, never to named individuals, and are labelled investigative leads rather than evidence. We also audit for geographic over-flagging.

**"What if the prediction is wrong?"**
Then a team is deployed to a location where nothing happens — the same cost as today's random patrolling, with none of the downside of a false accusation, because no action is taken against any person without human approval. And every wrong prediction becomes a training label that improves the model.

**"How is this different from any fraud-detection tool?"**
Fraud detection asks *"is this transaction suspicious?"* TRACE-X asks *"given that it is, where and when will the cash leave the system, and where do I send my two available teams?"* It is a deployment-decision system, not a detection system.

**"Can it scale to 8,000 complaints a day?"**
Not every complaint needs a full prediction — only financial-fraud complaints with active money movement. The risk field is computed on H3 cells rather than per-ATM, the graph queries are bounded by hop depth, and scoring is batched. The expensive part (graph traversal) is the part we control the depth of.

---

## 17. Glossary

| Term | Meaning |
|---|---|
| **Mule account** | A bank account used to receive and pass on stolen funds, often opened with a real but coerced or paid identity |
| **Layering** | Moving money through multiple accounts to obscure its origin |
| **Cash-out** | The moment stolen money is withdrawn as physical cash and leaves the traceable banking system |
| **Corridor** | A geographic path along which stolen money tends to move before being withdrawn |
| **H3 cell** | A hexagonal geographic cell (Uber's H3 system) used as the unit of spatial prediction |
| **I4C** | Indian Cyber Crime Coordination Centre, under the Ministry of Home Affairs |
| **Lead time** | Minutes of advance warning between our prediction and the actual withdrawal |
| **Expected intervention coverage** | The total probability mass of cash-out events that available teams can physically reach in time |
| **SHAP** | A method for attributing a model's prediction to its individual input features |

---

*TRACE-X · SIH 26184 · Ministry of Home Affairs · Blockchain & Cybersecurity*
*Don't wait for stolen money to disappear. Predict where it will surface next.*
