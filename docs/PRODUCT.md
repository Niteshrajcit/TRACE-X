# TRACE-X — Product Definition

> SIH 26184 · Ministry of Home Affairs · Blockchain & Cybersecurity
> Source of truth for scope, personas, and the real/simulated boundary. Every other doc in `docs/` inherits the classifications defined here.

---

## 1. What TRACE-X is

TRACE-X is a **spatio-temporal cash-out intelligence and intervention platform**. It takes a cyber-fraud complaint, builds a fraud intelligence graph around it, predicts where and when the stolen money is likely to be withdrawn as cash, explains that prediction, and recommends how to deploy a limited number of response teams — with a human approving every action and every step logged immutably.

It is **not**:
- a hotspot heatmap with a threshold alert (that's the "obvious solution" §3 of PROJECT.md already rejects)
- a live-wired connection to NCRP/I4C/bank core systems (none of us have authorized access to those; anyone claiming otherwise at demo time is lying to the judges)
- an autonomous system that freezes accounts or blocks transactions on its own (human-in-the-loop is a hard requirement, not a feature)

## 2. Component classification legend

Every capability in TRACE-X is tagged with exactly one of these. This tag appears throughout `ARCHITECTURE.md`, `AI_ML_ARCHITECTURE.md`, and `DEMO_ARCHITECTURE.md` — treat it as load-bearing, not decorative.

| Tag | Meaning | Bar it must clear |
|---|---|---|
| 🟢 **REAL** | Fully working, production-grade logic. Runs end-to-end against our own database, no shortcuts. | Would not need to be rewritten to go to production, only re-pointed at real data sources. |
| 🔵 **ML-PROTO** | A genuinely trained model producing genuine predictions from genuine (synthetic) data — not a hardcoded number. Architecture and interface are production-shaped. | Model is fit with `model.fit()`, versioned, evaluated with real metrics on a held-out split. Its *calibration* is only as good as the synthetic data, and we say so. |
| 🟡 **ALGO** | Deterministic algorithm/optimization, no learning involved, fully functional. | Real implementation of the stated math (e.g. greedy coverage maximization), not a lookup table. |
| 🟠 **SIM** | Stands in for something we cannot access with authorization (live NCRP feed, live bank core, SMS gateway, real ATM cash-sensor telemetry). Clearly labeled as simulated in the UI at all times. | Has a **defined interface** identical in shape to what the real integration would use, so swapping it later is a config change, not a rewrite. |
| ⚪ **FUTURE** | Documented interface / adapter stub only. Not built for the prototype. | Exists as an API contract and a paragraph of design intent, nothing more. |

## 3. Users and personas

| Persona | Who they are | What TRACE-X gives them | Access scope |
|---|---|---|---|
| **Citizen** | Files the original complaint | A complaint reference/incident ID, status updates | Write-once intake form; no dashboard access |
| **Investigator** | State/district cyber cell officer | Live case feed, fraud graph, risk map, explanation panel, recommended deployment, approve/reject action | Own jurisdiction only |
| **Supervisor** | Investigator's superior / nodal officer | Everything an investigator sees across their unit, approval escalation, audit review | Jurisdiction + subordinate cases |
| **Bank liaison** | Nodal officer at a partner bank (simulated org in prototype) | Alerts naming their own accounts/branches only, freeze-request workflow | Own bank's accounts only |
| **Auditor/Admin** | System owner, compliance | Full audit trail, model versions, user activity, no case-content edit rights | Read-heavy, cross-jurisdiction |

## 4. The end-to-end flow this system must support

This is the canonical flow every architecture document is built to serve (numbering carried through to `USER_FLOWS.md`):

1. Citizen reports a cyber-fraud complaint
2. Complaint is stored and assigned an incident ID
3. Investigator receives the complaint in real time
4. Fraud intelligence graph is constructed
5. Mule-network intelligence is generated
6. Exit vector is predicted
7. Likely location and time window are predicted
8. Dynamic risk field is generated
9. Prediction is explained
10. Intervention is optimized
11. Human investigator approves/rejects the recommendation
12. Intervention outcome is recorded
13. Immutable audit event is created
14. Outcome becomes feedback for future model improvement

## 5. Scope boundary at a glance

| Layer | Prototype reality |
|---|---|
| Complaint intake | 🟢 REAL — our own intake form/API standing in for NCRP; NCRP itself is ⚪ FUTURE |
| Fraud graph construction | 🟢 REAL, on synthetic data |
| Ring/mule detection | 🔵 ML-PROTO (community detection over the graph; GNN classifier as stretch) |
| Exit-vector / corridor prediction | 🔵 ML-PROTO (sequence/gradient-boosted model over hop features) |
| Location + time-window prediction | 🔵 ML-PROTO (XGBoost location scorer + survival model for time-to-cashout) |
| Dynamic risk field | 🟡 ALGO (deterministic fusion + decay function over H3 cells) |
| Explainability | 🟢 REAL (SHAP is a real, working library call against a real model) |
| Intervention optimization | 🟡 ALGO (greedy coverage-maximization; ILP as stretch) |
| Human approval gate | 🟢 REAL |
| Audit log | 🟢 REAL (hash-chained, tamper-evident, in our own DB) |
| Blockchain anchoring of audit roots | ⚪ FUTURE (stretch: anchor Merkle roots to a public testnet) |
| Bank/I4C notification | 🟠 SIM (webhook to a mock bank/I4C receiver we also build) |
| SMS/email delivery | 🟠 SIM in demo (real Twilio/SMTP call is trivial to wire, but sends to team-controlled numbers/inboxes only — never real citizens/banks) |
| Feedback/retraining loop | 🟢 REAL mechanism (outcome → labeled row); 🔵 ML-PROTO the retraining job itself runs, on synthetic feedback data |
| Live NCRP/I4C/bank integration | ⚪ FUTURE, explicit adapter contracts only |

**Rule that governs all of this:** the UI must never claim a live external connection it does not have. Every SIM component carries a visible "Simulated — no live connection" badge. This is a judge-credibility requirement (PROJECT.md §16), not a nice-to-have.

## 6. Success criteria for the prototype

A judge should be able to watch one incident travel through all 14 steps above, live, in under two minutes, and be able to ask "is that real or fake?" about any single screen and get a truthful, specific answer — never "kind of."

Functional acceptance:
- A complaint submitted through the intake form appears on an investigator's screen within seconds via WebSocket, without polling
- The graph, prediction, explanation, and optimizer all execute against that specific complaint's data — not a canned demo payload
- Rejecting a recommendation and re-running with a different team count produces a genuinely different, coverage-optimal deployment
- The audit log for that incident is queryable and its hash chain verifies

Non-functional:
- Every AI/ML component has a stated evaluation metric and a number attached to it (not "it works")
- Every simulated component is visually distinguishable from a real one in under one second of looking at the screen

## 7. Explicit non-goals (do not build these)

- No frontend/dashboard implementation in this phase — architecture only (per instruction)
- No attempt to obtain or use real citizen/bank/PII data
- No autonomous account freezing or blocking
- No claim of legal admissibility for any output ("investigative lead," never "evidence")
- No demographic/person-level profiling — the model scores *places and time windows*, never people
