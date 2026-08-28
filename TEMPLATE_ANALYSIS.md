# TEMPLATE_ANALYSIS.md

Analysis of the supplied template: `Template/SIH2026-IDEA-Presentation-Format.pptx`

This document is the design blueprint for the final TRACE-X deck. **Nothing in the source PPTX was modified to produce this analysis.** All figures below come from direct inspection of the unzipped OOXML (`ppt/presentation.xml`, `ppt/slideMasters/`, `ppt/slideLayouts/`, `ppt/slides/`, `ppt/theme/`).

---

## 1. Identity of the template

This is the **official Smart India Hackathon "Idea Presentation Format"** — not a generic or custom-designed deck. Evidence:

- Every slide's footer placeholder reads literally: **`@SIH Idea submission- Template`**
- `ppt/media/image1.png` is the official SIH logo (brain/circuit + lightbulb, saffron/green, "SMART INDIA HACKATHON 2022" wordmark — reused for the 2026 edition)
- Slide 7 is a **meta-instructions slide**, title "IMPORTANT INSTRUCTIONS", containing the exact submission rules (see §14)

**This is the single most important fact governing the rest of this analysis**: the template is not just a visual system, it is a *rules-bearing document*, and its own rules constrain how many slides the final deck may have.

---

## 2. Slide dimensions

- `<p:sldSz cx="12192000" cy="6858000"/>` → **13.333in × 7.5in** (widescreen 16:9)
- Notes size: 6858000 × 9144000 EMU (standard 4:3 notes page, irrelevant to on-screen design)

---

## 3. Number of slides

**7 slides exist in the file, but only 6 are real content slides.**

| # | Title (as authored) | Layout used | Role |
|---|---|---|---|
| 1 | "SMART INDIA HACKATHON 2026" / "TITLE PAGE" | Title Slide | Title / ID card |
| 2 | "IDEA TITLE" | Title and Content | Proposed Solution |
| 3 | "TECHNICAL APPROACH" | Title and Content | Technical Approach |
| 4 | "FEASIBILITY AND VIABILITY" | Title and Content | Feasibility & Viability |
| 5 | "IMPACT AND BENEFITS" | Title and Content | Impact & Benefits |
| 6 | "RESEARCH AND REFERENCES" | Title and Content | Research & References |
| 7 | "IMPORTANT INSTRUCTIONS" | Title and Content | **Meta-slide — not real content, instructs the author to delete it before upload** |

Slide 7's own body text (verbatim):

> "Kindly keep the maximum slides limit up to six (6). (Including the title slide). Try to avoid paragraphs and post your idea in points /diagrams / Infographics /pictures. Keep your explanation precise and easy to understand. Idea should be unique and novel. You can only use provided template for making the PPT without changing the idea details pointers (mentioned in previous slides). You need to save the file in PDF and upload the same on portal. No PPT, Word Doc or any other format will be supported. **Note - You can delete this slide (Important Pointers) when you upload the details of your idea on SIH portal.**"

**Governing constraint: the final TRACE-X deck must be exactly 6 slides** (Title + the 5 fixed sections above), matching the template's own mandated structure precisely.

---

## 4. Slide masters

One slide master: `ppt/slideMasters/slideMaster1.xml`. It defines generic placeholders only (title, body, date, footer, slide number) with **no custom branding, no background art, no logos at the master level**. All visual "personality" in the deck (footer band, badge, logo, decorative shapes) is drawn manually on individual slides — this template was hand-built slide-by-slide, not engineered top-down through the master.

Master text styles (inherited defaults, frequently overridden per-slide — see §7):
- Title style: TradeGothic, 44pt, centered, color = `tx1`
- Body style (lvl1): TradeGothic, 32pt, bullet `•`, left-aligned, `spcBef` 20%

Master placeholder positions:
- Title: x=609600, y=-47625, cx=10972800, cy=1143000 (full width, top)
- Body: x=609600, y=1095375, cx=10972800, cy=5030788
- Date: bottom-left, x=609600, y=6356353
- Footer: bottom-center, x=4165600, y=6356353
- Slide number: bottom-right, x=8737600, y=6356353

---

## 5. Available layouts

11 layouts exist in `ppt/slideLayouts/`, but **only 2 are actually used** by the 7 slides:

