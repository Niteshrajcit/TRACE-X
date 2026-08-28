# TRACE-X — Design System

> Governs the visual language for the screens defined in [PRODUCT_EXPERIENCE.md](PRODUCT_EXPERIENCE.md). Not implemented this phase (no frontend is being built) — this is the specification the eventual frontend build must follow, and the specification judges/reviewers can hold the (future) UI against.

---

## 1. Visual personality

**Government intelligence platform + modern mission-control interface + serious analytical software.** Concretely, that means the reference points are an air-traffic-control display, a SOC (security operations center) dashboard, and a financial trading terminal — not a marketing SaaS admin panel, not a consumer app, and explicitly not a "hacker" aesthetic.

Three rules that follow from that and apply to every screen without exception:
1. **Every visual element earns its place by carrying information or enabling an action.** If a component can be deleted without losing information or a control, delete it. No decorative illustrations, no stock icons standing in for concepts already named in text, no filler charts.
2. **Density over whitespace-for-its-own-sake, legibility over decoration.** An investigator's screen should look like it's doing real work — closer to a Bloomberg terminal's information density than a landing page's — but every dense area must still pass a five-second scan test for its Tier-0 information (PRODUCT_EXPERIENCE.md §3.1).
3. **Calm by default, loud only when it matters.** Motion, color intensity, and glow are reserved for state changes that need attention (a new high-risk incident, a pending approval) — a screen that is visually loud all the time teaches the eye to ignore it, which is the opposite of what a risk system needs.

**Explicitly rejected**: cyberpunk neon palettes, gratuitous 3D globe/particle backgrounds, glassmorphism glow effects, decorative looping animations, gauge/donut charts used as decoration rather than to show a real ratio, drop shadows deeper than a functional elevation cue, any chart whose data isn't a named real field from API_CONTRACT.md.

---

## 2. Typography

| Role | Typeface direction | Notes |
|---|---|---|
| UI text / body | A neutral, high-legibility grotesque (e.g. Inter, IBM Plex Sans, or system-ui stack) | Optimized for dense tabular and label text at small sizes, not display impact |
| Numerals / data | Tabular (lining) figures, monospaced-numeral variant if the chosen family supports it | Probabilities, coverage percentages, and timestamps must align in columns — a wobbling decimal point undermines the "serious analytical software" read |
| Headings | Same family, weight-differentiated (600/700), not a separate display face | A second typeface family is an unforced aesthetic choice this product doesn't need |
| Monospace | A plain monospace (e.g. JetBrains Mono, IBM Plex Mono) reserved for: account hashes, hash-chain values, model version strings, H3 cell IDs | Signals "this is a literal system value, not prose" — an important honesty cue distinguishing generated evidence from computed identifiers |

Type scale: a restrained 6-step scale (e.g. 12/14/16/20/24/32px) — no more. Body copy never below 14px; dense table/label text may use 12px but never for anything a decision depends on.

## 3. Spacing & grid

8px base unit, all spacing and sizing in multiples of it. A 12-column responsive grid for the Command Center and admin screens; the Incident Workspace (PRODUCT_EXPERIENCE.md §3.2) uses a fixed three-region layout (left rail / main / right panel) with the main region internally free to lay out its active tab's content. Panel padding is consistent (16px standard, 24px for top-level page containers) — inconsistent padding is one of the fastest "generic admin template" tells, and this system deliberately avoids it.

## 4. Color system

A restrained, mostly-neutral palette with color reserved as a signal, not decoration — the opposite of a dashboard that colors everything to look lively.

**Base neutrals** (dominant on every screen): a slate/graphite scale for backgrounds, panels, borders, and body text — cool-neutral, not pure gray, not warm. Dark-surface-first is appropriate for a mission-control read (long viewing sessions, map/graph content that needs contrast to pop against), with a light theme as a genuine equal, not an afterthought — investigators may run this on a bright office monitor, not a darkened SOC room.

