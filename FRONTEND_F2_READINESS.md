# TRACE-X — Frontend Phase F2 Readiness: Mission Control

**Status:** Investigation only. No frontend files, backend files, or dependencies were modified in the production of this report.

---

## 0. Where Mission Control actually stands today

Same caveat as the F1 report, restated because it's just as true here: Mission Control is not a blank page. `frontend/src/pages/MissionControl.tsx` (213 lines) already exists, already renders real data end-to-end against the running backend, and already puts a map — not a card grid — at its visual center. F2 is a redesign-and-extend pass on a working screen, not a from-scratch build. This report evaluates that actual screen against the F2 brief's much more ambitious bar, and is specific about the gap between the two.

---

## 1. Mission Control Purpose

Restated in the terms the current implementation actually has to answer:

- **What is happening?** → the stat row + live activity feed.
- **Where is risk concentrated?** → the jurisdiction risk-field map.
- **Which investigations matter?** → currently unanswered. The one case list on the page ("Recent cases") is sorted by filing recency, not by anything resembling urgency. This is the single biggest gap between what exists and what F2 asks for.
- **What intelligence has TRACE-X generated?** → partially: ring counts and a coarse high-risk count exist as aggregate numbers, but nothing surfaces *which specific case* that intelligence belongs to at a glance.
- **What can the investigator do next?** → clicking a case row already opens the real `/cases/:id` workspace. This part already works and is real, not a mockup.

---

## 2. Existing Backend Data Available

Everything below was re-confirmed against the live backend for this report, not assumed from memory.

| Data | Endpoint | Real shape |
|---|---|---|
| Complaint list | `GET /v1/complaints` | `ComplaintSummary[]`: `complaint_id, incident_reference, fraud_type, amount, status, filed_at, jurisdiction_id, assigned_investigator_id`. **No lat/lon, no ring count, no prediction, no severity field on this list endpoint.** |
| Complaint detail | `GET /v1/complaints/{id}` | Adds `location_lat/lon`, `latest_prediction` (incl. `exit_vector.confidence_cone_deg`), `graph_summary.ring_count`, `deployment_history[]`. This is the *only* place location and ring/prediction data live — there is no bulk/aggregate version of it. |
| Risk field | `GET /v1/jurisdictions/{id}/risk-field?at=` | `{h3_cells: [{h3_cell, score}], generated_for}` — a real, jurisdiction-wide H3 field, live or historical. |
| Rings | `GET /v1/complaints/{id}/rings` | Per-complaint only; no jurisdiction-wide ring list exists. |
| Audit | `GET /v1/audit/events` | Auditor/admin only, unscoped; investigator/supervisor must supply `subject_id`+`subject_type` — **cannot be used for a jurisdiction-wide Mission Control feed for investigator/supervisor roles**, only for auditor/admin. |
| Live events | `WS /v1/ws` | Confirmed real topics (checked against `app/events/topics.py` and every actual `dispatcher.publish(...)` call site in the backend, not just the topic list): `complaint.created`, `intelligence.started`, `transaction.ingested`, `graph.updated`, `ring.detected`, `corridor_prediction.completed`, `exit_prediction.completed`, `risk_field.updated`, `explanation.generated`, `intervention.recommended`, `approval.required`, `intervention.approved`, `intervention.rejected`, `action.dispatched`, `outcome.recorded`, `feedback.created`. |

**Two precise findings from re-checking the backend source directly, not just the topic list:**

1. `transaction.ingested` is **real and actively fires** (published from `POST /v1/transactions/ingest`, carries `complaint_id`, `amount`, `channel`, `hop_index`) — it appeared repeatedly in the live audit trail during F1 testing — but it is **not currently in the frontend's `LiveEvent` TypeScript union** (`types/domain.ts`). At runtime this doesn't crash (the WS handler doesn't validate against the union, it's a bare type assertion), but `eventLabel()` falls back to the raw string `"transaction.ingested"` instead of a human label, because `EVENT_LABEL` has no entry for it. This is a real, fixable gap, not a design choice.
2. `spatiotemporal_prediction.completed` is declared in `topics.py` but has **zero publish call sites anywhere in the backend** — it is reserved/dead on the backend side today. Correctly, it's also not in the frontend's union. Nothing to fix here; noting it so F2 doesn't waste time building for an event that will never arrive.

