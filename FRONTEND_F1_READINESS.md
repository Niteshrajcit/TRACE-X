# TRACE-X — Frontend Phase F1 Readiness Report

**Status:** Investigation only. No frontend files, backend files, or dependencies were modified in the production of this report, per instruction. This document is the only artifact created.

---

## 0. A fact that changes how to read this report

Before anything else: **this is not a pre-implementation review of an empty or placeholder frontend.** `frontend/` currently contains a complete, working, 8-page implementation — 4,463 lines of TypeScript/TSX across 31 files, plus a 1,219-line stylesheet — built and verified end-to-end against the real, running backend (real login, real complaints, real rings, real predictions, real approvals, real WebSocket events, a full production `vite build` passing under strict TypeScript).

That matters for how F1 should be scoped. The request frames F1 as "the foundation before building the major investigation pages" and asks whether things should be **reused / reworked / replaced / new**. Given what's already there, F1 is realistically a **hardening and systematization pass over an existing implementation**, not a from-scratch foundation. Treating it as the latter would mean discarding working, backend-verified code for no functional gain — that would be a regression dressed up as a fresh start.

This report evaluates the *actual current codebase* against the F1 rubric, section by section, and is deliberately critical about where it falls short — because most of its shortcomings are real, not hypothetical. Where the existing implementation already satisfies a requirement, this report says so plainly instead of inventing new work to justify a "foundation phase."

---

## 1. Current Frontend Assessment

### 1.1 Structure

```
frontend/src/
  api/client.ts               typed wrapper over every real backend endpoint in use
  types/domain.ts              hand-mirrored backend Pydantic schemas (no codegen)
  context/  AuthContext, CaseContext, LiveEventsContext, LastCaseContext
  hooks/    useApi, useLiveEvents, useJurisdictionScope
  layout/   AppShell, GlobalNav, CaseWorkspace, caseTabs
  components/
    ui/       primitives.tsx (StatCard, Pill, Panel, Timeline, empty/loading/error states)
              charts.tsx (ProbabilityRing, ConfidenceBar, CoverageBar, TimeWindowBar, Sparkline, BearingCompass)
    map/      RiskMap.tsx (H3-hex risk field, hand-projected, no external map/API-key dependency)
    graph/    NetworkGraph.tsx (d3-force physics + hand-rolled SVG rendering)
  pages/
    Login, ComplaintPortal, MissionControl, CaseList, RiskHeatmap, AuditTrail
    case/  CaseOverview, NetworkInvestigation, RingsCorridors, PredictionExplanation,
           InterventionApproval, ActionOutcomeAudit
  styles/index.css              the entire design system, as CSS custom properties + utility classes
```

### 1.2 Stack

- React 18.3, TypeScript 5.6 (`strict: true`, `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`), Vite 8, react-router-dom v7.
- Visualization: `h3-js` (real hexagon geometry from the backend's real `h3_cell` strings), `d3-force` (physics only — rendering is hand-rolled SVG), `lucide-react` (icons), `framer-motion` (installed, **not used anywhere** — see §2).
- No charting library, no map-tile library, no state-management library, no CSS framework, no component library, no test framework.

### 1.3 What each of the 8 pages actually is today

| # | Page | File | Real data wired |
|---|------|------|------|
| 01 | Mission Control | `pages/MissionControl.tsx` | listComplaints, per-complaint detail fan-out (capped at 24), risk-field, live WS |
| 02 | Case / Complaint | `pages/case/CaseOverview.tsx` | complaint detail, rings, audit events, assign/close |
| 03 | Network Investigation | `pages/case/NetworkInvestigation.tsx` | explanation's real Neo4j-verified `graph_path`, rings |
| 04 | Ring + Corridor | `pages/case/RingsCorridors.tsx` | rings, `latest_prediction.exit_vector`, risk-field |
| 05 | Risk Heatmap | `pages/RiskHeatmap.tsx` | risk-field (live + historical `at=` replay), complaint locations |
| 06 | Prediction + Explanation | `pages/case/PredictionExplanation.tsx` | prediction, ranked_locations, explanation (top_factors, plain_language) |
| 07 | Intervention + Approval | `pages/case/InterventionApproval.tsx` | optimize-deployment, decision |
| 08 | Action → Outcome → Audit | `pages/case/ActionOutcomeAudit.tsx` | outcome, live WS feed, audit events, verify-chain |

Every one of these is live-tested against the running backend, not a mock. This is the single biggest fact this report has to reconcile with an F1 brief written as if page-building hasn't started.

### 1.4 What is genuinely still missing or weak

This is the honest part. See §2.

---

## 2. Problems With the Current UI

Ranked roughly by severity.

1. **The navigation was, until a follow-up fix this session, actively misleading.** The sidebar listed exactly 4 links (Mission Control, Cases, Risk Intelligence, Audit Trail). The other 6 pages existed and worked, but were only reachable *after* opening a specific case — nothing in the shell told a first-time viewer they existed. A stakeholder opening the app would reasonably conclude "there are 4 pages," not 8. This has since been patched (a permanent "Case Workspace" nav section, populated once any case is opened, shows all 6 case-scoped pages at all times), but it's a clear example of a real information-architecture failure that shipped and had to be caught by a user, not by design review. **F1 must not repeat this class of mistake** — see §7 for the fix made and §16 for what's still incomplete about it.

2. **`framer-motion` is a dead dependency.** It's in `package.json`, it was installed specifically because the original brief called for "purposeful animation," and it is imported **nowhere**. The entire animation language today is 4 CSS `@keyframes` (a live-dot pulse, a hex hotspot pulse, a spin, and an unused skeleton shimmer) plus 5 basic `transition:` declarations (hover states). There is no page-transition choreography, no reveal-on-arrival animation for a fresh prediction, no orchestrated "the system is thinking" sequence — despite that being an explicit, named goal in the original product brief ("selecting a ring should focus the graph, highlight the map corridor, update the risk panel, and reveal the prediction panel"). None of that cross-panel choreography exists. Right now, selecting something in one panel does not animate or even update any other panel — see #4.

3. **No skeleton loading states, despite one being defined.** `.skeleton` exists in the stylesheet and is used by zero components. Every loading state today is a centered spinner + one line of text (`LoadingBlock`). For a "premium intelligence product" pitch, a spinner is the least impressive way to say "loading" — it communicates nothing about what's about to appear.

4. **No cross-panel selection state.** This is the most important functional gap relative to the *stated product vision*, not just visual polish. Today, "select a ring" on the Rings & Corridors page does nothing to the map, the Network page's graph, or the Prediction page — because there is no shared state for "the ring/account/prediction currently under investigation" above the per-page level. Each of the 6 case pages independently fetches and renders its own slice of the same case. The result is 6 correct pages that don't feel like *one* investigation the way the brief explicitly asks for. This is a real architectural gap, not a paint job — closing it needs a shared "investigation focus" concept (see §8, §16).

5. **No modal/drawer/toast pattern exists at all.** The F1 brief asks for a position on "Modals/Drawers" and "Notifications" as UI primitives. Today there are literally zero of either. Every interactive flow (assign, close case, approve/reject, record outcome) is an inline expanding form inside a panel. That's a legitimate design choice (it avoids the generic-SaaS "everything is a modal" feel the brief explicitly warns against), but it means live system events (ring detected, prediction completed, intervention dispatched) surface *only* by being appended to a small in-page list — there is no toast/notification-center concept for something happening while the investigator is looking elsewhere. Given the product's core pitch is a live intelligence feed, this is a meaningful gap for the "real-time system feeling" requirement.

6. **Single JS bundle, no code-splitting.** `vite build` currently produces one ~486 KB (~153 KB gzipped) JS file for the entire app — login, portal, and all 8 investigator pages together. That's not large in absolute terms yet, but it will grow every time a new page or visualization is added, and nothing today would stop it from becoming the "why is the demo laptop slow to boot" problem. Route-level code-splitting (`React.lazy` per page) is trivial to add and currently entirely absent.

7. **Zero automated tests.** Every verification this session was manual, live-browser testing against the real backend. That's genuinely valuable (it caught two real bugs — see §19) but it isn't repeatable. There is no unit test, no component test, no E2E test, no CI wiring. For a "verified and frozen" backend paired with an actively-changing frontend, this is backwards: the frontend is exactly the layer that most needs a regression net right now.

8. **The design system was never written down before this document.** Every token — the color values, the two accent colors, the radius scale, the type scale — existed only as CSS custom properties, discoverable only by reading `styles/index.css` top to bottom. There was no design-tokens document, no component inventory, no naming rationale anyone could review without reading source. §5 of this report is the first time this system has been specified as a document rather than as an artifact of implementation.

9. **Accessibility is inconsistent.** Two clickable-table-row instances were fixed this session (added `role="button"`, `tabIndex`, `onKeyDown`, a `:focus-visible` style) only because manual testing happened to catch them. The map and network graph are raw `<svg>` with no `role`, no `aria-label` on individual hexagons/nodes, and no text alternative for what they're showing. Live WebSocket events that change on-screen state (a new ring detected, an outcome recorded) fire with no `aria-live` region, so a screen-reader user gets no notification at all that something changed. Status pills communicate severity by color only in the DOM (though the color choices are colorblind-considerate — see §4.6 — there is no accompanying icon or shape differentiation beyond a text label, which does help, but isn't verified against WCAG 1.4.1 formally).

