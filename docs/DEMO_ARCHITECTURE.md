# TRACE-X — Demo Architecture

> Depends on: [PRODUCT.md](PRODUCT.md) §2 (classification legend) and §5 (scope boundary) — this document is where those labels become visible screen elements.

---

## 1. The core demo principle

The demo must never let a judge wonder "is that real?" without an immediate, honest, visible answer. Concretely: **every SIM component carries a persistent, unmissable UI badge** ("Simulated — no live NCRP/bank connection") and **every ML-PROTO output is labeled with its model version and evaluation metric**, not presented as unqualified fact. This is not a legal disclaimer buried in a footer — it is a first-class design requirement, because PROJECT.md §16 shows the judges will ask exactly this, and the honest answer is a competitive advantage (per PROJECT.md §3's whole thesis) only if it's visibly true.

## 2. Synthetic data harness — 🟢 REAL component

A standalone process (`synthetic-data-harness`), not a script run once, because it must serve two modes:

**Batch mode** — generates a base dataset before the demo starts:
- Historical resolved cases (for the Explainer's "comparable cases" and the retraining baseline)
- ATM/branch registry seeded from real public data (bank branch locators, RBI/NPCI published ATM density data) — this part is real-world data, not synthetic, and is labeled as such
- Base account population with realistic KYC-tier distribution

**Live-drip mode** — during the actual demo, plays a **scripted fraud scenario** at a controlled pace (configurable speed multiplier) by POSTing to the exact same `/v1/complaints` and `/v1/transactions/ingest` endpoints a real feed would use (ARCHITECTURE.md §9). This is the single most important credibility mechanism in the whole system: the demo is not "fake data displayed by the UI," it is "fake data flowing through the real pipeline via the real ingestion API."

### Generation methodology (what makes it "structurally realistic," not just random)

1. **Fraud-ring topology**: generated with `networkx` using parameters (ring size, hop depth, branching factor) sampled from ranges consistent with published fraud-typology descriptions (layering depth, mule-chain length) — cited from NCRB/I4C aggregate reports, not invented
2. **Transaction timing**: inter-hop delays drawn from a distribution calibrated to reported layering speed (fast layering within minutes, slower for certain fraud types) rather than uniform random
3. **Geographic movement**: corridor endpoints sampled from real ATM/branch coordinates so the exit-vector and location-scoring stages operate on genuine geospatial data, not synthetic coordinates floating in empty space
4. **Ground truth retained**: the generator records the *true* ring membership, *true* exit vector, and *true* cash-out cell/time it planted — this is what makes stages 2–4's evaluation metrics (AI_ML_ARCHITECTURE.md §2, §4) computable at all; without planted ground truth there is nothing to score hit-rate against

Every synthetic record carries `is_synthetic = true` in the schema (DATA_MODEL.md §2) — queryable, not just a comment, so it is structurally impossible to accidentally present synthetic data as real in a future environment where real data also exists.

## 3. The scripted demo scenarios

**[Expanded after product review — see PRODUCT_EXPERIENCE.md §7]** Three scenario files now exist (`demo_scenario_a_atm.yaml`, `_b_crypto.yaml`, `_c_ecommerce.yaml`), sharing the same harness and the same ingestion API, differing in hop pattern, exit-channel type, and therefore optimizer mode (AI_ML_ARCHITECTURE.md §7a/7b). **Scenario A is the primary, fully-rehearsed judge run** (see [JUDGE_DEMO.md](JUDGE_DEMO.md)); B and C are built to the same standard but are a secondary "does this generalize" beat, cut first under time pressure.

A fixed, rehearsed scenario file (`demo_scenario_a_atm.yaml`, shown below as the primary example) drives live-drip mode, matching PROJECT.md §12's beat sheet:

```yaml
scenario: sih_demo_v1
victim_account: seeded
fraud_type: upi_fraud
amount: 200000
hops:
  # [Corrected against API_CONTRACT.md §1a's frozen transaction-ingest contract]
  # `channel` is a required field on every POST /v1/transactions/ingest call
  # (DATA_MODEL.md's transactions.channel enum) - added to each hop below so
  # this scenario format actually satisfies the contract it's meant to drive.
  - {delay_s: 5,  to: mule_1, amount_pct: 0.95, channel: upi}
  - {delay_s: 8,  to: mule_2, amount_pct: 0.90, channel: upi}
  - {delay_s: 6,  to: mule_3, amount_pct: 0.85, channel: imps, sibling_of_case: "case_2024_0091"}
planted_exit_vector: {bearing_deg: 62, distance_km: [3,7]}
planted_cash_out: {h3_cell: "8828308281fffff", eta_min: 45}
team_locations: [ {lat:..., lon:...}, {lat:..., lon:...} ]
```
Because this scenario is played through the real ingestion API at real (sped-up) wall-clock pace, the "87% risk... within 45 minutes" banner shown to judges is the model's actual output on this run, reproducible and re-runnable — not a hardcoded string in a slide. The scenario's *existence* is disclosed if asked; its role is identical to a flight simulator's training scenario, not a fabricated result.

## 4. Mock institution receivers — 🟠 SIM, explicitly labeled

**[Consolidated after product review — PRODUCT_EXPERIENCE.md §8.4]** One lightweight service (`mock-external-systems`) exposing one route per channel (`/mock/bank`, `/mock/i4c`, `/mock/exchange`, `/mock/merchant` — the latter two needed for Scenarios B/C) rather than a growing list of near-identical single-purpose containers. Each route independently accepts the exact signed-webhook payload shape a real integration would (API_CONTRACT.md §4), logs receipt, and surfaces in the shared status view / Alert Inbox screen ("Alert received on [channel], HMAC verified, acknowledged at 14:32:07"). The UI is skinned with a visible "SIMULATED EXTERNAL SYSTEM" watermark, labeled per channel, so nobody — judge or teammate — mistakes any of the four for a real institution's portal.

## 5. What's live vs. pre-computed during the actual demo

| Screen moment | Live or pre-computed? |
|---|---|
| Complaint submission → incident ID | Live, real API call |
| Graph construction animation | Live — real Neo4j writes as the scenario's hops post in |
| Risk field ignition / corridor cone | Live — real model inference per hop |
| "87% ... 45 minutes" banner | Live — real model output for this run |
| Explanation panel (factors, path, comparable cases) | Live — real SHAP + graph query; comparable case is a real historical seeded record |
| Optimizer at team_count=2 | Live — real greedy computation, re-runs if the judge asks to change the number |
| Alert dispatch + audit entry | Live — real webhook to the mock receiver, real hash-chained audit row |
| Nothing in the demo path is a static screenshot or a canned JSON fixture | By design |

## 6. Fallback plan

A screen-recorded run of the exact same live scenario, kept as a fallback only for venue Wi-Fi/hardware failure — never a substitute for rehearsing the live path, and never shown unless the live system genuinely fails. The recording is timestamped and regenerated whenever the pipeline changes, so it never drifts into showing stale/incorrect behavior.

## 7. Judge-facing "reality legend"

A small persistent UI element (present in every screen's corner) rendering the PRODUCT.md §2 legend compactly: 🟢 real · 🔵 trained model (synthetic data) · 🟡 algorithm · 🟠 simulated · ⚪ future integration. Hovering any major panel shows which tag applies to what's on screen. This single affordance pre-empts most of PROJECT.md §16's credibility questions before they're asked.
