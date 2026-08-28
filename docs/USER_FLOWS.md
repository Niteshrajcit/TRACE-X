# TRACE-X — User Flows

> Depends on: [PRODUCT.md](PRODUCT.md) §4 (canonical 14-step flow), [API_CONTRACT.md](API_CONTRACT.md) for the exact calls named below. **[Revised after product review]** Event names below are updated to match the canonical granular sequence locked in [PRODUCT_EXPERIENCE.md §4](PRODUCT_EXPERIENCE.md) (`intelligence.started`, `graph.updated`, `exit_prediction.completed`, `spatiotemporal_prediction.completed`, etc.) — that table is authoritative for producer/consumer/DB/UI detail; this document stays at the flow-narrative level.

---

## Flow A — Citizen complaint to investigator screen (steps 1–3)

1. Citizen fills the intake form → `POST /v1/complaints` → gets back `incident_reference` immediately (this is 🟢 REAL and stands in for NCRP; see PRODUCT.md §5)
2. Backend hashes PII, creates `Complaint` + `Account(victim)` rows, emits `complaint.created`
3. Intelligence orchestrator picks up the event, kicks off Flow B in the background
4. Every investigator connected via WebSocket in that jurisdiction receives `intelligence.started` within the same second — no refresh, no poll

**Failure/edge paths**: complaint with no linked transactions yet (money hasn't moved) stays in `status: new` indefinitely and never enters the expensive pipeline — this is the mechanism behind "not every complaint needs a full prediction" (PROJECT.md §16).

---

## Flow B — Graph construction to prediction (steps 4–9)

1. Orchestrator calls the Graph Builder as new `transaction.ingested` events arrive (from the synthetic harness in demo, from a real feed in production) — graph grows hop by hop, emitting `graph.updated`
2. Once at least one hop exists, Ring Detector runs over the current subgraph
3. Corridor Predictor produces an exit vector from the ring's hop sequence → `exit_prediction.completed`
4. Exit-Channel + Time-Window Scorer scores candidate exit channels within that vector → `spatiotemporal_prediction.completed`
5. Risk Field Fusion folds the result into the jurisdiction's live surface → `risk_field.updated`
6. Explainer pre-computes the explanation for the top-ranked channel (so it's instant when an investigator clicks, not computed on click) → `explanation.generated`
7. All six events above push to every subscribed investigator as they fire, in order — this is what drives the Incident Workspace's live pipeline-progress strip (PRODUCT_EXPERIENCE.md §3.1)

**Investigator-visible state machine**: `new → graph_building → predicted`. The console shows which state a case is in — this stops a judge from mistaking "no prediction yet because no money has moved" for "the system is broken."

---

## Flow C — Investigator reviews and requests optimization (steps 8–10)

1. Investigator opens the case (`GET /v1/cases/{id}`), sees graph + risk map + top prediction
2. Clicks the top-ranked exit channel → `GET /v1/cases/{id}/explanation` → sees factors, graph path, comparable cases
3. Sets available team count, or request-slot count for a non-physical exit channel (e.g. 2) → `POST /v1/cases/{id}/optimize-deployment` → `intervention.recommended` fires once the optimizer returns
4. Sees the optimized assignment plus the naive top-N comparison, with the coverage-gain number surfaced
5. Can change the team count and re-run — each run is a new immutable `RecommendedDeployment` row, so the investigator can compare options without losing history

---

## Flow D — Human approval gate (steps 11–13)

0. The instant a deployment is proposed, `approval.required` fires — this is what puts the pending badge on the Command Center card (PRODUCT_EXPERIENCE.md §4)
1. Investigator (or supervisor, per RBAC — see SECURITY_AND_GOVERNANCE.md §3) reviews the recommended deployment and either:
   - **Approves** → `POST /v1/deployments/{id}/decision {approved}` → `intervention.approved` → Action module builds and sends alert payloads to the relevant mock external system (bank/I4C/exchange/merchant, per the active scenario's channel) and/or dispatches to real teams (outside system scope) → `action.dispatched` → audit event written
   - **Rejects** → `POST /v1/deployments/{id}/decision {rejected}` with mandatory justification text → `intervention.rejected` → audit event written, no alert sent
2. **No path exists in the API for the system to send an alert without a prior `approved` decision row** — this is enforced server-side (the Action module's send function requires a `decision_id` and checks its status), not just a UI convention. This is the literal implementation of PROJECT.md §7.6's "no automated freezing or blocking."
3. Every view of the case by every role, every decision, and every alert dispatch appends to the hash-chained audit log (step 13) — see SECURITY_AND_GOVERNANCE.md §4

---

## Flow E — Outcome recording and feedback (step 12, 14)

1. After the response window has passed, the investigator (or supervisor) records what actually happened: `POST /v1/deployments/{id}/outcome` → `outcome.recorded`
2. This writes both an `InterventionOutcome` row and a labeled `FeatureSnapshot` row — the ground truth the retraining job needs → `feedback.created` confirms the label is retraining-eligible, which is what the Incident Workspace's `#audit` tab shows as its closing line (PRODUCT_EXPERIENCE.md §4)
3. Retraining job (manually triggered during the hackathon; schedulable in production) re-fits stages 2–4 on the accumulated labels, evaluates against a held-out set, and only promotes a new model version if it wins — see AI_ML_ARCHITECTURE.md §8
4. Auditor/admin can see the resulting model version bump and its metric deltas in the model registry view

---

## Flow F — Supervisor oversight (cross-cutting)

A supervisor sees everything their subordinate investigators see (`GET /v1/cases?jurisdiction_id=` scoped to their unit). **[Deprioritized after product review — PRODUCT_EXPERIENCE.md §8.5]** The escalation path described in the original design (routing a deployment to the supervisor for a second approval on high-sensitivity cases) is not part of the locked core journey (PRODUCT_EXPERIENCE.md §1) and is deprioritized out of the build plan — the supervisor role and its read scope remain, since both are used elsewhere (RBAC completeness, the judge demo's persona set), but the escalation *logic/UI* doesn't compete for build time against the primary journey.

---

## Flow G — External-institution liaison (cross-cutting, 🟠 SIM)

The mock bank liaison persona receives only alerts naming accounts at their own `bank_id` (`GET /v1/alerts?...` scoped server-side by the JWT's `bank_id` claim, identical scoping mechanism to jurisdiction scoping for investigators). The same Alert Inbox screen serves the exchange-compliance and merchant-ops personas introduced by Scenarios B/C (PRODUCT_EXPERIENCE.md §7), scoped identically by their own org identifier. They can acknowledge receipt (`read_at` timestamp) — there is deliberately **no** "freeze account" / "cancel order" button in this prototype's liaison surfaces, because those actions require real institutional authority TRACE-X does not have and should not simulate as a one-click button (PRODUCT.md §7's non-goals).

---

## Flow H — Auditor/admin (cross-cutting)

Read-only across jurisdictions: audit event stream, chain-verification tool (`GET /v1/audit/verify-chain`), model registry. No case-content edit rights anywhere in the RBAC matrix for this role — see SECURITY_AND_GOVERNANCE.md §3.

---

## Sequence diagram — the full 14-step flow in one picture

```
Citizen        Backend/Pipeline                    Investigator     Mock External   Audit Log
  │  POST complaint │                                    │                │              │
  ├────────────────►│ create Complaint, incident_id      │                │              │
  │◄────────────────┤                                    │                │              │
  │                 │ complaint.created ──────────► WS push (status: new) │              │
  │                 │ intelligence.started ────────► WS push (building)   │              │
  │                 │                                    │                │              │
  (synthetic/real txns stream in)                        │                │              │
  │                 │ Graph Builder ── graph.updated ────►│ (graph grows)  │              │
  │                 │ Corridor Predictor ── exit_prediction.completed ───►│ (cone appears) │
  │                 │ Exit-Channel+Time Scorer ── spatiotemporal_prediction.completed ────►│ (banner fills)
  │                 │ Risk Field Fusion ── risk_field.updated ───────────►│ (map lights up)│
  │                 │ Explainer ── explanation.generated ────────────────►│ (evidence ready)│
  │                 │                                    │ click channel  │              │
  │                 │◄──────────── GET explanation ───────┤                │              │
  │                 │──────────── explanation ───────────►│                │              │
  │                 │                                    │ set team_count │              │
  │                 │◄──────── POST optimize-deployment ──┤                │              │
  │                 │── intervention.recommended ────────►│ assignment + coverage         │
  │                 │── approval.required ────────────────►│ pending badge │              │
  │                 │                                    │ approve        │              │
  │                 │◄──────────── POST decision ─────────┤                │              │
  │                 │── intervention.approved ──────────────────────────────────► audit event
  │                 │── action.dispatched ────────────────────────────────►│              │
  │                 │                                    │                │ ack          │
  │                 │                                    │ record outcome │              │
  │                 │◄──────────── POST outcome ──────────┤                │              │
  │                 │── outcome.recorded ────────────────────────────────────────► audit event
  │                 │── feedback.created (labeled FeatureSnapshot, feeds retraining) ─────►│
```