10. **Mission Control's "aggregate stats" are an N+1 fetch, capped and silently truncated.** Ring counts, high-risk counts, and pending-approval counts are computed by fetching full detail for up to 24 complaints client-side and summing. This is *honest* (no fabricated aggregate endpoint exists on the backend, and the cap is disclosed in the UI as "/ N reviewed"), but it will not scale past a few dozen complaints per jurisdiction, and every jurisdiction switch re-triggers up to 24 parallel detail fetches. This was a reasonable choice for a demo-scale seed dataset; it is not a real foundation for anything beyond that.

11. **Responsive behavior is reflow, not redesign.** The two breakpoints (1180px, 860px) collapse grid columns and turn the sidebar into an off-canvas drawer. That's adequate, but the brief's original ask ("must recompose layouts, not just shrink") isn't really met — the map and graph components render at whatever width their container gives them via `viewBox` scaling, which keeps them from breaking, but nothing about their information density or interaction model changes on a phone-sized screen. A dense ranked-locations list with a 56px probability ring per row is not tablet/mobile-appropriate information density.

None of the above are reasons to throw away the current implementation. They're the actual, specific punch list an F1 hardening pass should work through.

---

## 3. Design Philosophy

The existing implementation's philosophy is sound and is worth stating explicitly so F1 preserves it rather than accidentally overwriting it with something blander:

- **One signal accent, reserved.** Cyan (`--accent`) means *live / system-generated / intelligence-derived*. It is never reused for anything else — not for a generic "primary button," not for navigation state, not decoratively. This is the single choice most responsible for the app not looking like a generic SaaS dashboard with a blue accent slapped on it.
- **A second, deliberately different accent for human authority.** Gold (`--decision`) marks anything a *person* decided or is being asked to decide — approve/reject actions, the "human decision required" label, the predicted-corridor cone on the map. This directly encodes the brief's "the system recommends, the investigator decides" principle *in color*, not just in copy.
- **Risk severity is its own palette, never borrowed.** Low/medium/high/critical (green → amber → orange → red) never overlaps with the accent or decision colors. A risk-critical pill and a "live" pill are never the same hue, so severity and freshness are never visually confused.
- **Density over whitespace, legibility over minimalism.** This is an investigator's tool, not a marketing page. Panels are compact, numeric columns are monospaced and right-aligned via `tabular-nums`, and information is not spread out to look bigger than it is.
- **No fabrication, ever, expressed visually.** Every place the backend has a real gap (no jurisdiction names, no team roster, no historical per-deployment outcome lookup), the UI says so in plain language rather than inventing a plausible-looking value. This is a genuine product-quality signal for a system whose entire pitch is trustworthy, auditable intelligence — a fabricated-looking "0 teams available" placeholder would undercut that pitch. F1 must keep this discipline; it is easy to erode by accident when someone reaches for a placeholder value "just for the demo."

What F1 should **add**, not replace: an animation and cross-panel-interaction layer on top of this — see §12 and §11.

