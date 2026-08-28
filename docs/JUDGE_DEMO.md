# TRACE-X — Judge Demo

> Depends on: [PRODUCT_EXPERIENCE.md](PRODUCT_EXPERIENCE.md) §1 (locked journey), §4 (event sequence), §7 (scenarios), [DEMO_ARCHITECTURE.md](DEMO_ARCHITECTURE.md) (how the synthetic harness actually drives this live). This is the judge-facing script; DEMO_ARCHITECTURE.md is the engineering behind it.

---

## 0. Format

5 minutes, live, primary run is **Scenario A (ATM Cash-Out)** per PRODUCT_EXPERIENCE.md §7's sequencing recommendation — it is the PS's literal example and exercises every pipeline stage in its simplest, most legible form. If time allows at the end, a 30-second coda shows Scenario B or C's `#intervention` tab side-by-side to prove the pipeline generalizes — this is a bonus beat, not core, and is cut first if time is short.

Two presenters, matching the pitch split already established in PROJECT.md §15: one drives the keyboard, one narrates and faces the judges. Narration below is intentionally short — the screen should be doing the convincing, not a voiceover.

---

## 1. Exact starting screen

**Investigator Command Center** (`/console`), already logged in as an investigator, jurisdiction feed empty or showing only unrelated historical (closed) cases — never a pre-loaded version of the demo incident. The top bar's "Live" indicator is visible and green before anything happens, so its later behavior (staying green throughout) is a deliberate, checkable claim, not an assumption.

A second browser tab/window, off to the side or on a second monitor, shows the **Citizen Complaint Portal** (`/report`) — this is the tab the presenter will submit from, in full view of the judges, so the "citizen" step is not narrated as having happened off-screen.

---

## 2. Minute-by-minute script

### 0:00–0:20 — The complaint (Flow A)
**Action**: Presenter fills the Citizen Complaint Portal live — fraud type, ₹2,00,000 amount, brief description — and submits.
**System does**: `POST /v1/complaints` → hashes PII → creates the complaint → returns an incident reference → emits `complaint.created`.
**Audience sees**: The Portal shows the incident reference immediately. Within the same second, on the *other* screen, a new card animates into the Investigator Command Center feed — no refresh, no click.
**We say**: *"A citizen just filed this fraud complaint. Watch the investigator's screen — nobody touched it."*
**Wow moment #1**: the live arrival, unprompted, on a screen nobody interacted with.

### 0:20–0:35 — Opening the incident
**Action**: Presenter clicks the new card, opens the Incident Workspace.
**System does**: loads complaint + transaction summary (empty so far) + intelligence status = `New`.
**Audience sees**: the sticky header, the empty-but-specific state ("No money movement detected yet") per DESIGN_SYSTEM.md §10 — not a broken-looking blank screen.
**We say**: *"Right now this is just a report. Nothing has moved yet."*