| Layout file | Name | Used by |
|---|---|---|
| slideLayout1.xml | **Title Slide** | Slide 1 only |
| slideLayout2.xml | **Title and Content** | Slides 2–7 |
| slideLayout3.xml | Section Header | *unused* |
| slideLayout4.xml | Two Content | *unused* |
| slideLayout5.xml | Comparison | *unused* |
| slideLayout6.xml | Title Only | *unused* |
| slideLayout7.xml | Blank | *unused* |
| slideLayout8.xml | Content with Caption | *unused* |
| slideLayout9.xml | Picture with Caption | *unused* |
| slideLayout10.xml | Title and Vertical Text | *unused* |
| slideLayout11.xml | Vertical Title and Text | *unused* |

Both used layouts are **stock, unmodified Office default layouts** — no theme colors, no fills, no custom placeholder positions baked in at the layout level (verified: Title/Content placeholders in slideLayout1/2 carry no `fill`, no repositioning). Every piece of visible branding (blue band, badge, logo, decorative shapes) is added as extra shapes directly on each slide, copy-pasted slide to slide with incrementing shape names (`Rectangle 8/9/9/9/9`, `Oval 9/10/11/11/8`) — i.e. manually duplicated, not layout-inherited.

**Implication for TRACE-X:** the 9 unused layouts are structurally available but carry none of the template's actual visual identity (no badge, no footer band). Using them would visually break continuity with slides 1–6's established look. Given the slide-count rule in §3, none of them are needed anyway — the deck reuses only Title Slide and Title and Content, exactly as the source already does.

---

## 6. Theme colors

`ppt/theme/theme1.xml` is the **unmodified stock "Office" theme** (the literal default new-PowerPoint palette):

| Role | Hex | Notes |
|---|---|---|
| dk1 (text) | `000000` | via sysClr windowText |
| lt1 (background) | `FFFFFF` | via sysClr window |
| dk2 | `1F497D` | navy — used for slide-1 big heading (`tx2`) |
| lt2 | `EEECE1` | cream — not used anywhere in actual slides |
| accent1 | `4F81BD` | blue |
| accent2 | `C0504D` | red |
| accent3 | `9BBB59` | green |
| accent4 | `8064A2` | purple — used as the team-badge outline color |
| accent5 | `4BACC6` | teal |
| accent6 | `F79646` | orange |

**The real recurring "brand color" of this deck is not a theme color at all** — it's a hardcoded RGB used directly on shapes:

- **`0070C0`** (a stronger blue than any theme accent) — the solid footer band on every content slide, with a drop shadow (`outerShdw`, gray 34.999% alpha)

Because the theme is factory-default, TRACE-X content should **not** try to "use the theme accent colors" as if they were meaningful brand choices — they aren't. The only colors with actual visual weight in this template are: white background, black/navy text, and the `0070C0` blue band. Any new diagram/visual generated for TRACE-X should draw its palette from `0070C0` (primary blue) plus neutral grays/black, so it reads as native to the template rather than introducing a new, unrelated palette (per PPT_RULES §1/§10 template lock).

---

## 7. Fonts & typography hierarchy

The master declares **TradeGothic** as the font for titles and body — but **every actual slide overrides this with different fonts**, so the "real" typography in use is inconsistent by design intent (this looks like a template assembled by copy-pasting text boxes with fonts set ad hoc, typical of hackathon-provided templates). Observed, as-shipped hierarchy:

| Element | Slide(s) | Font | Size | Weight | Color |
|---|---|---|---|---|---|
| Big brand heading ("SMART INDIA HACKATHON 2026") | 1 only | Garamond | 40pt | Bold | `tx2` (navy `1F497D`) |
| Title-page detail bullets (Problem Statement ID, Theme, Team, etc.) | 1 only | Arial | 24pt | Bold | `tx1` (black) |
| Subtitle placeholder ("TITLE PAGE" → replace with project name) | 1 only | Times New Roman | default (~28-32pt inherited) | Bold | `tx1` |
| Content-slide titles ("IDEA TITLE", "TECHNICAL APPROACH", etc.) | 2–7 | Times New Roman | 36pt | Bold | default black |
| Body bullets | 2–6 | Arial | 24–28pt | Regular | default black |
| Footer text | all | TradeGothic (master default) | 12pt | Regular | gray `898989` / `tx1` 75% tint |
| Slide number | all | TradeGothic (master default) | 12pt | Regular | gray `898989`, right-aligned |
| Team-name badge | 2–7 | default (minor font) | default | Regular | `dk1` (black) |

