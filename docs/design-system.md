# LLMFlow Dashboard Design System

Governed by AGENT.md §4. Written 2026-10-13 before any dashboard code.

## Research summary and what we took from it

| Source | Principle adopted |
|---|---|
| Linear's UI redesign write-up | Few colour variables, neutral chrome, reduce visual noise in sidebar/tabs/headers, align labels/icons on a strict grid, density tested from condensed to spacious |
| Vercel Geist | Two-family type system (sans + mono), high-contrast accessible colour, hairline strokes, grid as a core aesthetic |
| Stripe/Apple (general practice) | Numbers are the hero; whitespace and hierarchy do the work, not boxes |
| Data-viz method (validated palette, mark specs) | Thin marks, hairline recessive grid, 2 px surface gaps, direct + legend labels, table view, tooltips on hover and focus |

Decisions that follow: one near-black "ink" action colour (no brand gradient), one blue for data and focus, borders not shadows, 13 px base text for a developer tool, numbers in mono, no cards-within-cards.

## Principles

1. Data first: the figure is the largest element on a screen; chrome recedes.
2. Rows, not cards: stats are an aligned strip separated by hairlines; tables are dense and scannable.
3. Honest states: every view has loading (frame kept), empty (says why, what to do), error (says what failed, retry) states. Shadow cost is always labelled "shadow".
4. Nothing decorative: no gradients, glows, glass, large radii or emoji.

## Tokens

### Colour (light / dark)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f9f9f7` | `#0d0d0d` | page |
| `--surface` | `#fcfcfb` | `#1a1a19` | panels, charts |
| `--surface-2` | `#f2f1ed` | `#222220` | hover, table header, track |
| `--border` | `#e1e0d9` | `#2c2c2a` | hairlines |
| `--border-strong` | `#c3c2b7` | `#383835` | inputs, axes |
| `--text` | `#0b0b0b` | `#ffffff` | primary |
| `--text-2` | `#52514e` | `#c3c2b7` | secondary |
| `--text-3` | `#898781` | `#898781` | muted, axis labels |
| `--accent` | `#2a78d6` | `#3987e5` | focus, links, data |
| `--ink` / `--on-ink` | `#0b0b0b` / `#fff` | `#fff` / `#0b0b0b` | primary button |
| `--good` `--warn` `--bad` | `#0ca30c` `#fab219` `#d03b3b` | same | status (always with icon + label) |

Chart ordinal ramp (tiers small → medium → large): blue steps 250 / 400 / 550 (`#86b6ef`, `#3987e5`, `#1c5cab`); validated to stay ≥2:1 against both surfaces per the ordinal rule. Categorical series (if more than tier is needed) use the validated order blue, orange, aqua.

### Type

- UI: **Geist Sans** (variable), fallback `system-ui`. Numbers in tables/axes: **Geist Mono** with tabular figures. Large stat values: proportional figures.
- Scale (px / line-height): 11/16 caption · 12/16 meta · 13/20 body (base) · 14/20 emphasis · 16/24 section title · 20/28 page title · 28/32 stat value.
- Weights 400, 500, 600 only. Sentence case everywhere; uppercase only for 11 px column headers with +0.04em tracking.

### Space, shape, motion

- 4 px base: 4, 8, 12, 16, 24, 32, 48. Page gutters 32 (≥1024), 16 (mobile).
- Radius: 4 (controls, badges), 6 (panels). Nothing larger, with one deliberate exception: the Playground message box is a pill (25 px radius) with a round 36 px send button inside it, concentric with the pill's curve, so the text area and button share one height and outline (chat convention).
- Borders 1 px; shadows only on floating layers (tooltip, menu): `0 4px 16px rgba(0,0,0,.12)`.
- Motion 120 ms ease-out for hover/focus; respects `prefers-reduced-motion`.

## Layout

- Fixed 220 px sidebar (collapses to top bar < 768 px): product mark, nav (Overview, Requests, Providers, Playground), footer with connection status, theme toggle, Settings.
- Content max-width 1200 px. Page header: title, one-line description, controls on the right.
- Filters live in one row above the content they scope (range selector).

## Components

Button (primary ink / secondary outline / ghost; 28 px high), Input, Select, Segmented control, Badge (status + tier; dot + text), StatStrip, Chart (bars with tier stack, hover tooltip, table view toggle), DataTable (sticky header, mono numerics, right-aligned numbers), Meter (quota usage; fill accent → warn → bad), EmptyState, ErrorState, Banner, Tooltip.

States: every interactive control has default, hover, focus-visible (2 px accent ring, offset 1), active, disabled.

## Accessibility

- Contrast ≥ 4.5:1 for text tokens; status colours never carry meaning alone.
- Full keyboard operation, visible focus, landmarks, `aria-live` for async results, charts have a table view and per-mark labels.
- Respect `prefers-color-scheme` with a manual override stored in `localStorage` (wrapped in try/catch).

## Icons

`lucide-react`, 16 px, 1.5 px stroke, `currentColor`; only where they add meaning (navigation, status, actions).