---

## 4. TRACE-X Visual Language

### 4.1 Primary visual character

A dark, single-theme, government/security "command deck" — closer to a SOC (security operations center) console or a Bloomberg-terminal-adjacent tool than a consumer dashboard. Deliberately not warm, not playful, not gradient-hero-driven. The product should look like it takes the subject matter (financial crime against real victims) seriously without being somber — precision, not decoration.

### 4.2 Background hierarchy

Four flat, slightly blue-teal-biased near-blacks, each one step lighter, used strictly by role — never interchangeably:

| Token | Value | Role |
|---|---|---|
| `--bg-0` | `#0a0d12` | page background |
| `--bg-1` | `#0e1218` | primary panels, nav, topbar |
| `--bg-2` | `#131922` | nested/secondary surfaces (cards inside panels, inputs) |
| `--bg-3` | `#1a212c` | tertiary surfaces (pills, skeleton base, hover states) |
| `--bg-raised` | `#1c2430` | defined but currently unused — reserved for a future elevated-surface tier (modals, popovers) |

### 4.3 Text hierarchy

Four steps, `--text-0` (near-white, headings/values) down to `--text-3` (labels, disabled, timestamps). No pure white, no pure black anywhere — deliberate, avoids the harsh-contrast look common to hastily-built dark themes.

### 4.4 Typography

- **IBM Plex Sans** for everything conversational (labels, body, headings).
- **IBM Plex Mono** for everything that is data: IDs, hashes, coordinates, amounts, timestamps, model versions. This single decision does a lot of the "feels like an investigative/forensic tool" work — numbers and identifiers visually read as *evidence*, not as UI chrome.
- Loaded via Google Fonts `<link>` in `index.html`; no self-hosted fallback currently, which is a real risk in an offline/airgapped demo environment (see §19).
- Type scale is currently informal (`h1` 1.5rem, `h2` 1.15rem, `h3` 0.95rem, body 14px) — functional but not documented as a scale with defined steps. F1 should formalize this (§5).

### 4.5 Accent strategy

Two accents, never conflated (see §3). No third accent. No gradient accents anywhere except the small brand mark and the risk-scale legend gradient swatch — gradients are used exactly twice in the entire app, both deliberately, not as a stylistic tic.

### 4.6 Risk/severity language

A continuous, not discretely-bucketed, color ramp for the risk map (`riskColor()` in `RiskMap.tsx` interpolates smoothly between four stops), so the field looks like a real physical quantity rather than four flat zones. Discrete pills (`RiskPill`) exist for places a single number needs a label (low/medium/high/critical), computed via fixed thresholds (`riskLevelFromScore`: <0.25 low, <0.5 medium, <0.75 high, else critical) — **these thresholds are currently invented UI convenience, not derived from any backend-defined severity taxonomy**, and should be flagged to whoever owns the ML side before F2 treats them as meaningful.

### 4.7 Success/warning/error

`--ok` (green, shared with `--risk-low`), `--warn` (amber, shared with `--risk-medium`), `--danger` (red, shared with `--risk-critical`). Sharing values between the risk scale and generic status semantics is intentional (one fewer palette to keep consistent) but means a "critical risk" pill and a "this action failed" error message are literally the same red — acceptable today because they never appear adjacent in a way that would confuse the two, but worth a second look once notifications (see §2.5) are built.

### 4.8 Borders, shadows, glow

Three border strengths (`--border-subtle` → `--border-strong`), used to express nesting depth without adding shadow. Two shadow tokens only: a subtle panel shadow and a stronger "pop" shadow (currently unused — reserved for the modal/drawer layer F1 should add). **No glow effects exist anywhere** — this was an explicit anti-pattern in the original brief ("do not make everything glow") and the implementation holds that line. The one deliberate exception is the hotspot pulse on the risk map, which uses a radial gradient, not a box-shadow glow, and is scoped to exactly the top-3 hottest cells.

### 4.9 Corner radius philosophy

Three steps only — `--radius-sm` (5px, controls/buttons/pills), `--radius` (8px, cards/inputs), `--radius-lg` (14px, panels/auth cards). Nothing is fully rounded (no pill-shaped buttons except status pills themselves, which use `border-radius: 999px` deliberately to read as tags, not as buttons).

### 4.10 Density

High. Panel padding is 18px, table rows are ~40px tall, stat cards are compact. This is a considered choice for an investigator tool where more visible information beats generous whitespace — but see §2.11 for where this doesn't yet adapt down for small screens.

### 4.11 Iconography

`lucide-react` exclusively, 14–28px, always paired with a text label except in the icon-only nav-toggle and sign-out buttons (both of which have `aria-label`). No custom icon set, no icon font. This is a defensible, unglamorous choice — consistent stroke width, tree-shakeable, and it avoids the temptation to over-design iconography for a tool whose credibility should come from data quality, not from cute icons.

### 4.12 Chart language

Every chart in the app is bespoke SVG, hand-rolled specifically for one investigative quantity (§10 has the full inventory) — deliberately not a general-purpose charting library's default visual language. This was the right call for a distinctive product and should not be walked back in F1 by reaching for a chart library "to save time."

### 4.13 Map language