**What does not exist anywhere in the backend, confirmed again for this report:**
- No jurisdiction-wide or bulk ring/prediction/risk-score endpoint. Any jurisdiction-level aggregate the frontend shows is necessarily computed client-side from individually-fetched complaint details.
- No case severity, priority, or risk-score field on any endpoint. `confidence_cone_deg` (tighter cone = more confident/actionable prediction) and `graph_summary.ring_count` are the only real signals that correlate with "this case is more developed/urgent than that one" — and only for cases that already have a prediction.
- No jurisdiction name field and no jurisdiction list endpoint (already established in F1; still true, still shapes how the jurisdiction selector must work).

---

## 3. API / Data Mapping

Every element the current page shows, or that this report proposes adding, mapped to its exact source — so nothing proposed below can quietly become fabricated in implementation.

| Element | Source | Fabrication risk if implemented carelessly |
|---|---|---|
| Active investigations count | `listComplaints` scoped, filtered by status not in `{closed, rejected}` | None — direct count |
| Rings detected count | Sum of `graph_summary.ring_count` across the fetched detail fan-out | Must keep disclosing "of N reviewed" — it is not a jurisdiction-wide total |
| High-risk predictions count | `latest_prediction.exit_vector.confidence_cone_deg <= 40` (existing, invented threshold) | The "40°" cutoff is a UI convenience, not a backend-defined severity boundary — must stay labeled as such, never presented as a model output |
| Pending approvals count | `deployment_history` entries with `status === "proposed"`, summed across the fan-out | Same fan-out-cap caveat as rings |
| Risk field map | `getRiskField` | None — real field |
| Case markers on map | `location_lat/lon` from the detail fan-out | None if plotted as-is; **would become fabrication if given a severity color not traceable to a real field** |
| Filing trend sparkline | Bucketed `filed_at` from the *summary* list (not the capped fan-out) | None — this already correctly uses the full scoped list, not just the 24-item detail sample |
| Live activity feed | `LiveEventsContext.keyedEvents`, filtered to jurisdiction | None, but currently shows no case identity — see §7 |
| Recent cases table | `scoped`, sorted by `filed_at` | None |
| **Proposed: investigative priority ranking** (§6) | Composite of `confidence_cone_deg`, `ring_count`, pending-approval count, amount — all real, all already fetched | Must be labeled explicitly as a derived/heuristic ordering, e.g. "Sorted by: prediction confidence, ring activity, pending approvals" — never "AI risk score" or anything implying a backend model produced it |
| **Proposed: case-to-hex linking** (§5, §7) | Client-computed via `h3-js latLngToCell(lat, lon, resolution)` at the same resolution as the fetched risk field, matched against `location_lat/lon` | None — this derives a real H3 index from a real coordinate; it must not be presented as if the backend associated the case with that cell (the backend never does) |

---

## 4. Page Information Architecture

What the current single-scroll layout gets right, and what should change:

**Keep:** stat row at top (fast orientation), map as the visual anchor, a case-entry-point table at the bottom. This structure matches the brief's own ask reasonably well already — the issue is what's *inside* each piece, not the overall skeleton.

**Change:**
- The "Recent cases" table should not be the *only* case-facing panel. Add a **Priority queue** panel (ranked by the composite in §3, not recency) as a peer to the map — this is what actually answers "which investigations matter," which the current recency-sorted table cannot.
- The live activity feed and the priority queue should sit closer together conceptually (both answer "what should I look at right now"), while the map and the trend sparkline are the "context" pairing (both answer "what does the overall picture look like").
- Nothing here should become a fifth or sixth panel competing for attention — the brief explicitly warns against "a collection of cards." Two clearly-differentiated zones (Overview/context vs. Action/priority) is the right level of structure, not more.

Proposed layout, same primitives already in the design system (`split`, `panel`, `grid`), no new layout components needed:

```
[ stat row: 4 cards ]
[ MAP (large, primary)              ] [ Priority queue (ranked, real) ]
[                                    ] [ Live activity (case-linked)  ]
[ Filing trend (small, secondary)   ]
[ Recent cases (recency, secondary) ]
```

The map keeps the largest single footprint on the page - it already does; F2 doesn't need to resize it, it needs to make it *do more* (§5, §7).

---

## 5. Primary Visualization