**Recommendation for TRACE-X content:** match the existing per-slide pattern rather than inventing a new hierarchy — Times New Roman 36pt bold for section titles (already established on slides 2–6), Arial 24–28pt for bullets (already established), and leave the slide-1 Garamond/Arial title-page treatment untouched since it's the fixed SIH branding block.

---

## 8. Title / subtitle / body styles in detail

**Slide 1 (Title Slide layout):**
- `ctrTitle` placeholder: fixed "SMART INDIA HACKATHON 2026" — **this is competition branding, do not alter**
- `subTitle` placeholder (idx=1): currently literal placeholder text "TITLE PAGE" — **this is where the project name/title goes**
- A free `TextBox` below (not a real placeholder) holds 6 bulleted fill-in-the-blank lines: *Problem Statement ID –, Problem Statement Title–, Theme–, PS Category– Software/Hardware, Team ID–, Team Name (Registered on portal)* — bullet char `•`, Arial 24pt bold, 200% line spacing, justified.

**Slides 2–6 (Title and Content layout), identical pattern on each:**
- `title` placeholder: section name, Times New Roman 36pt bold, positioned x=182998,y=0, full width, 1143000 EMU tall
- A free `TextBox` (not the layout's actual Content Placeholder — that placeholder exists in the layout but goes **unused** in every slide) holds the section's guidance bullets, Arial 24-28pt, bullet `•`, justified, hanging indent 342900/-342900 EMU
- Content textbox starts around y=2064921–2795263 EMU (2.26"–3.06"), i.e. there is a **1–1.5 inch gap of blank white space between the title and the bullet text** on every content slide — this gap, plus all space below the last bullet line down to the footer band, is open canvas intended for diagrams/images (matches PPT_RULES' "visual-first" instruction and slide 7's own advice to "post your idea in points/diagrams/infographics/pictures" rather than paragraphs).

---

## 9. Margins and spacing

- Standard left margin for content: **x = 609600 EMU (0.667in)**, consistent across master, title placeholders, and body textboxes
- Right margin: content width caps around cx=9385300–10972800 EMU, leaving 0.5–0.7in on the right
- Title band height: 1143000 EMU (1.25in) at the very top
- Footer reserved band: bottom **0.55in** of every content slide is visually occupied by the solid blue rectangle (see §11) — nothing should be placed there except the badge/footer/page-number placeholders, which already sit inside/above it
- No visible grid system beyond this — the template does not use a multi-column grid; each content slide is effectively one full-width text block plus open white space

---

## 10. Image placeholders

- **None are used.** The "Title and Content" layout (slideLayout2.xml) does technically include a generic `Content Placeholder` (idx=1, no type restriction — supports the standard PowerPoint 6-icon insert: table/chart/SmartArt/picture/clip/video), but **no actual slide uses it** — all 6 content slides replace it with a plain unstyled `TextBox` instead.
- The only image anywhere in the source deck is the SIH logo (`image1.png`) on slide 1, and even that is cropped (`srcRect r="59916"` — right ~60% of the image is cropped away, keeping roughly the left 40%, i.e. the brain/bulb icon rather than the full wordmark) and placed at x=6854891,y=1715881, size 3203509×3426237 EMU (≈3.5"×3.75"), overlapping the light decorative freeform shape.

**Implication:** any diagrams/visuals created for TRACE-X will be **custom-inserted images or native shapes**, not filled into a pre-built placeholder — there is no chart/diagram frame to target. They should occupy the open white space identified in §8/§9 on slides 2–6.

---

## 11. Chart / diagram areas

None exist in the source file — no native PowerPoint charts, no SmartArt, no diagram frames anywhere in the 7 slides. Any TRACE-X charts/diagrams (fraud graph, prediction flow, architecture) will need to be added fresh into the open space on the content slides, generated to match the template's minimal, flat, two-tone (`0070C0` blue / black-on-white) visual language — not as native PPT charts unless one is specifically useful (e.g. a simple bar/column for a metric), consistent with the pptx skill's "keep charts native" guidance.

---

## 12. Recurring visual elements

Two elements repeat, hand-copied, on every content slide (2–7):

1. **Bottom footer band** — a solid rectangle, fill `0070C0`, full slide width (12191999 EMU) × 503238 EMU tall (≈0.55in), positioned at y=6354762 (flush to the bottom edge), with a subtle drop shadow (`outerShdw`, gray, 35% alpha, 23000 EMU distance). Purely decorative — carries no text of its own; the footer/date/page-number placeholders sit visually in/near this band.
2. **"Your Team Name" oval badge** — an ellipse, x=329773,y=252246, size 1251857×807334 EMU (≈1.37"×0.88"), top-left corner of every content slide. Style: white fill (`lt1`), `accent4` purple outline, centered text "Your Team Name" in default black. Its `descr` attribute literally reads `"Your startup LOGO"` — meaning this shape doubles as a slot for either a team-name label or a logo image, at the author's discretion.

Slide 1 carries its own one-off decorative elements not repeated elsewhere: a large, very-light (15% alpha, gray `tx1` lumMod/lumOff) abstract freeform "seal/hex" shape behind the logo, and an invisible (`useBgFill`, i.e. same as background — effectively a no-op leftover from PowerPoint Designer) rectangle. Neither should be treated as meaningful design language to extend elsewhere.

---

## 13. Header / footer elements

- **Footer text** (all slides): "@SIH Idea submission- Template" — fixed competition branding, centered at the bottom, must not be changed
- **Slide number**: bottom-right, auto-numbered field
- **Date placeholder**: exists in the master (bottom-left) but is **not populated/visible** in any of the actual 7 slides (they don't include a date textbox) — effectively unused
- No slide has a visible header

---

## 14. Background & overall visual language

- **Background**: plain solid white (`bg1`/`lt1`) on every single slide — no textures, gradients, or imagery
- **Overall visual language**: minimal, utilitarian, government-hackathon-standard. This is explicitly *not* a richly art-directed corporate template — it is a compliance-format document with light branding (SIH logo, blue accent band, purple-outlined badge) layered on top of plain PowerPoint defaults. The template's own instructions (slide 7) explicitly favor points/diagrams over paragraphs and explicitly cap length — the format rewards restraint, not visual elaboration.
- Any new visuals created for TRACE-X (diagrams, icons, flow charts) should stay within this restrained language: white background, black text, `0070C0` blue as the single accent, flat/simple shapes, no gradients, no unrelated color palette, no cyberpunk/AI-generic imagery (also explicitly barred by PPT_RULES §8).

---

## 15. Slide-by-slide layout suitability for TRACE-X content

Because the template's own rules cap the deck at 6 slides matching its 5 fixed section names, **there is no discretion over which layout maps to which content type** — the template already assigns exactly one purpose to each slide:

| Slide | Fixed section (per template) | Natural TRACE-X mapping |
|---|---|---|
| 1 | Title / ID card | Project identity, PS ID (SIH26184), title, theme, team |
| 2 | Proposed Solution | The core pitch: problem → TRACE-X → how it works, differentiation |
| 3 | Technical Approach | Architecture, ML approach, tech stack, methodology |
| 4 | Feasibility and Viability | Risks, data constraints (synthetic data), scalability answer |
| 5 | Impact and Benefits | Who benefits, lead-time/coverage gains, responsible-AI framing |
| 6 | Research and References | NCRB/I4C references, prior-art comparison, glossary/sources |

Slide 7 (Important Instructions) is **not a content slide** — per its own text it must be deleted before the final deck is produced.

---

## 16. Summary of constraints for the next phase (PPT_BLUEPRINT.md)

1. Final deck = **exactly 6 slides**, matching the template's own mandated structure (Title + 5 fixed sections). Slide 7 is discarded entirely.
2. Only **Title Slide** and **Title and Content** layouts are used — matching what the source already does; the other 9 layouts stay unused.
3. Keep the SIH branding block on slide 1 (`SMART INDIA HACKATHON 2026`, logo, decorative shapes) exactly as-is; only fill in the subtitle and the 6 detail bullets.
4. Keep the blue `0070C0` footer band and the "Your Team Name" badge on every content slide, unchanged in position/style — badge text becomes the actual team name.
5. Keep font choices consistent with what's already established per-element (Times New Roman 36pt bold titles, Arial 24–28pt bullets) rather than introducing new fonts.
6. Use the open white space below/around the bullet text on slides 2–6 for custom TRACE-X diagrams — this space is real estate the template's own instructions (slide 7) explicitly encourage filling with points/diagrams rather than paragraphs.
7. Any new color used in generated visuals should be drawn from `0070C0` + black/white/gray — no unrelated palette.