No basemap, no tiles, no third-party map API key. The risk map is the real H3 hexagons, computed from the real `h3_cell` strings the backend returns, projected with a hand-written equirectangular projector fit to the actual data's bounding box (with a longitude-compression correction for latitude, so hexagons aren't visibly stretched). This is honest (never implies street-level geographic precision it doesn't have) and dependency-free (no API key to manage, no risk of a demo failing because a map tile provider is unreachable). The tradeoff — discussed honestly in §19 — is that it gives no geographic *context* (no city outline, no street names, no coastline) for a viewer unfamiliar with the area, which the original visual reference (a real map-tile-based command center) implicitly has.

### 4.14 Graph language

`d3-force` for physics (charge, link, collide, center), settled synchronously for ~320 ticks rather than animated into place, then rendered as plain SVG circles/lines/text — no graph library's default node/edge chrome. Real edges (Neo4j-verified transfer hops) are solid; inferred ring-cohesion connections are dashed and explicitly labeled as inferred in an adjacent panel. This real/inferred visual distinction is one of the most important honesty features in the whole app and should be treated as non-negotiable in any future rework.

---

## 5. Design Tokens / System (formalized)

This is the first time these values have been written down as a specification rather than left implicit in `styles/index.css`. F1's actual "foundation" deliverable, in the concrete sense the brief asks for, is this table becoming the source of truth that the stylesheet is checked against — not a rewrite of the stylesheet.

**Color**
```
--bg-0 #0a0d12   --bg-1 #0e1218   --bg-2 #131922   --bg-3 #1a212c   --bg-raised #1c2430
--border-subtle #232c38   --border #2b3644   --border-strong #3a4756
--text-0 #eef2f7   --text-1 #c3ccd8   --text-2 #8b96a5   --text-3 #5c6675
--accent #22d3ee   --accent-dim #22d3ee33   --accent-strong #67e8f9
--decision #f5c451   --decision-dim #f5c45126
--risk-low #34d399   --risk-medium #fbbf24   --risk-high #fb923c   --risk-critical #f4574f
--ok #34d399   --warn #fbbf24   --danger #f4574f
```

**Type**
```
--font-sans "IBM Plex Sans"     — labels, body, headings
--font-mono "IBM Plex Mono"     — IDs, amounts, coordinates, hashes, timestamps
Scale (informal today, to formalize): 0.65rem caption / 0.7–0.75rem meta / 0.8–0.85rem body /
  0.95rem h3 / 1.15rem h2 / 1.5rem h1 / 1.6rem stat value
```

**Space & shape**
```
--radius-sm 5px   --radius 8px   --radius-lg 14px
--shadow-panel (subtle, used)   --shadow-pop (strong, currently unused — reserve for modals)
Layout: --nav-w 232px, --nav-w-collapsed 68px (defined, not yet used — see §7),
  --header-h 60px, --case-tabs-h 52px
```

**Breakpoints:** 1180px (2-column collapse), 860px (off-canvas nav, single column).

**What's missing from the token set today and should be added in F1:**
- Elevation tiers beyond the two shadow values (needed once modals/drawers exist).
- A motion token set (durations, easings) — right now every transition hardcodes its own timing (`0.12s ease`, `0.4s ease`, `0.6s ease`, `2s ease-out`, `1.4s ease`) with no shared scale.
- A formal type scale as named tokens (`--text-xs` … `--text-2xl`) instead of literal `rem` values scattered through the stylesheet.
- A z-index scale (currently only one explicit value, `z-index: 30` on the topbar, and `100`/`90` on the mobile nav/scrim — undocumented, ad hoc).

---

## 6. Global Application Shell

**Current implementation:** `AppShell.tsx` renders a two-column grid — a sticky, always-present `GlobalNav` sidebar and a main column with a sticky topbar (breadcrumb slot + live-connection indicator) and a content area. `CaseWorkspace.tsx` layers a case header (incident reference, status pill, active-prediction pill, key facts) and a tab bar on top of that for the 6 case-scoped pages, using negative margins to visually merge with the shell rather than nesting another bordered box.

**What exists:**
- Sidebar navigation (not top-nav) — appropriate for a dense, many-destination tool.
- A live connection status pill in the topbar, driven by a single real WebSocket connection.
- A minimal breadcrumb (`Cases / TX-XXXXXXXX`) inside the case workspace only; no breadcrumb on the 4 top-level pages.
- Role/jurisdiction shown in a small session card at the bottom of the sidebar.
- Mobile: sidebar becomes an off-canvas drawer with a scrim, toggled from the topbar.

**What's missing, per the brief's own checklist:**
- **Global search** — does not exist in any form. There is no way to jump to a case by incident reference or ID from anywhere except the Cases list's own filter box.
- **Notifications** — no notification center, no toast, no unread-count badge. Live events are only visible on pages that happen to render a live-feed panel.
- **Investigation context beyond the current case** — no "recently viewed cases" list, no way to have two cases open in a meaningful sense (only one "last case" is tracked — see §16).
- **Deeper breadcrumbs** — a case's sub-tab (e.g. "Network") isn't reflected in the breadcrumb at all today; it's only visible via the active tab underline.

**Recommendation for F1:** formalize the shell's contract (topbar slots, sidebar sections, content padding rules) as the actual deliverable, and add global search + a notification surface as the two genuinely-missing shell primitives — both are foundational (everything else depends on them existing once) and neither requires touching the backend (search operates over already-fetched complaint data or a `GET /v1/complaints` query; notifications consume the existing WS event stream that's already flowing through `LiveEventsContext`).

---

## 7. Navigation Architecture

**As of this report**, after the mid-session fix: two-tier —

1. **Global tier** (always visible): Mission Control, Cases, Risk Intelligence, Audit Trail.
2. **Case Workspace tier** (always visible, contextual): Overview, Network, Rings & Corridors, Prediction, Intervention, Action & Audit — disabled with an explanatory hint until a case has been opened this session, then live-linked to whichever case was most recently opened, persisted in `localStorage` via `LastCaseContext`.

This satisfies the letter of "the pages must feel like one investigation" better than the original 4-link sidebar did, but it has a real limitation worth stating plainly: **it tracks exactly one "last case," not a real case-switcher.** If an investigator has two cases they're actively comparing, opening the second silently retargets every Case Workspace nav link away from the first — there is no dropdown, no pinning, no "recent cases" list. A proper case switcher (a dropdown in the sidebar or topbar, backed by a small MRU list instead of a single value) is the correct F1-scope fix and is a small, well-contained addition on top of what exists.

**Also worth noting:** the case's own in-page tab bar (`CaseWorkspace.tsx`'s `<nav className="case-tabs">`) and the sidebar's "Case Workspace" section now render **the same six destinations twice, simultaneously**, whenever a case page is open (once as tabs at the top of content, once in the sidebar). That's not wrong, but it is redundant, and a design pass should decide whether the sidebar's case section should collapse or de-emphasize itself while already inside that case's own tabbed view, versus staying as a fixed global reference point.

---

## 8. Routing Strategy

Current structure (`App.tsx`):