**One brand/interactive accent** — a single deliberate blue (this is also a continuity thread from the existing TRACE-X pitch deck's `0070C0` blue per TEMPLATE_ANALYSIS.md — reusing it here ties the product visually to the pitch material already reviewed by the team). Used for: primary buttons, active nav state, links, the "Live" connection indicator, selected map cells before risk-coloring applies.

**Severity/risk color scale** — this is the one place saturated color is earned, because risk level is the single most important piece of information on the map and headline:

| Level | Color direction | Used for |
|---|---|---|
| Minimal | Neutral slate (no color) | Below-threshold H3 cells — deliberately *not* colored, so the map isn't wall-to-wall color noise |
| Low | Muted green-yellow | Low probability cells |
| Moderate | Amber | Mid-range probability |
| High | Orange | High probability, not yet top-ranked |
| Critical | Red, reserved | Top-ranked cell(s) / the specific prediction the headline banner refers to — never used for anything else, so red always means "this is the one" |

Severity colors are consistent across the map (§5), the graph (ring cohesion, §6), and status chips — a red chip means the same thing everywhere in the product, which is a hard rule, not a guideline.

**Data-mode chips** (PRODUCT_EXPERIENCE.md §6) use their own restrained palette, deliberately *not* borrowed from the severity scale (so "simulated" is never visually confused with "high risk"): neutral slate for synthetic, amber outline (not filled) for simulated-external, muted outline for future/not-connected.

**Dark/light parity**: every token above is defined for both themes with equivalent contrast ratios — this is a WCAG requirement (§12), not a nice-to-have, given the content includes color-coded risk that a colorblind or low-vision investigator must still be able to distinguish (severity is never color-only, see §12).

## 5. Map treatment

The H3 hex risk layer is the product's signature visual and must read instantly as **data, not decoration**:
- Base map: a muted, low-contrast basemap (desaturated, minimal labels) — the hex layer is the subject, the basemap is context, never the reverse
- Hex cells below the "minimal" risk threshold are not colored at all (transparent/basemap-visible) — coloring every cell regardless of score is the single most common way a risk map becomes visual noise instead of information
- The exit-vector cone (PRODUCT_EXPERIENCE.md §7) renders as a translucent directional wedge, animated in once on arrival, then static — not a looping pulse, which would compete with the risk layer for attention
- Deployment pins (optimizer output) use a distinct shape (not a hex, not a dot already used for something else) with a numeric badge for coverage contribution
- Time slider for historical replay sits below the map, full-width, with clear "live" vs. "replaying — [timestamp]" state text, because replaying history on a "live" system is exactly the kind of thing that must never be ambiguous

## 6. Graph treatment

Force-directed layout, victim account visually anchored (larger node, brand-accent outline) so the eye always has a fixed starting point regardless of how the rest of the graph settles. Ring membership is color-coded using the same severity-adjacent logic as the map but kept visually distinct (ring colors are categorical/qualitative, not a severity gradient — a ring isn't "riskier" for being a different color, only different). Edge thickness maps to transaction amount; edge style (solid/dashed) distinguishes transaction edges from relationship edges (`SHARES_DEVICE_WITH` etc.) so the graph doesn't require a legend lookup for every edge.

## 7. Card & panel hierarchy

Three elevation levels only: **page background → panel (bordered, flat) → focused/active card (subtle elevation + accent border)**. No fourth level, no soft floating-shadow stack — elevation communicates "this is the thing you're currently acting on," not decoration. The sticky header (PRODUCT_EXPERIENCE.md §3.1) sits above all elevation levels by z-order but uses the flattest visual treatment of all (a bordered bar, not a shadowed card) — it should feel like scaffolding, not another competing panel.

## 8. Navigation

Persistent left rail (icons + labels, collapsible to icons-only), persistent top bar (role, jurisdiction, live-connection status). No breadcrumb trail beyond "Command Center → Incident #X" — the product's navigation depth is intentionally shallow (PRODUCT_EXPERIENCE.md §2's five top-level destinations), so breadcrumbs beyond two levels would indicate the IA has drifted from its own design.

## 9. Motion principles

Motion is used exactly three ways, never for delight-for-its-own-sake:
1. **State-change confirmation** — a new node/edge animating into the graph, a hex cell recoloring, a new Command Center card sliding in — always under 300ms, always a direct visualization of a real event from PRODUCT_EXPERIENCE.md §4's event table, never a generic "loading flourish"
2. **Attention direction** — a brief highlight pulse (one cycle, not looping) when a pending-approval badge newly appears, so an investigator's eye catches it without a sound/toast being required
3. **Progress indication** — the pipeline status strip (§3.1 Tier 0) fills left-to-right as real events arrive; it is driven by actual WebSocket events, so its speed reflects the real pipeline's speed, and it must never be faked to "look" faster or slower than the backend

No parallax, no hover-triggered decorative transforms, no looping ambient animation anywhere (including "just for polish" background effects) — anything that moves without a corresponding state change is a defect in this system, not a feature.

## 10. Loading, empty, and error states

| State | Treatment |
|---|---|
| **Loading** (pipeline stage in progress) | The progress strip itself *is* the loading indicator — no separate spinner competing with it. Tab content shows a skeleton shaped like the real content (a dimmed graph outline, a dimmed hex grid) rather than a generic spinner, so the investigator can see *what* is loading, not just *that* something is |
| **Empty** (no transactions yet, no active incidents) | Explicit, specific copy — "No money movement detected yet for this complaint" is correct and calm, never a generic "No data" — an empty state in this product usually means "nothing bad has happened yet," which is good news and should read that way, not as a broken screen |
| **Error** (API failure, WebSocket disconnect) | Never a silent failure. A disconnect shows the top-bar "Live" indicator flip to "Reconnecting…" immediately (PRODUCT_EXPERIENCE.md's real-time promise depends on this being trustworthy); a request failure shows the `request_id` from API_CONTRACT.md §8 so it's traceable, not just "Something went wrong" |
| **Alert/critical state** | The one place a non-looping attention animation plus the critical-red severity color both apply at once — reserved strictly for a new top-ranked prediction crossing a high-risk threshold or a pending approval, never for routine state changes |

## 11. Responsive behavior

Primary target is desktop/large-tablet (an investigator's workstation, a command-center wall display) — this is not a mobile-first product. Below a defined breakpoint, the Incident Workspace's three-region layout (PRODUCT_EXPERIENCE.md §3.2) collapses to a single-column stack in a fixed priority order (sticky header → main tab content → left rail summary collapsed into an expandable drawer → right panel collapsed into an expandable drawer), so the decision-relevant Tier-0/Tier-1 information always reaches a smaller screen first. The Citizen Complaint Portal (screen 01) is the one screen that must be fully mobile-first, since citizens will overwhelmingly use it from a phone.

## 12. Accessibility

- Severity is never color-only: every risk-level cell/chip also carries a label or icon distinguishable without color (e.g. a numeral, a pattern, or text on hover/focus) — required both for WCAG and because a colorblind investigator making a deployment call is a real operational risk, not just a compliance checkbox
- Minimum WCAG AA contrast for all text and meaningful graphical elements, in both theme modes (§4)
- All interactive elements keyboard-navigable and screen-reader-labeled, including map hex cells (exposed via an accessible data table alternative view, not just the visual layer) and graph nodes (an accessible list view of the same graph data)
- Motion (§9) respects `prefers-reduced-motion` — state changes still occur, only their animated transition is skipped
- Every icon-only control (collapsed nav, chip icons) has a text label available via tooltip/aria-label — this product's icon vocabulary (§1's provenance chips, map/graph legends) is not universally standardized and must not rely on icon recognition alone
