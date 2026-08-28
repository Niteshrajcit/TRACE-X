# TRACE-X — Frontend Phase F3 Readiness: Case + Network Investigation

Investigation only — no files modified besides this one. Kept short per instruction.

---

## 1. Existing Implementation Assessment

The case workspace and a working network graph already exist from F1 — this is a redesign/elevation pass, not a build-from-zero:

- `layout/CaseWorkspace.tsx` — case header + 6-tab shell (`Overview`, `Network`, `Rings & Corridors`, `Prediction`, `Intervention`, `Action & Audit`), already real-data-driven, already has cross-tab focus state (`InvestigationFocusContext`, scoped per case).
- `pages/case/NetworkInvestigation.tsx` — a real `d3-force`-physics + hand-rolled SVG graph (`components/graph/NetworkGraph.tsx`), built from the real Neo4j-verified `explanation.graph_path.real_path` chain plus real detected rings. Selecting a node already sets `selectedAccountId`/`selectedRingId` in the shared focus context.
- `pages/case/RingsCorridors.tsx` — ring cards (real `RingSummary` fields) + a real H3 risk-field map with real exit-channel markers (decoded from `h3_cell` via `h3-js`).

**What F3 actually needs to change:** the graph is currently one panel among six equal tabs, rendered small (`height=460` in a ~66%-width column), with no zoom/pan and no filtering. It is not yet "the centerpiece." Case context (fraud type, amount, indicators) lives on a separate tab (`Overview`), not alongside the graph. This is the gap F3 closes — elevating and consolidating what exists, not replacing it.

---

## 2. Real Backend / API Data Available

Re-enumerated directly from the router source (`grep` over every `@router.get/post` in the codebase) rather than assumed — this is the **complete** real endpoint list relevant to F3:

```
GET  /v1/complaints/{id}                real complaint detail (+ latest_prediction, graph_summary, deployment_history)
GET  /v1/complaints/{id}/rings          real detected rings
GET  /v1/complaints/{id}/prediction     real corridor/exit prediction
GET  /v1/complaints/{id}/explanation    real SHAP-style factors + real Neo4j-verified graph_path.real_path
GET  /v1/jurisdictions/{id}/risk-field  real H3 risk field
POST /v1/transactions/ingest            write-only, service-role - NOT a data source for the UI
```

**Critical, precise finding — read carefully, it shapes §3-4:** there is **no `GET` endpoint for transactions, accounts, or entities anywhere in the backend.** Confirmed by listing every route, not inferred. This means:

- A literal "transaction timeline" (a scrollable list of this case's individual transactions with amounts/timestamps) **cannot be built from real historical data** — there is no way to ask the backend "give me this case's transactions." The only two real sources of transaction-shaped information are:
  1. **Ring aggregate stats** (already fetched, already real): `transaction_count`, `total_amount`, `average_transaction_amount`, `transaction_velocity`, `burst_ratio`, `fan_in/out_count`, `fan_in/out_amount` — summary numbers, not a row-by-row list.
  2. **Live `transaction.ingested` WS events** — real per-transaction data (`txn_id, amount, channel, hop_index, occurred_at`) but **only for transactions that happen to fire while the investigator is connected**; nothing before that moment is retrievable.
- Individual account/entity detail (device, phone, IP, VPA values, not just counts) is likewise not exposed by any endpoint — only the aggregate counts already on `RingSummary`.
- Jurisdiction `state`/`district`/`name` exist as real DB columns (confirmed in `app/db/models/jurisdictions.py`) but **are never exposed by any endpoint** — no jurisdictions list/detail route exists at all. The frontend cannot know a jurisdiction's real-world name or state today, at all, from any API call.

Everything else already used in F1 (rings, prediction, explanation, risk-field, complaint location) is confirmed real and stays available.

---

## 3. Proposed F3 Layout

One workspace, built by redesigning the existing `Network Investigation` tab (not a new route, not a merge of all six tabs — that would undo F1's already-good IA):

```
┌───────────────────────────────────────────────┬─────────────────────┐
│  NETWORK GRAPH (large, primary, ~65-70% width) │  Case context strip │
│  - real accounts, real verified hops           │  - fraud type,      │
│  - ring clusters, zoom/pan                     │    amount, status   │
│                                                 │  - suspicious       │
│                                                 │    indicators       │
│                                                 │    (already exist   │
│                                                 │    on Overview tab) │
│                                                 ├─────────────────────┤
│                                                 │  Ring intelligence  │
│                                                 │  - selected ring's  │
│                                                 │    real stats       │
│                                                 │  - fan-in/out,      │
│                                                 │    cohesion, txn    │
│                                                 │    aggregates       │
├─────────────────────────────────────────────────┴─────────────────────┤
│  Transaction activity (honest, aggregate-only + live session feed)   │
└─────────────────────────────────────────────────────────────────────┘
```

This satisfies "graph as centerpiece" literally (largest area, first visual weight) while pulling case-context and ring-intelligence into the same screen as *reactive side panels* driven by the graph's own selection state — clicking a node updates the side panel instantly, no tab switch. The "transaction activity" panel is deliberately labeled as aggregate + live, not a fabricated historical list (§2).

The `Overview` and `Rings & Corridors` tabs stay as they are — this page becomes the rich entry point, they remain the deeper-drill-down destinations, exactly as F1 already established.

---

## 4. Network Visualization Strategy

Keep `d3-force` + hand-rolled SVG (no graph library) — it's a real strength, not a gap. Concrete upgrades:

- **Size**: full primary-column width, `height` driven by viewport (e.g. `min(640, 70vh)`) instead of a fixed 460px in a cramped column.
- **Zoom/pan**: not currently implemented. Buildable with plain SVG `viewBox` manipulation + wheel/pointer handlers — no new dependency needed (`d3-zoom` exists but isn't installed; a ~30-line hand-rolled version matches the project's existing "no library where a small hand-rolled version suffices" pattern already used for the map projector).
- **Filtering**: real, honest filters only — by node kind (victim/hop/ring member/predicted exit, all real categories already in the data model) and by ring (show one ring's cluster in isolation). No filter on anything not already a real field.
- **Ring highlighting**: already exists (`highlightRingId` prop, added in F1) — F3 elevates its visual treatment (stronger glow/boundary, entrance animation on selection) rather than rebuilding the mechanism.
- **Selected-node behavior**: already exists (dim non-connected, show details panel) — F3 makes the details panel a permanent side panel instead of a conditionally-rendered block at the bottom of the tab.
- **What stays explicitly NOT built**: transaction direction/amount *on edges* (arrowheads, edge labels) — the real `real_path` is an ordered account chain with no per-hop amount/timestamp exposed (§2), so an edge cannot honestly carry a "₹50,000 →" label. If this is wanted, it depends on a backend change (out of scope, frozen).

---

## 5. India / Geographic Strategy

Scoped down from the brief's ambition to what's honestly buildable (§2's jurisdiction-name gap matters here):

- A full "India-wide, all-jurisdictions" map is **not buildable** today — no jurisdictions-list endpoint, no state/district exposed via any API.
- What *is* real and available: this case's own `location_lat/lon` (already used), and the exit-channel/ring-cluster coordinates already plotted on Rings & Corridors.
- **Proposed, honest scope for F3**: a compact geographic inset on the network page — the case's real incident coordinate plotted against a **static India outline** (a real geographic reference shape, not backend data — the same category of asset as an icon or a flag, not a fabrication) so the investigator sees "this is in Tamil Nadu / South India" at a glance. This establishes the visual identity the brief wants without inventing jurisdiction data the backend doesn't provide.
- This requires one new static asset (an SVG India boundary path) — not a new dependency, not fabricated data, just a reference shape. A full comparative multi-jurisdiction map is a later-phase item, contingent on a jurisdictions endpoint existing.

---

## 6. Interaction Flow

| Action | Effect |
|---|---|
| Click a graph node | Updates the side details panel; if the node is a ring member, sets `selectedRingId` (existing F1 mechanism) |
| Click a ring (side panel or Rings & Corridors) | Highlights that ring's cluster in the graph (existing `highlightRingId`) |
| Hover a node | Lightweight preview in details panel without committing selection |
| Zoom/pan | Local to the graph only, does not affect focus state |
| Select a ring here → open Rings & Corridors tab | `InvestigationFocusContext.selectedRingId` already persists across tabs (F1) — this is the literal F3→F4 bridge, already built, just needs to keep working |
| Click the geographic inset | Optional: jumps to the full Rings & Corridors risk-field map, consistent with existing "Open full Risk Intelligence" link pattern from F2 |

---

## 7. F3 → F4 Transition

F4 is "Ring + Corridor Intelligence" — already exists as the `Rings & Corridors` tab. The transition is already real and already works (`InvestigationFocusContext.selectedRingId` set on F3's graph carries into F4's ring cards, which already read and visually reflect it, per F1). F3's job is only to make *selecting* a ring on the graph feel deliberate and visually rewarding (§4's highlight treatment) — the actual state-passing mechanism needs no new work.

---

## 8. F3 Acceptance Criteria

1. **Real case data** — case context panel shows only fields from `ComplaintDetail`, no invented fields.
2. **Real transaction data** — the transaction-activity panel shows only real ring aggregates + real live-session events, explicitly labeled as such; no fabricated per-transaction history.
3. **Real graph relationships** — every solid edge traces to `explanation.graph_path.real_path`; every dashed (inferred) edge is labeled inferred, per F1's existing discipline.
4. **Real ring data** — ring intelligence panel shows only real `RingSummary` fields.
5. **Interactive network** — zoom, pan, node select, and ring highlight all functional at the new larger size.
6. **Ring highlighting** — selecting a ring anywhere in the workspace visually focuses it in the graph within the same interaction (no reload).
7. **Investigation-focus state** — `selectedRingId`/`selectedAccountId`/`selectedExitChannelId` continue to persist across this page and into Rings & Corridors / Prediction exactly as F1 built.
8. **Geographic context** — the India inset plots only the case's real coordinate; no other jurisdiction's data is implied or shown.
9. **Responsive** — see §9 below.
10. **Loading/error/empty** — independent states for the explanation fetch, the rings fetch, and (if added) the live transaction feed; no single failure blanks the whole page.
11. **Production build** — `tsc --noEmit` and `vite build` clean before F3 is considered done.
12. **No backend modifications** — verified by file-mtime check against backend source, same method used for F1/F2.

---

## 9. Responsive Behavior

- **Desktop/laptop**: graph + side-panel column, as in §3.
- **Tablet (≤1024px)**: side panels stack below the graph rather than beside it (reuses the existing `.split`→single-column collapse already in the design system); graph keeps a tall, wide canvas — never shrunk to card-size. Zoom/pan becomes the primary way to inspect a dense graph at this width.
- **Mobile (≤768px)**: graph gets a fixed, generous height (not proportional to a cramped column) with pinch/pan; the details/ring/transaction panels become a bottom sheet or sequential stack rather than three competing panels. The India inset is the first thing dropped at this width if space is tight — it's supporting context, not primary.
- Consistent with F1's established pattern: recompose, don't just shrink.

---

## 10. Risks / Limitations

- **The transaction-timeline gap (§2) is the single biggest constraint on this phase.** Any stakeholder expecting a literal chronological transaction list will not get one from real data — the honest aggregate-plus-live-feed treatment is the ceiling until/unless a backend transactions-read endpoint exists. This should be communicated before implementation starts, not discovered after.
- **The India map is necessarily a single-case inset, not the jurisdiction-wide visual the brief's language implies** — same reason (§2, §5). Worth confirming this scoped-down version is acceptable before building it.
- **Zoom/pan is new, hand-rolled interaction code** (no library) — more implementation risk than the rest of this phase, which is largely rearranging already-working pieces.
- **Graph performance at larger size/zoom is untested** beyond the current seed-data scale (same caveat as F1/F2's marker-density note) — fine for the demo dataset, unverified beyond it.