```
/                      → redirect to /report
/report                → public complaint intake (unauthenticated)
/login
/mission-control       ┐
/cases                 │ global, auth-gated
/risk-intelligence     │
/audit                 ┘
/cases/:complaintId              → CaseWorkspace (nested)
  ├── (index)          → Overview
  ├── network
  ├── rings
  ├── prediction
  ├── intervention
  └── audit
```

This is a sound, conventional structure and does not need replacing. Two real gaps:

1. **No drill-down deep-linking.** Selecting a specific ring, a specific ranked exit location, or a specific audit event does not change the URL. This means nothing is shareable/bookmarkable ("look at *this* ring in *this* case"), and a browser back/forward doesn't step through selection state — only page navigation. This directly blocks the cross-panel "investigation focus" concept from §2.4/§11: if selection state doesn't live in the URL (or at least in a shared context), it can't survive a page navigation, which is exactly the case today.
2. **No route-level code splitting** (see §2.6) — every route currently imports eagerly into the one bundle.

**Recommendation:** adopt query params for drill-down state (`?ring=<id>`, `?exitChannel=<id>`, `?event=<id>`) on the relevant case pages, and lazy-load each top-level route component. Neither requires new backend surface — both are purely a frontend-routing decision.

---

## 9. Backend → Frontend Capability Map

This is the authoritative mapping already implemented; F1 should treat it as the contract to preserve, not redesign.

| Backend capability | Real endpoint(s) | Frontend surface today |
|---|---|---|
| 2A Ingestion / Graph Builder | (internal; no direct UI-facing read endpoint beyond its effects) | Reflected indirectly via `graph.updated`/`transaction.ingested` audit events and the live feed |
| 2B Ring Detection | `GET /v1/complaints/{id}/rings` | Network Investigation graph, Rings & Corridors ring cards |
| 2C Corridor / Exit-Vector Prediction | `GET /v1/complaints/{id}/prediction` (`exit_vector`) | Rings & Corridors bearing compass + distance/cone stats |
| 2D Exit-Channel + Time-Window Scoring | `prediction.ranked_locations` | Prediction + Explanation ranked-location list, probability rings, time-window bars |
| 2E Dynamic Risk Field Fusion | `GET /v1/jurisdictions/{id}/risk-field?at=` | Risk Heatmap (live + historical replay), Mission Control map, Rings & Corridors corridor overlay |
| 2F Explainability | `GET /v1/complaints/{id}/explanation` | Prediction + Explanation (top_factors, plain_language, graph_path, comparable_cases), Network Investigation's real transfer path |
| 2G Intervention Optimization | `POST /v1/complaints/{id}/optimize-deployment` | Intervention + Approval generation form (mode-aware: team locations vs. request-slot count) |
| Case & Approval | `assign` / `close` / `POST /v1/deployments/{id}/decision` | Case Overview actions, Intervention + Approval decision form |
| Action & Alerting | (no direct read endpoint — observed only via `action.dispatched` WS event) | Action & Outcome & Audit's live feed |
| Outcome / Feedback | `POST /v1/deployments/{id}/outcome` | Action & Outcome & Audit outcome form, with an honest fallback message when the API's lack of a per-deployment outcome-history read is hit (409) |
| Audit | `GET /v1/audit/events`, `GET /v1/audit/verify-chain` | Case Overview timeline, Action & Outcome & Audit trail, global Audit Trail (auditor/admin) |
| Model registry | `GET /v1/models` | Global Audit Trail |

**Known, confirmed backend gaps the frontend already works around honestly** (not something F1 should try to "fix" by inventing endpoints):
- No `GET /v1/users` → "assign to me" uses client-side JWT decode of the investigator's own `sub`, not a picker.
- No `GET /v1/complaints/{id}/graph` → the network graph is built from `rings` + the explanation's verified path, with inferred edges explicitly labeled as such.
- No `GET /v1/jurisdictions` list / no jurisdiction name field anywhere → jurisdiction options for auditor/admin are derived from jurisdiction_ids seen in already-loaded complaint data, shown as truncated UUIDs, never a hardcoded name table.
- `AuditEventResponse` doesn't expose `payload` and `deployment_history` doesn't carry outcome status → there is no way to know, after the fact, whether an approved deployment already has a recorded outcome, except by attempting to record one and reading a 409. The UI surfaces this honestly rather than guessing.

---

## 10. Visualization Strategy

Every visualization currently in the app, what it answers, and where it lives:

| Visualization | Answers | Lives in | Why visual > text |
|---|---|---|---|
| `RiskMap` (H3 hex field) | "Where is risk concentrated right now, and how has it moved?" | Mission Control, Risk Heatmap, Rings & Corridors | A table of 20+ hex scores is unreadable as a spatial pattern; a color field makes concentration and gradient immediately legible |
| `NetworkGraph` (d3-force) | "How is this victim's money connected to a ring, and which hop is real vs. inferred?" | Network Investigation | A list of account IDs conveys none of the topology (fan-out, shared intermediaries) that makes a ring suspicious |
| `BearingCompass` | "Which direction, and how confident, is the predicted exit corridor?" | Rings & Corridors | A bearing in degrees and a cone angle in degrees are two numbers a reader can't intuitively combine into "which way, how sure" without a compass rendering |
| `ProbabilityRing` | "How likely is this specific candidate exit?" | Prediction + Explanation (one per ranked location) | A percentage in a table column doesn't carry the same at-a-glance weight as a filled ring next to it |
| `TimeWindowBar` | "In what window, relative to a plausible 3-hour horizon, is cash-out expected?" | Prediction + Explanation | Two numbers (20–50 min) don't communicate scale without a reference bar |
| `ConfidenceBar` | "How much does this factor push risk up or down, and by how much relative to the others?" | Prediction + Explanation (SHAP-style factors) | Directly visualizes the magnitude comparison a reader would otherwise have to do mentally across several rows |
| `CoverageBar` | "Did the optimizer actually beat the naive baseline, and by how much?" | Intervention + Approval | The entire point of showing an optimizer is to prove it's better than not optimizing — a side-by-side bar makes that comparison immediate |
| `Sparkline` | "Is filing volume trending up?" | Mission Control | A 14-number list is not a trend; a sparkline is |
| `Timeline` | "What happened to this case, in order, and was any of it a human decision vs. a system event?" | Case Overview, Action & Outcome & Audit, global Audit Trail | Distinguishes tone (system/decision/critical) via a colored rail dot — sequence and actor-type both read at a glance |