The risk-field map is already the right choice and already exists (`RiskMap.tsx`, H3 hexagons, no tile dependency, hand-projected). What's missing to make it feel like "the primary intelligence surface" rather than "a heatmap with some dots on it":

1. **Marker clicks currently do nothing.** `RiskMap`'s `MapMarker` interface already supports `onClick` and `highlighted` (added in F1, used on the Rings & Corridors page) — Mission Control's own marker array simply never passes them. Wiring this up is close to free and is the single highest-leverage fix here: clicking a case's pin should open that case, exactly like clicking its row does.
2. **All case markers look identical today** — every one renders as the same "victim" pin regardless of whether that case has zero rings or four. Differentiating markers by the same composite signal used for the priority queue (§3) — without inventing a new visual language, just reusing the existing risk-color ramp already defined for hex cells — makes the map itself answer "which of these dots matters" instead of only the field color doing that work.
3. **No hex-to-case drill-down.** Clicking a hex cell today does nothing on Mission Control (unlike the Risk Heatmap page, which has a full hotspot list). A lightweight version — click a cell, filter the priority queue to cases whose real coordinate falls in that cell (via the real `h3-js` conversion in §3, not fabricated) — turns the map from a picture into an actual investigative tool without duplicating the full Risk Heatmap page's scope.

None of this requires a new mapping approach or a new dependency — it's wiring the map component F1 already built more completely into this specific page.

---

## 6. Supporting Visualizations

- **Stat row** — keep, but the "High-risk predictions" and "Rings detected" cards should each be a real navigational shortcut (clicking one filters the priority queue), not a static number, since the brief explicitly disfavors decoration that doesn't serve investigation.
- **Filing trend sparkline** — keep as-is; it's small, honest (built from the real unfiltered `filed_at` list, not the capped fan-out), and answers a real question ("is volume rising").
- **Priority queue (new)** — a ranked list, same visual language as the existing case table, but sorted by the composite in §3, with the ranking *reason* visible per row (e.g., "4 rings · 22° cone · 2 pending") rather than a bare score, so the investigator can see why something is ranked highly instead of trusting an opaque number. This is the direct answer to the brief's "which investigations matter."
- **Live activity feed** — keep the existing animated-entry treatment from F1, but see §9 for the case-identity gap that needs closing.

**Explicitly not recommended:** a second map, a 3D globe, a gauge/dial widget for "system health," or any visualization whose only real data is a single scalar dressed up as something more complex. The brief's own anti-pattern list ("do not simply make cards glow… do not overuse 3D") rules these out, and there's no backend data that would make them anything other than decorative.

---

## 7. Interaction Model