### 0:35–1:15 — The pipeline executes live (Flow B)
**Action**: Presenter triggers (or the pre-scripted scenario auto-plays via the synthetic harness's live-drip mode, DEMO_ARCHITECTURE.md §3) the transaction chain — victim → mule 1 → mule 2 → mule 3, at accelerated but visible pace.
**System does**: each `transaction.ingest` call fires `graph.updated`, then once enough hops exist, `exit_prediction.completed`, `spatiotemporal_prediction.completed`, `risk_field.updated`, `explanation.generated`, in sequence, per PRODUCT_EXPERIENCE.md §4's table.
**Audience sees**: the pipeline status strip fills step by step in real time; the `#graph` tab grows new nodes live; the map preview lights up with the directional exit-vector cone, then the full hex risk field; the sticky-header headline populates with the real, computed number — *"87% probability of cash-out in this corridor, 30–60 minutes."*
**We say**: *"This isn't a canned number. Every one of these steps just ran, on this specific complaint, in front of you."*
**Wow moment #2**: the graph building itself, mule accounts appearing hop by hop, ending in a real probability the audience just watched get computed.

### 1:15–1:45 — The explanation (Flow C, part 1)
**Action**: Presenter clicks the top-ranked risk cell.
**System does**: opens the `explanation` payload already pre-computed at `explanation.generated`.
**Audience sees**: SHAP factor bars, the graph path highlighted from victim to this cash-out point, one comparable historical case referenced.
**We say**: *"No black box. Here's exactly why — three hops in eighteen minutes, and a sibling account from this same ring cashed out four kilometers from here last month."*
**Wow moment #3**: a specific, human-readable, evidence-backed reason — not a bare score.

### 1:45–2:30 — The optimizer (Flow C, part 2)
**Action**: Presenter sets available teams to 2, runs the optimizer; then changes it to 3 live to show re-optimization.
**System does**: `POST /v1/cases/{id}/optimize-deployment` → greedy coverage-maximization → returns assignment + coverage numbers.
**Audience sees**: two deployment pins appear — deliberately not the two highest-scoring cells — plus the naive-top-N toggle showing the difference; the coverage-gain percentage stated on screen.
**We say**: *"With two teams, sending them to the top two dots wastes one of them — they overlap. Watch what changes when I ask for three instead."*
**Wow moment #4**: the assignment visibly *not* being "just the top N," and changing live when the constraint changes.

### 2:30–3:00 — Approval (Flow D)
**Action**: Presenter clicks Approve, with the mandatory justification field briefly shown (typed or pre-filled).
**System does**: `intervention.approved` → Action module fires only now → signed webhook to the mock bank receiver.
**Audience sees**: the Alert Inbox screen (second window or quick tab-switch) receives the alert live, marked `Simulated — [Bank] · no live connection` per the data-mode chip design (PRODUCT_EXPERIENCE.md §6) — stated honestly, not hidden.
**We say**: *"No automated freezing. A human just approved this, and that approval is the only thing that let an alert go out — the system cannot send this on its own."*

### 3:00–3:30 — Outcome and the audit trail (Flow E)
**Action**: Presenter records an outcome ("cash-out prevented"), then opens the `#audit` tab.
**System does**: `outcome.recorded` → `feedback.created`; audit timeline reflects every event from the last three minutes, in order.
**Audience sees**: the full chronological trail, hash values visible on click, and the closing line — *"Outcome recorded as a training label for the next model update."*
**We say**: *"Nothing about this incident happened off the record, and the outcome just became a lesson for the next case."*
**Wow moment #5**: the loop visibly closing — complaint to learning signal, on one screen, inside three minutes.

### 3:30–4:00 — Chain verification (technical credibility beat)
**Action**: Presenter opens the Admin Audit screen, clicks "Verify chain."
**System does**: `GET /v1/audit/verify-chain` recomputes the hash chain live.
**Audience sees**: `valid: true`, computed on demand, not a static claim.
**We say**: *"That's not a screenshot of a log — that's a live cryptographic check running right now."*

### 4:00–4:45 — The honesty beat (pre-empting the hardest question)
**Action**: Presenter hovers/clicks the provenance chips already visible throughout (`Synthetic data`, `Simulated — Bank`).
**We say**: *"Every one of these labels has been on screen the whole time. This complaint's data is synthetic, calibrated against published NCRB and I4C fraud statistics. This alert went to a system we built to stand in for a real bank, using the exact same signed API call a real bank integration would receive. We are not going to tell you this is connected to NCRP or a real bank — it isn't, yet — and the reason we can say that clearly is that the architecture was built so swapping in a real feed is a configuration change, not a rewrite."*
**Why here, not at the start**: leading with disclaimers primes skepticism before the audience has seen anything work; placing it after five real "wow" moments lets the honesty read as confidence, not hedging.

### 4:45–5:00 — Close
**We say**: *"Complaint to actionable, approved, audited intervention — under two minutes of system time, five minutes of us talking. The money is still in the system. That's the whole idea."* (Callback to PROJECT.md §12's close, delivered as the literal thing the judges just watched, not a slide claim.)

---

## 3. Technical evidence deliberately surfaced during the run

- Real-time push with no refresh/poll (visible by never clicking a refresh button)
- A genuinely computed probability and time window, arrived at while the audience watched (not typed into a slide beforehand)
- A specific, factor-level explanation tied to this run's actual graph path
- An optimizer output that visibly changes with a changed constraint, and visibly differs from the naive baseline
- A hard approval gate (no alert path exists without it — stated and structurally true, not just claimed)
- A live, on-demand cryptographic chain-verification result
- Consistent, honest provenance chips throughout, never contradicted by a claim in the narration

## 4. If something fails

**Principle**: never silently switch to fallback without narrating it — a judge respects "here's what we do when infrastructure hiccups" far more than a suspiciously smooth recovery.

| Failure | Response |
|---|---|
| WebSocket disconnects mid-demo | Top-bar indicator shows "Reconnecting…" per DESIGN_SYSTEM.md §10 — pause narration for the few seconds it takes to reconnect, say *"that's the live connection recovering — watch the indicator,"* and continue once reconnected. Do not refresh the page, which would hide the honest reconnect behavior |
| A pipeline stage errors (e.g. optimizer fails to return in time) | Fall back immediately and explicitly to the pre-recorded run of the *same* scenario (DEMO_ARCHITECTURE.md §6 — recorded from a real run, regenerated whenever the pipeline changes, never staged separately): *"We'll switch to a recorded run of this exact scenario so we don't lose your time — everything you're about to see ran for real on this system this morning."* |
| Venue Wi-Fi/hardware failure before the demo starts | Go straight to the recorded run, same framing, no attempt to debug live in front of judges |
| A judge asks to change something live (e.g. "try 5 teams") | This is a genuine opportunity, not a risk — the optimizer re-run in §2's 1:45–2:30 beat is built to take exactly this kind of live input; take it if time allows |

## 5. Fallback demo mode

DEMO_ARCHITECTURE.md §6's recorded run, kept current (regenerated on every pipeline change, timestamped). It is the *same* scripted scenario (`demo_scenario.yaml`) played through the *same* live system in a controlled recording session — never a separately staged/edited sequence — so switching to it mid-demo changes nothing about what's claimed to be true.