**What's notably absent** relative to the original brief's own visualization list:
- **A transaction timeline** (chronological, per-account or per-ring transaction sequence) does not exist as its own component. Transaction-level detail is only implied through ring aggregate stats (`transaction_count`, `total_amount`, `burst_ratio`) — there's no visual of individual transactions in sequence.
- **No cross-visualization interaction** (§2.4, §11) — selecting a node in the network graph does not highlight anything on the risk map or in the prediction panel, even though they're describing the same case.

---

## 11. Interaction Strategy

**What's implemented today:**
- `NetworkGraph`: click a node to highlight its direct connections and dim everything else; a details panel below shows ring membership for the selected node. Selection state is local to the component (lost on navigation).
- `RiskMap`: click a hex cell to pin its tooltip and highlight it distinctly; a synced "Hotspots" list on the Risk Heatmap page lets clicking a list row select the same cell on the map. This is the one place today where two panels genuinely stay in sync via shared state — it should be the model for the rest.
- `PredictionExplanation`: clicking a ranked location re-fetches and displays the explanation *for that specific candidate* (a real backend-supported drill-down, not a client-side filter) — a good example of interaction backed by a real API capability rather than decoration.
- Approve/reject and outcome-recording require a justification/notes field before the action buttons are enabled — encodes "a human decision requires a reason" directly into the interaction, not just into a backend validation error.