| Action | Current behavior | F2 behavior |
|---|---|---|
| Click a case row | Navigates to `/cases/:id` | Unchanged — already correct |
| Click a map marker | **Nothing** | Navigate to `/cases/:id` (same target as the row click) |
| Hover a map marker | Nothing | Show the incident reference + the same "why ranked" reason as the priority queue row, reusing the map's existing hover-tooltip pattern (already built for hex cells) |
| Click a hex cell | Nothing | Filter the priority queue to cases whose real coordinate resolves into that cell |
| Click a priority queue row | N/A (doesn't exist yet) | Same as case row: navigate to `/cases/:id`, and also pan/highlight the corresponding map marker (mirrors the cross-panel focus pattern F1 already established for the case-workspace pages) |
| Click a live activity item | Currently non-interactive, no case identity shown at all | Once the event is resolved to an incident reference (§9), clicking it navigates to that case |
| Switch jurisdiction (auditor/admin) | Re-fetches everything | Unchanged — already correct, already the pattern used elsewhere |

The throughline: every interactive element on this page should point at the same real destination (a real case), the same way the case-workspace pages already cross-link through `InvestigationFocusContext`. Mission Control doesn't need its own version of that context — it only has one real "focus" target (a case), not the multi-entity focus a case workspace needs.

---

## 8. Real Investigation Navigation

The entry point already works correctly today (`navigate('/cases/' + id)`, a real route, a real `CaseWorkspace` mount, real data). F2 does not need to build this — it needs to make sure the *highest-value* entry point is the one the demo actually uses. Concretely: the priority queue's top row, not "Recent cases"' newest row, should be what a demo operator clicks at the 0:00–0:30 mark, because it's the row the interface itself is claiming matters most — which only works once §6's ranking exists.

---

## 9. WebSocket / Live Intelligence Strategy

**Which events belong on Mission Control**, reasoned from what an investigator watching the whole jurisdiction (not one case) actually needs to notice:

- `ring.detected`, `intervention.recommended`, `approval.required`, `intervention.approved`, `action.dispatched`, `outcome.recorded` — all directly relevant at jurisdiction scope; these are the events that should visibly arrive.
- `complaint.created`, `graph.updated`, `transaction.ingested`, `corridor_prediction.completed`, `exit_prediction.completed`, `explanation.generated` — real, but pipeline-internal/high-frequency; appropriate for a compact feed entry, not for anything more prominent (no toast, no map pulse) or the page would feel noisy rather than "live."
- `risk_field.updated` — relevant, but should trigger a **map refresh indicator**, not a feed line — it's telling the investigator "the field you're looking at just changed," which is a different kind of signal than "something happened to a case."
- `intervention.rejected`, `feedback.created` — real, low-frequency, fine to include in the feed at the same weight as the others; no special treatment needed.

**The concrete gap to close:** none of these events carry a jurisdiction-level display name, but every one that has a `complaint_id` can be resolved to an `incident_reference` by joining against the already-loaded `scoped` complaint list (a real, already-fetched dataset — this is a join, not a fabrication) — e.g. "Ring detected — TX-2026-21AC6D38" instead of the current bare "Fraud ring detected." This turns the feed from an activity log into something an investigator can act on directly, and is a small, mechanical change once identified (it's exactly why §2's `transaction.ingested` gap and this join both belong in the same implementation pass).

**A live map, not just a live feed:** `risk_field.updated` firing should cause the map to visibly indicate a refresh is available (a small "field updated — refresh" affordance, or an automatic silent re-fetch with a brief transition on the changed cells) rather than the map only ever updating on a hard page load. This is the concrete version of the original brief's "risk should visually evolve rather than being a static coloured map," scoped to what's actually buildable from the real event.

---

## 10. Responsive Design

Reuses the tiers F1 already established (desktop / tablet-icon-rail / mobile-drawer) — Mission Control doesn't need its own breakpoint scheme, it needs the existing `split` and `grid-cols-4` behavior applied consistently, plus two Mission-Control-specific concerns:

1. **Marker touch targets.** The map's marker circles (`r=6`, `r=8` when highlighted) are sized for mouse precision, not touch. On the tablet/mobile tiers, markers need a larger invisible hit-area (a transparent larger circle behind the visible one) — this is the one place F1's general responsive pass didn't reach because it's specific to this component's usage on this page.
2. **Priority queue vs. map on mobile.** At mobile width, the map should not be pushed below both the stat row *and* a full ranked list before it's visible — the map is the primary visual and should appear first after the stat row even when everything else stacks to one column, with the priority queue and recent-cases table following it. This is a content-order decision (`order` in CSS or JSX ordering), not a new layout primitive.

---

## 11. Loading / Error / Empty States

Mission Control has three independent async sources today (`listComplaints`, the N+1 detail fan-out, `getRiskField`) plus the WS connection — each needs its own honest state, and they must not block each other:

- **Loading:** the map's own loading state (already exists) must not wait on the detail fan-out — a jurisdiction with a slow 24-complaint fan-out should still show the risk field the moment it arrives, not a blank page. This already works correctly today (the map and the stat cards are independent `useApi` calls) — F2 must preserve that independence when adding the priority queue, not accidentally couple it to a single combined loading gate.
- **Empty:** "no cases yet" and "no risk field yet" already exist and are honest. The new priority queue needs its own empty state distinct from "recent cases is empty" — e.g., "No cases with active predictions yet" when there are cases but none have reached the prediction stage, which is a real, distinguishable condition from "no cases at all."
- **Error:** none of the three sources currently have a visible error state on this page — a failed `getRiskField` or failed fan-out call silently resolves to `null`/empty rather than surfacing a retry option. This is a real gap: an investigator watching a blank map has no way to know whether that means "no risk yet" or "the request failed."
- **Partial data:** the fan-out cap (24) already discloses itself via the "/N reviewed" unit label, but only on one stat card. Given the priority queue depends on the same capped fan-out, it needs the same disclosure directly in its own panel header, not just inherited implicitly from a stat card elsewhere on the page.

---

## 12. F2 Acceptance Criteria

1. **Visual quality** — the map remains the largest, most visually prominent element on the page at every breakpoint down to tablet; no new decorative element (glow, 3D, gradient) is added without a real data justification.
2. **Information hierarchy** — a viewer can state, within 10 seconds of looking at the page, which single case TRACE-X considers most worth investigating right now, and why (visible reason, not just a rank number).
3. **Real backend data** — every displayed number or marker traces to a cited real endpoint per §3's table; any composite/derived value is visibly labeled as derived, never presented as a backend output.
4. **Real case navigation** — every clickable surface that represents a case (row, marker, priority queue entry, resolvable live event) navigates to the same real `/cases/:id` route with no dead clicks.
5. **Risk visualization** — the map communicates both the jurisdiction-wide field (already real) and per-case standing (new) without conflating the two color languages.
6. **Live event integration** — at least the six jurisdiction-relevant event types in §9 visibly arrive in the feed with a resolved case reference where one exists, without introducing fabricated events or a fake "demo mode."
7. **Loading states** — the three independent data sources load and render independently; no source's latency blocks another's.
8. **Empty states** — at least three distinguishable empty conditions are handled: no cases, cases but no risk field yet, cases but none with predictions yet.
9. **Error states** — a failed fetch on any of the three sources is visibly distinguishable from "genuinely empty," with a retry action.
10. **Responsive behavior** — the map stays usable and appears before secondary panels at every breakpoint; marker hit-areas are touch-appropriate below 1024px.
11. **Performance** — the detail fan-out stays capped and disclosed; no uncapped per-case fetch is introduced by the priority-queue or hex-drilldown features.
12. **Accessibility** — new interactive markers and priority-queue rows follow the `role="button"`/`tabIndex`/`onKeyDown`/`:focus-visible` pattern F1 established for custom clickable elements, applied consistently rather than added ad hoc.

---

## 13. Implementation Order

1. Wire existing `MapMarker.onClick`/`highlighted` into Mission Control's own marker array (§5.1) — near-zero cost, immediate real interactivity.
2. Add `transaction.ingested` to the frontend's `LiveEvent` union and `EVENT_LABEL` map (§2) — a small, contained type-completeness fix that the live feed and priority queue both benefit from.
3. Resolve live events to incident references via the already-loaded complaint list (§9) — mechanical, no new fetch.
4. Build the priority-queue ranking and panel (§3, §6) — the highest-value, most involved piece; depends on nothing else in this list.
5. Wire map ↔ priority-queue cross-highlighting and hex-to-case filtering (§5.2, §5.3, §7) — depends on #4 existing.
6. Add the three missing error states and the priority-queue-specific empty state (§11).
7. Responsive marker hit-area and mobile content-order pass (§10) — last, since it's a refinement of everything above rather than a new capability.

## 14. Risks / Tradeoffs

- **The composite "priority" ranking is real data, invented arithmetic.** Every input is real; the weighting between "ring count" and "prediction confidence" is a frontend judgment call with no backend authority behind it. This must be disclosed in the UI (the visible "why ranked" reason from §6) precisely so it never gets mistaken for a model score in front of a judge or a real investigator.
- **The fan-out cap remains a real scaling ceiling.** Making the priority queue depend on the same 24-item capped fan-out means a jurisdiction with more active cases than that will have a genuinely incomplete priority queue, not just an incomplete stat card. This is the same honest tradeoff F1 already flagged for Mission Control's stats, now extended to a more visible feature — worth a clearer on-page disclosure than today's single small unit label.
- **Hex-to-case matching is an approximation at the map's rendered resolution**, not a backend-verified association — two cases whose real coordinates are meters apart could resolve to different cells or the same one depending on H3 resolution and cell-boundary proximity. This is honest (real coordinates, real H3 function) but should be communicated as "cases located in this area," not "cases assigned to this cell" — the backend has no concept of the latter.
- **Marker-density performance at scale is untested** beyond the current seed dataset (dozens of cases per jurisdiction) — differentiated, clickable markers with hover tooltips on a jurisdiction with hundreds of cases would need clustering, which is out of scope for F2 and should be flagged rather than silently deferred.