**What's missing**, stated plainly because the original brief describes this exact behavior as a goal and it isn't there yet: selecting a ring, an account, or a predicted exit **does not** propagate to any other panel or page. There is no shared "what is currently under investigation" state above the level of "which case is open." Building that (a small `InvestigationFocusContext` — selected ring id, selected exit-channel id, selected account id — read by the map, the graph, and the prediction panel wherever they're all mounted, and reflected into the URL per §8) is, in this report's judgment, **the single highest-value piece of interaction work for F1** to scope, because it's the concrete mechanism behind the brief's repeated claim that this should feel like "one investigation."

---

## 12. Animation Strategy

**Today:** a pulsing live-status dot, a pulsing glow on the top-3 hottest map cells, a spinning loading icon, and CSS `transition` on hovers/focus. That's it. `framer-motion` is installed and unused (§2.2).

**Proposed for F1** (scoped to be "restrained but impressive," per the brief, not decorative):

1. **Reveal-on-arrival, not reveal-on-mount.** When a prediction, explanation, or ring genuinely appears for the first time (either from a fresh fetch or a live WS event), it should animate in distinctly from "the page just re-rendered." Today these are indistinguishable — a re-render and a genuinely new piece of intelligence look identical.
2. **Cross-panel highlight animation**, contingent on §11's shared focus state existing: when a ring is selected, the graph's camera/emphasis and the map's corridor highlight should transition together, not just toggle instantly. This is where `framer-motion`'s `layout` animations or a shared-element transition would earn their place — right now they'd have nothing to animate between, because there's no shared state to animate.
3. **Live-event entry animation** on whatever notification surface gets built (§6) — a new event should visibly arrive, not silently appear in a list on next render.
4. **Page-level transition** between the 6 case tabs — currently an instant swap. A short, consistent cross-fade (150–200ms) would reinforce "you're still in the same case" far more cheaply than any of the above.
5. A defined **motion token set** (durations: 120ms micro-interaction / 250ms panel transition / 600ms data reveal; one shared easing curve) so animations feel like one system instead of each component inventing its own timing, which is the current state (§5).

**What NOT to build:** anything resembling a loading "hero" animation, particle effects, or 3D transforms — consistent with the brief's own explicit anti-pattern list, and consistent with this app's existing restraint.

---

## 13. Responsive Strategy

**Today:** two breakpoints, sidebar becomes off-canvas below 860px, grids collapse from 3–4 columns to 2 then 1. Maps and the network graph use `viewBox`-relative SVG so they never overflow, but their information density doesn't change with viewport.

**What F1 should define, concretely, per device class** (not currently specified anywhere):

- **Desktop (≥1280px):** full 3-panel density as today — sidebar + content + secondary panel (the `split` grid pattern already used on several pages).
- **Laptop (1024–1280px):** the existing 1180px collapse point is close to right but should be re-measured against the actual `split` grid's 380px fixed secondary-panel width, which can crowd content between ~1180–1280px today.
- **Tablet (768–1024px):** currently falls into the same single-column treatment as mobile. This is the biggest concrete gap — a tablet has room for two columns and should not be forced into the same layout as a phone. The map and graph in particular should keep a 2-column companion panel at tablet width rather than stacking.
- **Mobile (<768px):** off-canvas nav is right. What's missing is a *deliberate* mobile information hierarchy — e.g., the Prediction page's ranked-location rows (56px probability ring + time-window bar + confidence text, all in one row) need a restructured, taller card layout on narrow screens rather than the same row simply wrapping.

None of this requires new components — it's almost entirely stylesheet work plus, in a few places (dense tables), a decision about which columns to hide below a given width.

---

## 14. Accessibility Strategy

**Foundation to establish in F1** (current gaps listed plainly in §2.9):

- Every custom clickable element (table rows today; graph nodes, map cells, and any future custom control) gets `role="button"`, `tabIndex={0}`, `onKeyDown` for Enter/Space, and a `:focus-visible` style — the pattern already established for the two table-row instances should become the mandatory pattern, not an ad hoc fix applied when caught.
- `aria-live="polite"` region for the live-event feed(s), so a screen-reader user is told when a new ring/prediction/outcome arrives, not just a sighted user watching the panel.
- `aria-label`s on the map's hex cells and the graph's nodes describing their value in words ("risk cell, score 2.4, critical" / "ring member account, cohesion 0.67"), not just visual color/position.
- Confirm color is never the *only* signal: risk pills already pair color with a text label (good); verify this holds for every future indicator, including anything added for §6's notification surface.
- Native `<label>`-wrapped form controls (already true throughout the existing forms) and default browser focus rings are preserved everywhere except where intentionally replaced with an equivalent custom focus style (true today, should stay true).
- Font sizes stay in relative units (already true — no `px` font sizes in the current stylesheet) so browser zoom and OS text-size settings work.

---

## 15. Component Architecture

**Current organization** (`components/ui`, `components/map`, `components/graph`) is a reasonable, shallow structure for the current scale (31 files) and should not be over-engineered into a deeper hierarchy prematurely. Two structural additions are justified by what's missing elsewhere in this report, not by abstract "best practice":

1. A `components/shell/` (or similar) home for the notification surface and global search once built (§6) — currently `layout/` mixes page-chrome components (`AppShell`, `GlobalNav`) with what would become shell-level *features*, which is fine today but would get crowded.
2. A shared `InvestigationFocusContext` (§11) alongside the existing `CaseContext`/`LiveEventsContext`/`LastCaseContext` pattern — the existing context architecture (one focused context per concern, composed in `App.tsx`) is good and this should follow the same shape, not introduce a different state-management approach.

**What F1 should explicitly NOT do:** introduce Redux, Zustand, React Query, or any general state library. The existing hand-rolled `useApi`/context pattern is appropriately sized for this app's actual complexity, and swapping it for a heavier tool would be solving a problem that doesn't exist yet, at the cost of a dependency and a learning curve neither the brief nor the current codebase needs.

---

## 16. 8-Page Relationship

Today: 4 always-visible global pages + 6 case-scoped pages reachable two ways (the case's own tab bar, and — as of this session's fix — the sidebar's "Case Workspace" section once any case has been opened). This satisfies "approximately 8 major pages" as literal page count.

It does **not** yet satisfy "feel like one investigation, not eight separate screens" in the deeper sense the brief means, for the two concrete reasons already named: no shared selection/focus state (§11) and no case-switcher beyond a single "last case" (§7). Both are well-scoped, backend-independent, frontend-only additions — this report's clearest recommendation for what F1's actual code output (once approved) should prioritize.

---

## 17. 5-Minute Demo Flow

Every step of the originally-specified flow was live-tested this session against the real backend and works today:

```
0:00 Mission Control  → real aggregates, live risk map, live activity feed
0:30 Case             → real complaint detail, real indicators, assign/close
1:00 Network          → real d3-force graph, real verified path, honest inferred-edge labeling
1:40 Ring + Corridor  → real ring cards, real bearing compass, real corridor-on-map overlay
2:20 Risk Heatmap     → real H3 field, hotspot list, historical replay control
3:00 Prediction + Explanation → real ranked locations, real SHAP-style factors, real plain-language text
3:40 Intervention     → real optimizer call (mode-aware form, fixed this session), real deployment created
4:10 Approval         → real decision endpoint, justification required, live-verified end to end
4:30 Action           → real automatic dispatch (server-side on approval), observed live via WS during testing
4:45 Outcome          → real outcome recorded, live feed updated across page navigation (verified this session)
5:00 Audit            → real 241-event chain, real cryptographic verify-chain call, real "no tampering detected" result
```

**Rough edges a live demo should be aware of, found during testing:**
- The jurisdiction risk-field computation has a visible pause on first access per jurisdiction (backend seeds its cache lazily) — a demo script should either warm this before going on stage or narrate through the pause rather than be surprised by it.
- Not every seeded complaint has a usable prediction (`ranked_locations` is `None` for some — an honest backend gap, not a frontend bug) — the demo should be scripted against a specific, pre-verified complaint (this session used `TX-2026-21AC6D38` / `aff5597b-…` for the richest full-lifecycle view, and freshly-generated deployments on other complaints for a live approve-from-scratch moment), not an arbitrary one picked live.
- An approved deployment's outcome can only be recorded once; if a rehearsal already recorded one, the live demo will hit the honest 409 fallback message instead of the success state — worth having a spare un-recorded approved deployment ready rather than reusing the same one.

---

## 18. F1 Acceptance Criteria (proposed)

Concrete and checkable, not aspirational:

1. **Design tokens exist as a reviewable spec** (this document's §5, or its successor) that the stylesheet is checked against — no new color, radius, or shadow value introduced without a token.
2. **Every one of the 8 pages is reachable from the global shell within 2 clicks**, for a session with at least one case opened, and the "no case opened yet" state explains what to do next rather than hiding the destination — the sidebar fix in §7 meets this now, formalize it as a checked requirement so it can't silently regress.
3. **A shared investigation-focus mechanism exists** (§11) and is demonstrably used by at least two of the three panels it should connect (map, graph, prediction) — not required to be complete across all 8 pages in F1, but the mechanism and at least one real cross-panel effect must exist.
4. **Zero new fabricated data.** Every new visual element traces to a real backend field or an explicitly-labeled "inferred" derivation, following the pattern already established (§9's honesty list) — reviewed against the actual API contract, not assumed.
5. **No backend changes, no invented endpoints** — verified by diffing `backend/` before and after F1, not just asserted.
6. **Responsive behavior is specified per device class** (§13) and at minimum the tablet gap identified in §13 is closed.
7. **Baseline accessibility pattern is codified** (§14) and applied to every existing custom-interactive element, not just the two fixed this session.
8. **At least route-level code-splitting** is in place (§2.6, §8) so bundle growth in F2+ doesn't silently degrade load time.
9. **A defined motion token set exists** (§5, §12) and `framer-motion` is either actually used according to §12, or removed from `package.json` — an installed-but-unused animation library is worse than no animation library, because it's a false signal to the next engineer that motion has been designed for.
10. **This report's §2 punch list has an owner and a decision (fix now / defer / accept) for each item** before F1 is considered closed — not silently dropped.

---

## 19. Risks / Tradeoffs

- **No street-context basemap** (§4.13) is an honest, dependency-free, demo-safe choice, but it is a real tradeoff against the original reference image's aesthetic, which does show a real map with geographic context. A judge unfamiliar with H3 hexagons may read the risk map as more abstract/technical than the reference intended. Mitigation is narration during the demo, not a rebuild — introducing a real map-tile provider now would trade a real risk (an unreachable tile CDN failing live on stage, or requiring an API key someone has to remember to provision) for a marginal aesthetic gain.
- **Google Fonts dependency with no self-hosted fallback** (§4.4) is a real risk specifically for an offline or restricted-network demo environment. Low cost to fix (self-host the two IBM Plex weights actually used), currently unaddressed.
- **Zero test coverage** (§2.7) is the largest structural risk in the codebase today. It was survivable this session because of extensive manual live-testing, but that doesn't scale to a team, or to a second implementation session that doesn't have this session's context.
- **The "last case" nav mechanism (§7) is a stopgap**, not a real case-switcher, and will visibly confuse anyone testing with more than one case open in their head — this should not ship to an actual demo without at minimum a "recent cases" list.
- **Client-side N+1 aggregate computation on Mission Control (§2.10)** works at current seed-data scale and will not work at any meaningfully larger scale — this is fine for F1/F2 but should be flagged to whoever eventually owns "does this survive real production data volume," because the honest answer today is no.
- **The risk-severity thresholds used for `RiskPill` (§4.6) are frontend-invented**, not backend-defined. If these numbers ever appear in front of a judge or a real investigator as if they were a calibrated model output, that would cross from "honest UI convenience" into "implied false precision" — worth a one-line disclaimer or, better, getting an actual threshold definition from whoever owns the risk-field model.

---

## 20. Recommended Implementation Order (for F2, post-approval)

Ordered by leverage (how much of the remaining work each unblocks), not by ease:

1. **Design tokens document → checked-in reference** (§5) — cheap, unblocks nothing else being reviewable against a standard.
2. **Shared investigation-focus context + URL drill-down state** (§8, §11) — the single highest-value item; almost everything else in "feel like one investigation" depends on this existing first.
3. **Case switcher / recent-cases** (§7) — small, contained, removes the "last case" stopgap's biggest rough edge.
4. **Global search + notification surface** (§6) — the two genuinely-missing shell primitives; both consume data that already exists in the app (complaint list, WS event stream) so neither is blocked on anything backend-side.
5. **Motion token set + the 4 concrete animation additions from §12**, in the order listed there (reveal-on-arrival is cheapest and highest-visibility; cross-panel highlight animation depends on #2 existing first).
6. **Accessibility pattern applied systematically** (§14) — mechanical once the pattern is codified, should be done as its own pass rather than piecemeal.
7. **Responsive tablet gap + mobile information-density pass** (§13).
8. **Code-splitting + bundle hygiene** (§2.6, §8) — do this once the page set has grown further (post §2–§7 above), not before, since splitting a still-growing route tree means redoing the split boundaries later anyway.
9. **Test coverage**, starting with the two real bugs already found this session (the intervention-mode form and the live-events-persistence architecture) as the first regression tests written, then expanding — this is listed last only because it's the biggest single effort, not because it's low priority; it should start as soon as there is engineering capacity for it, in parallel with the above, not strictly after.

---

## Final Summary

### A. What we should KEEP

- The entire existing 8-page implementation and its real backend integration — it works, end to end, against the live system, and rebuilding it from scratch would be pure regression.
- The color/type/token system as specified in §4–§5 (two disciplined accents, a real risk scale, IBM Plex Sans/Mono pairing, restrained radius/shadow/glow rules).
- The bespoke SVG chart/map/graph components (§10) — do not replace with a charting or mapping library.
- The "never fabricate" discipline (§9) applied throughout — this is a real product-quality differentiator and the hardest thing to re-establish if it erodes.
- The context-per-concern state architecture (`AuthContext`, `CaseContext`, `LiveEventsContext`, `LastCaseContext`) and the lightweight `useApi` hook — appropriately sized, no state-library needed.
- The nested-routing structure under `/cases/:id/*` paired with global top-level pages.

### B. What we should CHANGE

- The "last case" nav mechanism → a real case switcher with a recent-cases list (§7, §16).
- Zero cross-panel selection state → a shared investigation-focus context, reflected in the URL (§8, §11).
- An installed-but-unused `framer-motion` → either genuinely used per a defined motion system (§12) or removed.
- Undocumented, ad hoc design tokens → the formal spec in §5, checked against going forward.
- Client-side N+1 Mission Control aggregates → acceptable for now, flagged as not a real foundation (§2.10, §19).
- Responsive treatment that only reflows → a real per-device-class specification, closing the tablet gap specifically (§13).

### C. What we should BUILD (new, in F2, backend untouched)

- Global search over already-available complaint data.
- A notification/toast surface consuming the existing live WebSocket event stream.
- The shared investigation-focus context and its first real cross-panel wiring (map ↔ graph ↔ prediction).
- A defined motion token set and the 4 concrete animations in §12.
- Route-level code-splitting.
- A first pass of automated tests, anchored on the two real bugs this session already found.
- Self-hosted font fallback for the demo-offline risk in §19.

### D. What we should NOT build

- A new state-management library (Redux/Zustand/React Query) — the current pattern is sufficient (§15).
- A general charting or mapping library — the bespoke components are a genuine strength, not a gap (§4.12–§4.14, §10).
- A real map-tile basemap with an API key — the tradeoff analysis in §19 favors keeping the dependency-free H3 approach for a demo context.
- Any 3D interface element, particle effect, or decorative glow — consistent with the original brief's own anti-patterns and this app's existing restraint.
- A rebuild of any of the 8 existing pages from scratch — every identified gap in this report is an *addition* to, not a *replacement* of, what's there.

### E. Final Recommended Foundation

Treat F1 not as "design the foundation before building pages" — that phase has already, factually, happened and produced a working result — but as **"formalize and harden the foundation that an already-built, already-verified 8-page implementation is standing on, and close the specific, named gaps between what exists and what the original product vision actually asked for."** The two gaps that matter most, by a clear margin, are the absence of any shared cross-panel investigation state (§11) and the incompleteness of the navigation as a real multi-case tool (§7) — both are well-scoped, backend-independent, and directly address the exact language ("feel like one investigation") the original brief used to justify wanting 8 pages in the first place. Everything else in this report (animation, notifications, search, accessibility, tests, responsive tablet handling) is real, valuable, and should be scheduled — but those two are the foundation-level items an F1 approval should prioritize authorizing first.
