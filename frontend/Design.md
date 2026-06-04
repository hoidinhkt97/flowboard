# Flowboard — Design System

> A living reference for Flowboard's visual language, structured after Google's
> Material Design documentation model: **Foundations → Components → Patterns**.
> Use this when building or reviewing UI so new work stays consistent with the
> existing product. Single source of truth for tokens lives in
> [`src/styles.css`](src/styles.css) `:root`; this document explains the
> intent, scales, and usage rules around those tokens.

---

## Table of contents

1. [Design principles](#1-design-principles)
2. [Foundations](#2-foundations)
   - [2.1 Color](#21-color)
   - [2.2 Typography](#22-typography)
   - [2.3 Spacing](#23-spacing)
   - [2.4 Shape (border radius)](#24-shape-border-radius)
   - [2.5 Elevation & shadow](#25-elevation--shadow)
   - [2.6 Layering (z-index)](#26-layering-z-index)
   - [2.7 Motion](#27-motion)
   - [2.8 Iconography](#28-iconography)
   - [2.9 Theming (light & dark)](#29-theming-light--dark)
3. [Components](#3-components)
4. [Patterns](#4-patterns)
5. [Layout & responsive](#5-layout--responsive)
6. [Accessibility](#6-accessibility)
7. [Contributing to the design system](#7-contributing-to-the-design-system)
8. [Component examples (snippets)](#8-component-examples-snippets)

---

## 1. Design principles

Flowboard is a **theme-aware, node-based canvas tool** for AI media generation.
It ships **light mode as the default** with an optional dark theme (see
[§2.9 Theming](#29-theming-light--dark)). The visual language follows four
principles:

| Principle | What it means in practice |
|-----------|---------------------------|
| **Calm, layered surface** | The canvas is the hero. Chrome recedes — muted text, low-contrast borders, and a small surface ladder that separates layers without shouting. The ladder works in both themes (white→gray in light, near-black→gray in dark). |
| **Purple = action / AI** | The accent marks anything interactive, selected, AI-driven, or "primary". Used sparingly so it always means "this matters". |
| **State is always visible** | Running, success, error, partial, and blocked states each have a dedicated color + motion treatment. The user never wonders "did it work?". |
| **Hover reveals, never clutters** | Secondary affordances (kebabs, "Use →", "★ save", overlays) are `opacity: 0` at rest and surface on hover/focus. |

---

## 2. Foundations

### 2.1 Color

All colors are defined as CSS custom properties. The token *names* are the API;
their *values* swap per theme (`color-scheme` follows the active theme — `light`
by default, `dark` when `data-theme="dark"`). **Always reference the token, never
hard-code the hex**, so a component themes itself for free. The one-off state
tints documented below are the only sanctioned literals.

#### Core tokens (`src/styles.css`)

Both themes expose the same 15 tokens. **Light is the default (`:root`)**; dark
overrides them under `:root[data-theme="dark"]`.

| Token | Light (default) | Dark | Role |
|-------|-----------------|------|------|
| `--bg` | `#eef0f3` | `#0b0c10` | App background, the canvas base. |
| `--panel` | `#ffffff` | `#14161c` | Default panel/card surface (sidebars, nodes, toolbar). |
| `--panel-high` | `#f3f4f6` | `#1c1f27` | Raised surface — inputs, hover fills, nested tiles. |
| `--panel-higher` | `#ffffff` | `#232630` | Highest surface — modals, dropdowns, popovers. |
| `--border` | `#e3e6eb` | `#22252d` | Hairline borders & dividers (1px). |
| `--text` | `#1a1c22` | `#e6e8ec` | Primary text. |
| `--muted` | `#6b7280` | `#8a8f99` | Secondary text, labels, icons, placeholders. |
| `--accent` | `#6d4aff` | `#7c5cff` | Primary / interactive / selected / AI. |
| `--success` | `#0e9f6e` | `#6ee7b7` | Success / completed. |
| `--warn` | `#b45309` | `#f5b301` | Warning / partial / attention. |
| `--error` | `#dc2626` | `#ef4444` | Error / destructive. |
| `--accent-text` | `#6d28d9` | `#c5b3ff` | Accent text/links sitting on tinted surfaces. |
| `--ok-text` | `#15803d` | `#88e0a8` | Success / connected status **text**. |
| `--warn-text` | `#b45309` | `#ffc266` | Warning status **text**. |
| `--fail-text` | `#dc2626` | `#ff8888` | Error / failed status **text**. |

> The last four are **theme-sensitive text tokens**. They exist because the
> original palette baked light tints (lavender `#c5b3ff`, mint `#88e0a8`, …)
> straight into rules — readable on dark, too pale on white. Tokenizing them
> lets light mode darken the *text* while the *tinted background* recipe stays
> shared. Dark values equal the original hexes, so dark renders unchanged.

#### Surface elevation ladder

The ladder separates layers in both themes — it just runs in opposite
directions. In **dark**, surfaces get *brighter* as they rise; in **light**,
raised surfaces go *whiter/cleaner* while the page sits on a soft gray, and the
(shared, black) shadow does the lifting. This *is* the elevation system, paired
with shadow (see §2.5):

```
Light:  --bg #eef0f3  →  --panel-high #f3f4f6  →  --panel / --panel-higher #ffffff + shadow
           canvas            hover fills              cards · modals · menus

Dark:   --bg #0b0c10  →  --panel #14161c  →  --panel-high #1c1f27  →  --panel-higher #232630
           canvas          cards/sidebars        inputs/hover            modals/menus
```

#### Accent tint scale

The accent is rarely used at full opacity for fills. Standard alpha steps over
`rgba(124, 92, 255, …)`:

Because these are alpha tints of the accent, they read correctly over **either**
theme's surface (a faint purple wash on white or on near-black).

| Alpha | Use |
|-------|-----|
| `0.04`–`0.08` | Subtle active-row / hover wash. |
| `0.12`–`0.18` | Active item background, soft chips, badges. |
| `0.28` | Focus glow ring (`box-shadow: 0 0 0 4px`). |
| `0.85`–`1.0` | Solid accent fills (primary buttons, "Use →" pill). |
| Accent text on tint | `var(--accent-text)` — deep purple `#6d28d9` (light) / lavender `#c5b3ff` (dark). |

#### Semantic state colors

State tints follow a consistent recipe: **`rgba(<hue>, 0.08–0.18)` background +
`rgba(<hue>, 0.3–0.5)` border + a theme-aware text token**. The translucent
background/border are *shared* across themes (they layer over whatever surface
is behind them); only the solid **text** color flips via the `*-text` tokens.

| State | Background (shared) | Border (shared) | Text token |
|-------|--------------------|-----------------|------------|
| Success / OK | `rgba(80, 200, 120, 0.10–0.18)` | `rgba(80, 200, 120, 0.3)` | `var(--ok-text)` |
| Running | `rgba(124, 92, 255, 0.04–0.18)` | — | `var(--accent-text)` |
| Warning / partial | `rgba(245, 158, 11, 0.08–0.10)` | `rgba(245, 158, 11, 0.35–0.45)` | `var(--warn-text)` |
| Error / fail | `rgba(239, 68, 68, 0.04–0.16)` / `rgba(255, 90, 90, …)` | `rgba(239, 68, 68, 0.5)` | `var(--fail-text)` |
| Info / upload | `rgba(64, 175, 255, 0.10)` | — | `#74c8ff` (dark) — darken for light if used as text |

#### Premium / brand gradients

Reserved for monetization & premium surfaces — do **not** use for ordinary UI.
These are **shared across themes** (saturated gradients with white text read on
both light and dark) and are not tokenized.

| Use | Gradient |
|-----|----------|
| Model badge / "Ultra" | `linear-gradient(135deg, #7c5cff, #b388ff)` |
| Update / upgrade pill | `linear-gradient(135deg, #ff6ea8, #c576ff)` |
| Sponsor CTA | `linear-gradient(90deg, #ff6ea8, #c576ff, #6ec5ff)` |
| Avatar default | `linear-gradient(135deg, rgba(124,92,255,.85), rgba(64,175,255,.85))` |
| Empty thumbnail | `linear-gradient(135deg, var(--panel-high), var(--panel-higher))` |

---

### 2.2 Typography

There is no type-scale library — sizes are applied inline per component. The
recurring **type scale** below is the de-facto system; reuse these steps rather
than inventing new sizes.

#### Font families

```css
/* Body */
font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Inter, sans-serif;
/* Mono — IDs, versions, code, durations */
font-family: ui-monospace, monospace;
```

#### Type scale

| Size | Weight | Role |
|------|--------|------|
| `9–10px` | 600–700 | Micro-labels, badge text, uppercase tags. |
| `11px` | 400–600 | Captions, hints, secondary meta, section labels. |
| `12px` | 400–500 | Default UI text — list items, buttons, inputs. |
| `13px` | 500–600 | Emphasis body — node titles, dialog body, primary buttons, chat. |
| `14–15px` | 600 | Modal titles, section headings, avatars. |

#### Conventions

- **Section labels / eyebrows**: `11px`, `font-weight: 600`,
  `text-transform: uppercase`, `letter-spacing: 0.04–0.06em`, color `--muted`.
  (See `.project-sidebar__title`, `.settings-panel__title`, `.sidebar h2`.)
- **Body line-height**: `1.4`–`1.55` for paragraphs/hints; `1.2` for tight
  single-line meta.
- **Numeric values**: add `font-variant-numeric: tabular-nums` for credits,
  counters, durations so digits don't jitter.
- **Truncation**: single-line uses `white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis`. Multi-line uses the `-webkit-line-clamp` box
  (2 lines for hints, 3 for descriptions).

---

### 2.3 Spacing

Spacing is a **4px-based scale**. Use these steps for padding, margin, and gap;
avoid arbitrary in-between values.

| Step | px | Typical use |
|------|----|-------------|
| 0.5× | `2px` | Badge inner padding, micro gaps. |
| 1× | `4px` | Icon↔label gap, grid gaps, chip gaps. |
| 1.5× | `6px` | Small control padding, tight stacks. |
| 2× | `8px` | Standard gap between related controls. |
| 2.5× | `10px` | List-row padding, medium gap. |
| 3× | `12px` | Card / panel padding (the workhorse value). |
| 3.5× | `14px` | Panel header padding. |
| 4× | `16px` | Sidebar / section padding, larger gaps. |
| 5× | `20px` | Dialog content padding. |
| 6× | `24px` | Toaster offset, large header padding. |
| 7× | `28px` | Sponsor-dialog padding (largest). |

**Rule of thumb:** card/panel interior = `12px`; dialog interior = `20px`;
gap between sibling controls = `6–8px`; gap between sections = `12–16px`.

---

### 2.4 Shape (border radius)

| Radius | Use |
|--------|-----|
| `3–4px` | Small inline controls — close buttons, tiny chips, inline inputs. |
| `6px` | **Default** — inputs, list items, small buttons, badges, tiles. |
| `7–8px` | Raised controls — icon buttons, cards, selection panels, dropdowns. |
| `10px` | Larger cards & secondary modals (provider card, activity detail). |
| `12px` | Primary modals, node cards, chat composer. |
| `16px` | Largest dialog (sponsor). |
| `18px` | Pill-height CTA buttons (radius = height/2). |
| `50%` | Circular — avatars, send button, play badge, handle dots. |
| `999px` / `9999px` | Pills — tags, status chips, "Use →", palette. |

---

### 2.5 Elevation & shadow

Elevation = **a step on the surface ladder + a larger/softer shadow** (dark =
brighter surface; light = whiter surface on a gray page). The **shadows
themselves are black `rgba(0,0,0,…)` and shared by both themes** — black shadow
is correct on light surfaces too, so only surfaces flip. Four levels:

| Level | Surface | Shadow | Example |
|-------|---------|--------|---------|
| 0 — flat | `--panel` | none / `inset 0 -1px 0 --border` | Toolbar, cards on canvas. |
| 1 — popover | `--panel-higher` | `0 4px 18px rgba(0,0,0,.5)` | Kebab menus, drop popover. |
| 2 — dropdown | `--panel-higher` | `0 8px 24px rgba(0,0,0,.4)` · `0 16px 50px rgba(0,0,0,.5)` | Activity dropdown, pickers. |
| 3 — modal | `--panel-higher` | `0 16px 48px` → `0 24px 60px rgba(0,0,0,.55)` | Dialogs. |
| 4 — hero modal | `--panel-higher` | `0 32px 80px rgba(0,0,0,.6)` + inset hairline | Sponsor dialog. |

- **Focus ring** (not elevation): `box-shadow: 0 0 0 2px rgba(124,92,255,.18)`
  on inputs, `0 0 0 4px rgba(124,92,255,.28)` on handles.
- **Selection ring**: `box-shadow: 0 0 0 2px rgba(124,92,255,.2)` or
  `outline: 2px solid rgba(124,92,255,.8)` for node cards.
- **Hover lift**: `transform: translateY(-1px)` (cards, tiles, pills) — pair
  with an `80ms` transition.

---

### 2.6 Layering (z-index)

A small, deliberate ladder. **Do not invent new z-index values** — slot new UI
into the nearest existing band.

| z-index | Layer |
|---------|-------|
| `1–2` | In-card relative content (shimmer bands, pins). |
| `10` | Canvas overlays — StatusBar, AddNodePalette. |
| `12–13` | References panel + its toggle tab. |
| `20` | In-panel popovers (toolbar actions, mention popover). |
| `30` | In-card pickers (ref-source chip picker). |
| `60` | Sidebar item context menu. |
| `100` | Toaster (top-right notifications). |
| `200` | Standard dialog backdrops (generation, result viewer, sponsor, settings). |
| `220` | Drop popover (canvas connection-drag). |
| `240` | Project create/delete modal. |
| `800` | Activity dropdown. |
| `900` | AI provider dialog. |
| `1000` | Setup modal, activity detail modal. |
| `1100` | Forced-setup gate (must block everything). |

---

### 2.7 Motion

Motion is **fast and functional** — never decorative-slow. Standard durations:

| Duration | Easing | Use |
|----------|--------|-----|
| `80ms` | `ease` / `linear` | Hover transforms, color/border changes, opacity reveals. |
| `90ms` | `ease` | Handle dot scale-up. |
| `100–120ms` | `ease` / `ease-out` | Popover entry, panel width toggle, focus transitions. |
| `180ms` | `ease` | Side-panel slide (references). |

#### Keyframes catalog

| Animation | Duration / loop | Effect |
|-----------|-----------------|--------|
| `flow-pulse` | `2s` ease-in-out ∞ | Status strip opacity 0.55↔1 on running nodes. |
| `shimmer` | `1.4s` ease-in-out ∞ | Loading sweep over processing tiles (gradient slides). |
| `skeleton-shimmer` | `1.4s` ∞ | Skeleton placeholder sweep. |
| `node-llm-shimmer` | `1.6s` ∞ | LLM-thinking band on nodes. |
| `node-llm-spin` | `0.8s` linear ∞ | Inline spinner rotation. |
| `drop-popover-in` | `120ms` ease-out | Popover pop (translateY -4px + scale 0.96 → 0). |
| `project-modal-fade` / `project-modal-pop` | `100–120ms` ease-out | Modal backdrop fade + content pop. |
| `account-update-pulse` | `2.4s` ∞ | Upgrade-pill glow pulse. |
| `ai-provider-badge-pulse` | `2.4s` ∞ | Provider-needs-setup attention ring. |
| `activity-bell-pulse` | `1.6s` ∞ | Bell scale 1↔1.08 on new activity. |
| `references-toggle-pulse` | `2.4s` ×2 | One-time attention glow on the references tab. |

**Usage rules:** continuous pulses (`∞`) signal *ongoing* state (running,
needs-attention). One-shot animations signal *entry* (popovers, modals) or a
*finite nudge* (×2 iterations). Pause attention animations on hover where the
element is interactive (`animation-play-state: paused`).

---

### 2.8 Iconography

- Icons are **emoji / unicode glyphs** rendered as text (no icon font / SVG
  library). Sized via `font-size` (`12–18px`) and colored via `color`.
- Icon-only buttons use a fixed square hit area: `22px` (compact),
  `28px`, or `32px` (toolbar), centered with flex, radius `4–8px`.
- Decorative icons get `--muted`; active/AI icons get `--accent` / `var(--accent-text)`.
- Always pair icon-only controls with `title` / `aria-label` (see §6).

---

### 2.9 Theming (light & dark)

Flowboard is **light by default** with an opt-in dark theme. Theming is pure
CSS-variable swapping — no per-component theme logic.

> **Status:** this section is the agreed design spec. The token tables in §2.1
> are authoritative; the wiring below describes how the toggle is intended to
> work once implemented (it is not yet in code).

#### How it works

- **Default = light.** The base `:root` holds the light values. Dark is an
  override block: `:root[data-theme="dark"] { … }` re-declares the same tokens
  plus `color-scheme: dark`. (Equivalently the project may keep dark in `:root`
  and add `:root[data-theme="light"]` — either way, **light is what ships as the
  default experience**.)
- **`color-scheme` follows the theme** so native controls, scrollbars, and form
  widgets match.
- **The active theme is an attribute on `<html>`**: `data-theme="light" | "dark"`.
- **Persistence:** the user's choice is stored in `localStorage` under
  `flowboard-theme`. On load, a stored value wins; otherwise default to light.
- **No flash (FOUC):** an inline `<script>` in `index.html` sets `data-theme`
  *before* the bundle loads, so the first paint is already the right theme.

#### What flips vs. what's shared

| Flips per theme | Shared across themes |
|-----------------|----------------------|
| The 15 tokens in §2.1 (surfaces, text, borders, accent, state text) | Accent **alpha tints** (`rgba(124,92,255,…)`) |
| `color-scheme` | Black **shadows** & modal **backdrops** (`rgba(0,0,0,…)`) |
| A few hardcoded text colors via light fixups (logout red, gold star text) | Premium **gradients** + their white text |

#### Theme toggle (intended pattern)

A ghost icon button in the toolbar actions; flips the attribute and persists.

```tsx
// lib/theme.ts — applies + persists; getTheme() reads localStorage → <html> attr
export function toggleTheme() {
  const next = getTheme() === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("flowboard-theme", next);
  return next;
}
```

```tsx
// ThemeToggle.tsx — sits in <div className="toolbar-actions">
<button className="toolbar-icon-btn" onClick={() => setTheme(toggleTheme())}
  aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
  title={theme === "light" ? "Dark mode" : "Light mode"}>
  {theme === "light" ? "🌙" : "☀"}
</button>
```

```html
<!-- index.html <head> — no-FOUC init, runs before the bundle -->
<script>
  (function () {
    try {
      var t = localStorage.getItem("flowboard-theme") || "light";
      document.documentElement.setAttribute("data-theme", t);
    } catch (e) {}
  })();
</script>
```

**Authoring rule:** new UI must use tokens (never raw surface/text hexes) so it
themes for free. If you must use a literal color as *text*, add a
`:root[data-theme="dark"]` (or light) fixup, or promote it to a `*-text` token.

---

## 3. Components

Components follow **BEM-ish naming**: `.block`, `.block__element`,
`.block--modifier`. Reuse the patterns below before authoring new CSS.

### Buttons

| Variant | Recipe |
|---------|--------|
| **Primary** | `background: var(--accent); color: #fff` (or `--bg` on light-on-accent), radius `6–18px`, `font-weight: 600`, hover `filter: brightness(1.08)` or `opacity: .85`. |
| **Secondary** | `background: var(--panel-high); border: 1px solid var(--border); color: var(--text)`, hover `border-color: var(--muted)` + `background: var(--panel)`. |
| **Ghost / icon** | `background: none`, `color: var(--muted)`, hover `background: var(--panel-high); color: var(--text)`. |
| **Danger** | `background: rgba(239,68,68,.08); border: 1px solid rgba(239,68,68,.5); color: #fca5a5`, hover deepens to `.16` + `#ef4444` border. |
| **Pill / CTA** | radius `999px` (or height/2), often gradient for premium. |
| **Dashed "new"** | `border: 1px dashed var(--border)`, hover `border-color: var(--accent)` — "add / create" affordances. |

Global resets: `button { cursor: pointer; border: none; background: none; color:
inherit; font: inherit; padding: 0 }` and `button:disabled { cursor: default;
opacity: 0.4 }`. Use `cursor: progress` for in-flight async buttons.

### Form controls

- **Text input / textarea**: `padding: 8px 12px`, `background: var(--panel)` (or
  `--panel-high` in modals), `border: 1px solid var(--border)`, radius `6px`,
  `outline: none`, `font-size: 12–13px`. **Focus:** `border-color: var(--accent)`
  + optional `box-shadow: 0 0 0 2px rgba(124,92,255,.18)`.
- **Textarea**: add `resize: vertical`, `min-height: 80px`. Placeholders use
  `--muted`.
- **Select**: native, with `border-left: 2px solid var(--accent)` accent edge and
  a background-SVG dropdown arrow.
- **Radio / checkbox**: `accent-color: var(--accent)`. The radio-card pattern
  wraps the input in a bordered, clickable card that gets
  `border-color: var(--accent)` + tint when active.

### Cards & surfaces

- **Node card**: `width: 240px`, `--panel` bg, `1px --border`, radius `12px`,
  padding `12px` (left `18px` to clear the status strip). Hover `translateY(-1px)`;
  selected → accent outline. `--note` variant uses `border-style: dashed`.
- **Status strip**: 3px full-height bar on the card's left edge, color = node
  state, `flow-pulse` when running.
- **Panel / section**: `--panel` bg, sections divided by `1px solid var(--border)`
  (no shadow on flat panels).

### Overlays

- **Backdrop**: `position: fixed; inset: 0`, `rgba(0,0,0, 0.5–0.72)`, flex-centered.
  Add `backdrop-filter: blur(6px)` only for premium/hero dialogs.
- **Modal**: `--panel-higher` bg, `1px --border`, radius `12px` (10px for
  secondary), modal shadow (§2.5), `max-height: calc(100vh - 64px)` with
  `overflow-y: auto`. Header = title (uppercase eyebrow) + `×` close button.
- **Dropdown / menu / popover**: `--panel-higher`, radius `6–10px`, dropdown
  shadow, entry animation, `min-width` set so it doesn't collapse.

### Badges, pills & chips

- **Tag/eyebrow pill**: radius `999px`, `font-size: 9–10px`, `font-weight: 700`,
  `text-transform: uppercase`, `letter-spacing: 0.04–0.08em`.
- **Status pill**: state-tinted bg + border + text (see §2.1 semantic recipe).
- **Model badge**: premium gradient, white text, uppercase.
- **Notification badge**: circular/`999px`, `min-width: 16px`, accent or
  `#e85a5a` (fail) bg, white `9px` bold text, absolutely positioned at `-2px`.

### Toaster

Top-right (`24px/24px`, z `100`), `--panel-higher` bg, `border-left: 2px solid`
state color, `width: 280–320px`, body padding `10px 12px`, message clamped to
2 lines, dismissible `×`.

### Media tiles

- **Thumbnail / video tile**: `aspect-ratio: 16/9`, radius `6px`, empty state =
  panel gradient + centered muted icon, filled = `object-fit: cover`.
- **Grid**: `gap: 4px`; 1 variant → `1fr`; 2–4 → `1fr 1fr`. Single tile shows
  full image at native ratio (contain, `max-height` cap).
- **Hover overlays**: "★ save" (top-left) and "Use →" (top-right) pills, both
  `opacity: 0` → revealed on `:hover` / `:focus-within`. They never collide.
- **Processing**: `shimmer` sweep via `::after`. **Blocked**: amber tint +
  warning glyph. **Error**: `--error` border.
- **Play badge**: bottom-right circle, `rgba(0,0,0,.55)` + `backdrop-filter:
  blur(4px)`.

### Node handles (React Flow)

Small visible dot (`8px` via `::after`) over a generous `20px` invisible hit
target. Hover scales the dot to `14px`, fills accent, adds a 4px glow ring.
Selected edges get accent stroke + drop-shadow.

---

## 4. Patterns

### Empty states
Dashed-border box (`1px dashed var(--border)`) on `--panel-high`, centered
muted hint text, and one or two action buttons. Keep the empty box the **same
footprint** as the filled state so the card doesn't resize on fill
(e.g. `min-height` on character/visual-asset bodies).

### Loading states
- **Indeterminate, in-place**: `shimmer` gradient sweep over the element's real
  footprint (tiles, skeletons) — preferred over spinners for media.
- **Inline action spinner**: `node-llm-spin`.
- **Page-level**: simple centered muted text ("Loading board…").

### Hover-reveal affordances
Secondary actions start at `opacity: 0` and transition to `1` on the parent's
`:hover` / `:focus-within` (kebab menus, tile overlays). This keeps the resting
UI clean. Always also reveal on `:focus-visible` for keyboard users.

### Destructive actions
Red-tinted (`danger` button recipe), placed away from frequently-used controls
(e.g. sign-out at the bottom of settings), and confirmed via modal for
irreversible operations (project delete uses `--danger` modal button).

### Selected / active item
Accent tint background (`rgba(124,92,255,.14)`) + accent text + medium weight.
Hover deepens the tint one step (`.2`).

### Attention / nudges
Looping pulse animation (glow or scale) on elements that need the user to act
(provider needs setup, available update, new activity). Use a **finite**
iteration count for one-time nudges so they don't pulse forever.

---

## 5. Layout & responsive

### App shell
```
.app { display: grid; grid-template-columns: auto 1fr; height: 100vh; width: 100vw; }
       [ project sidebar | canvas-wrap ]
```
- **Project sidebar**: `220px` expanded ↔ `44px` collapsed, `width 120ms ease`.
- **Canvas-wrap**: flex column → Toolbar (`48px`, flat) over the React Flow board.
- **References panel**: absolutely positioned right drawer, `300px`, slides via
  `translateX(100%)` ↔ `0`.
- **Chat sidebar**: currently disabled (commented out in `App.tsx`); restore by
  adding `320px` back to the grid template.

### Responsive
The app is **desktop-first** (canvas tool). The only media query is the sponsor
tier grid collapsing `repeat(4,1fr)` → `1fr 1fr` at `max-width: 760px`. Dialogs
stay fluid via `width: min(<px>, <vw>)` and `max-width: calc(100vw - 32px)`.

---

## 6. Accessibility

- **Focus visibility**: hover affordances must also respond to `:focus-visible`;
  don't remove focus outlines without an accent-colored replacement.
- **Hit targets**: icon buttons are ≥ `22px`; the React Flow handle uses a `20px`
  invisible target around an `8px` dot — apply the same "generous target, small
  visual" idea elsewhere.
- **Icon-only controls**: always provide `title` / `aria-label` (icons are
  emoji glyphs with no inherent label).
- **Color is never the only signal**: state always pairs color with an icon,
  label, or motion (running = strip color *and* pulse; error = red *and* message).
- **Contrast**: keep body text at `--text`/`--muted` (both flip per theme); on
  solid accent fills use `#fff`. For accent/state text on a tinted surface use the
  theme-aware tokens (`--accent-text`, `--ok-text`, `--warn-text`, `--fail-text`)
  — never raw `--accent` or a baked light hex, which fails contrast in light mode.
  Verify both themes hit WCAG AA (4.5:1 for body, 3:1 for large text).
- **Numeric legibility**: `font-variant-numeric: tabular-nums` for live counters.

---

## 7. Contributing to the design system

1. **Reuse tokens first.** Reach for a `--token` or a documented scale step
   before writing a literal value. New raw hex values need a reason.
2. **Match the scale.** Spacing on the 4px grid; radius/size/z-index from the
   ladders above. If you need an in-between value, reconsider.
3. **Follow BEM-ish naming.** `.block`, `.block__element`, `.block--modifier`.
4. **State recipe.** New stateful UI uses the semantic tint recipe
   (`bg .08–.18 / border .3–.5 / theme-aware text token`).
5. **Theme for free.** Use tokens for every surface/text/border so the component
   works in both themes. Don't bake a light/dark surface hex; if text needs a
   literal, promote it to a `*-text` token or add a `data-theme` fixup. Check the
   change in **both** light and dark before shipping (§2.9).
6. **Motion budget.** Transitions `80–180ms`; reserve `∞` loops for genuine
   ongoing/attention states.
7. **Update this doc** when you add a new token, scale step, z-index band, or
   reusable component pattern. Keep `:root` / `data-theme` blocks and §2.1 in sync.

---

## 8. Component examples (snippets)

Copy-paste-ready examples taken from the actual components. Each block shows a
quick **ASCII preview** of the layout, the **JSX** (real class names / a11y
attributes), and the **key CSS** to look up in `src/styles.css`. Every snippet
uses tokens, so it renders correctly in **both light (default) and dark** with no
extra work — see [§2.9 Theming](#29-theming-light--dark). (Literal `#fff` on a
solid accent fill and the danger button's pale red are the only non-token colors
here; the latter gets a light-mode fixup.)

> **About screenshots:** rendered PNGs aren't checked into the repo (they go
> stale and bloat git). To capture live screenshots run `npm run dev` and
> screenshot the component in the browser, or drop images under
> `docs/design/` and link them here. The ASCII previews below stand in as
> always-accurate, diff-friendly references.

---

### 8.1 Toolbar — `src/components/Toolbar.tsx`

```
┌──────────────────────────────────────────────────────────────┐
│ Flowboard  /  My board ▸          ⬇  🔔  ✨AI  💜 Sponsor      │  48px, flat
└──────────────────────────────────────────────────────────────┘
```

```tsx
<div className="toolbar">
  <span className="toolbar-wordmark">Flowboard</span>
  <span className="toolbar-sep" aria-hidden="true">/</span>
  {editing ? (
    <input ref={inputRef} className="toolbar-name-input" value={draft}
      onChange={(e) => setDraft(e.target.value)} onBlur={commitEdit}
      onKeyDown={onKeyDown} aria-label="Board name" />
  ) : (
    <button className="toolbar-name-btn" onClick={startEdit}
      aria-label="Rename board" title="Click to rename">
      {boardName || "Untitled"}
    </button>
  )}
  <div className="toolbar-actions">
    <DownloadAllButton /> <ActivityBell /> <AiProviderBadge /> <SponsorButton />
  </div>
</div>
```

```css
.toolbar { display: flex; align-items: center; gap: 8px; height: 48px;
  padding: 0 16px; background: var(--panel);
  box-shadow: inset 0 -1px 0 var(--border); flex-shrink: 0; z-index: 20; }
.toolbar-actions { display: flex; align-items: center; gap: 12px; margin-left: auto; }
```

**Pattern:** wordmark → separator → inline-editable title (button ↔ input swap),
actions pushed right with `margin-left: auto`.

---

### 8.2 Buttons

```
[ Primary ]   [ Secondary ]   ⨯ ghost   [ ⚠ Danger ]   ( + dashed new )
```

```tsx
{/* Primary CTA */}
<button className="gen-dialog__cta" disabled={busy}>Generate</button>

{/* Secondary */}
<button className="project-modal__btn">Cancel</button>

{/* Ghost / icon-only — always give it a label */}
<button className="toolbar-icon-btn" aria-label="Download media" title="Download">⬇</button>

{/* Danger */}
<button className="settings-panel__logout-btn">Sign out</button>

{/* Dashed "create" */}
<button className="project-sidebar__new">＋ New project</button>
```

```css
/* Primary */
.gen-dialog__cta { height: 36px; padding: 0 20px; border-radius: 18px;
  font-size: 13px; font-weight: 600; background: var(--accent); color: #fff; }
.gen-dialog__cta:hover:not(:disabled) { opacity: 0.85; }
.gen-dialog__cta:disabled { opacity: 0.35; }

/* Secondary */
.project-modal__btn { padding: 7px 16px; font-size: 12px; font-weight: 500;
  border-radius: 6px; border: 1px solid var(--border);
  background: var(--panel-high); color: var(--text);
  transition: border-color 80ms ease, background 80ms ease; }
.project-modal__btn:hover:not(:disabled) { border-color: var(--muted); background: var(--panel); }

/* Ghost / icon */
.toolbar-icon-btn { width: 32px; height: 32px; border-radius: 6px; color: var(--muted); }
.toolbar-icon-btn:hover:not(:disabled) { background: var(--panel-high); color: var(--text); }

/* Danger */
.settings-panel__logout-btn { border: 1px solid rgba(239,68,68,.5);
  background: rgba(239,68,68,.08); color: #fca5a5; border-radius: 8px; }
.settings-panel__logout-btn:hover:not(:disabled) {
  background: rgba(239,68,68,.16); border-color: #ef4444; color: #fecaca; }
```

---

### 8.3 Form field — `src/components/GenerationDialog.tsx`

```
Prompt  ✨ auto
┌────────────────────────────────────────┐
│ A wide cinematic shot of …             │  textarea, focus = accent border
│                                        │
└────────────────────────────────────────┘
```

```tsx
<div className="gen-dialog__field">
  <div className="gen-dialog__label-row">
    <label className="gen-dialog__label" htmlFor="gen-prompt">Prompt
      {autoPromptUsed && (
        <span className="gen-dialog__auto-badge" title="Auto-generated from upstream nodes">
          ✨ auto
        </span>
      )}
    </label>
  </div>
  <textarea id="gen-prompt" className="gen-dialog__textarea" value={prompt}
    onChange={(e) => setPrompt(e.target.value)} />
</div>
```

```css
.gen-dialog__textarea { width: 100%; min-height: 80px; padding: 10px 12px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text); font-size: 13px; resize: vertical; outline: none;
  transition: border-color 120ms ease; }
.gen-dialog__textarea:focus { border-color: var(--accent); }
.gen-dialog__auto-badge { margin-left: 8px; padding: 2px 6px; border-radius: 8px;
  background: rgba(124,92,255,.15); color: var(--accent); font-size: 10px; font-weight: 500; }
```

**A11y:** every input has a `<label htmlFor>`; placeholder is never the only label.

---

### 8.4 Modal / dialog — `src/components/GenerationDialog.tsx`

```
░░░░░░░░ backdrop (rgba 0,0,0,.6) ░░░░░░░░
        ┌─────────────────────────┐
        │ Generate video       ×  │  header: title + close
        │ Node #a1b2              │
        │ ───────────────────────  │
        │  …fields…               │
        │            [ Generate ] │
        └─────────────────────────┘
```

```tsx
<div className="gen-dialog-backdrop" role="presentation"
  onClick={(e) => { if (e.target === e.currentTarget) closeGenerationDialog(); }}>
  <div className="gen-dialog" role="dialog" aria-labelledby="gen-dialog-title" aria-modal="true">
    <div className="gen-dialog__header">
      <div>
        <h2 id="gen-dialog-title" className="gen-dialog__title">Generate video</h2>
        <span className="gen-dialog__subtitle">Node #{shortId}</span>
      </div>
      <button className="gen-dialog__close" onClick={closeGenerationDialog}
        aria-label="Close dialog (Escape)">×</button>
    </div>
    {/* …fields… */}
  </div>
</div>
```

```css
.gen-dialog-backdrop { position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; }
.gen-dialog { width: 640px; max-width: calc(100vw - 32px); padding: 20px;
  background: var(--panel-higher); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: 0 24px 48px rgba(0,0,0,.5); }
```

**Pattern:** backdrop closes on outside-click only (`e.target === e.currentTarget`);
`role="dialog"` + `aria-modal` + `aria-labelledby`; close button mentions the
Escape shortcut. Pick the backdrop `z-index` from the §2.6 ladder.

---

### 8.5 Toaster — `src/components/Toaster.tsx`

```
                              ┌──────────────────────────┐
                              │ !  Something went wrong ×│  top-right, auto-dismiss 5s
                              └──────────────────────────┘
```

```tsx
<div className="toaster" role="alert" aria-live="assertive">
  <div className="toaster__body">
    <span className="toaster__icon" aria-hidden="true">!</span>
    <span className="toaster__msg">{error}</span>
    <button className="toaster__close" onClick={clearError} aria-label="Dismiss error">×</button>
  </div>
</div>
```

```css
.toaster { position: fixed; top: 24px; right: 24px; z-index: 100; width: 320px;
  background: var(--panel-higher); border-left: 2px solid var(--error);
  border-radius: 8px; }
.toaster__body { display: flex; gap: 8px; padding: 10px 12px; }
.toaster__msg { font-size: 13px; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
```

**Pattern:** `role="alert"` + `aria-live="assertive"` so screen readers announce
it; auto-dismiss after 5s; coloured left-border carries the state hue.

---

### 8.6 Radio-card (provider) — `src/components/settings/ProviderCard.tsx`

```
┌────────────────────────────────┐      ┌────────────────────────────────┐
│ Claude Code                 ◯  │      │ Gemini CLI            Active ●  │  ← selected
│ Anthropic CLI · OAuth          │      │ Google CLI · OAuth             │
│ ● Connected                    │      │ ● Setup needed                 │
└────────────────────────────────┘      └────────────────────────────────┘
```

```tsx
<button type="button" aria-pressed={selected}
  className={`provider-card${selected ? " provider-card--selected" : ""}${
    kind === "warn" ? " provider-card--unconfigured" : ""}`}
  onClick={() => onSelect(provider.name)}>
  <div className="provider-card__head">
    <span className="provider-card__name">{meta.name}</span>
    <span className="provider-card__tagline">{meta.tagline}</span>
  </div>
  <div className="provider-card__foot">
    <span className={`provider-card__status provider-card__status--${kind}`}>
      <span className="provider-card__status-dot" aria-hidden="true">●</span>
      {statusLabel(provider)}
    </span>
    {current && !selected && <span className="provider-card__current-badge">Active</span>}
  </div>
  <span className={`provider-card__radio${selected ? " provider-card__radio--on" : ""}`}
    aria-hidden="true" />
</button>
```

```css
.provider-card { padding: 12px 36px 12px 12px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--panel);
  transition: background .12s, border-color .12s, box-shadow .12s; }
.provider-card:hover { background: rgba(124,92,255,.06); border-color: rgba(124,92,255,.35); }
.provider-card--selected { border-color: var(--accent);
  background: rgba(124,92,255,.12); box-shadow: 0 0 0 2px rgba(124,92,255,.2); }
```

**Pattern:** the whole card is a `<button aria-pressed>`; selection = accent
border + tint + ring; status uses the semantic OK/warn recipe (§2.1).

---

### 8.7 Status badge / pill

```
●Connected   ⟳Running   ⚠Partial   ✕Failed      ┌Ultra┐   ↑ v1.2.21
```

```tsx
{/* Semantic status pill */}
<span className="result-viewer__status-pill">Done</span>

{/* Premium model badge (gradient) */}
<span className="model-badge">Ultra</span>

{/* Notification count badge (absolutely positioned on a button) */}
<span className="activity-bell__badge">3</span>
```

```css
.result-viewer__status-pill { padding: 2px 8px; border-radius: 9999px;
  font-size: 11px; background: rgba(110,231,183,.15);
  border: 1px solid rgba(110,231,183,.3); color: var(--success); }
.model-badge { padding: 2px 7px; border-radius: 999px; font-size: 10px;
  font-weight: 600; text-transform: uppercase; letter-spacing: .04em;
  background: linear-gradient(135deg, #7c5cff, #b388ff); color: #fff; }
.activity-bell__badge { position: absolute; top: -2px; right: -2px;
  min-width: 16px; height: 16px; padding: 0 4px; border-radius: 999px;
  background: rgba(124,92,255,.95); color: #fff; font-size: 9px; font-weight: 700; }
```

---

### 8.8 Media tile (variant grid) — `src/canvas/NodeCard.tsx`

```
┌─────────┬─────────┐   ★ save (top-left)  ·  Use → (top-right)
│  img    │  img    │   both opacity:0 → reveal on hover/focus
├─────────┼─────────┤   processing = shimmer sweep
│  img    │ ▣ empty │   16:9 tiles, gap 4px
└─────────┴─────────┘
```

```tsx
<div className={`thumbnail-tile thumbnail-tile--clickable`}>
  <img className="thumbnail-tile__img" src={src} alt={alt} />
  <button className="thumbnail-tile__save-btn"
    onClick={(e) => { e.stopPropagation(); onSaveToLibrary(); }}
    aria-label="Save to references">★</button>
  <button className="thumbnail-tile__use-btn"
    onClick={(e) => { e.stopPropagation(); onUseAsRef(); }}>Use →</button>
</div>
```

```css
.thumbnail-tile { position: relative; aspect-ratio: 16 / 9; border-radius: 6px;
  border: 1px solid var(--border); overflow: hidden;
  background: linear-gradient(135deg, var(--panel-high), var(--panel-higher)); }
.thumbnail-tile--clickable:hover { border-color: var(--accent); transform: translateY(-1px); }
.thumbnail-tile__use-btn { position: absolute; top: 4px; right: 4px; opacity: 0;
  border-radius: 999px; background: rgba(124,92,255,.85); color: #fff;
  font-size: 10px; font-weight: 600; transition: opacity 100ms linear; }
.thumbnail-tile:hover .thumbnail-tile__use-btn,
.thumbnail-tile:focus-within .thumbnail-tile__use-btn { opacity: 1; }
```

**Pattern:** hover-reveal overlays at opposite corners (never collide); inner
button clicks call `stopPropagation()` so they don't trigger the tile's own
open-viewer click.

---

### 8.9 Node card + handles — `src/canvas/NodeCard.tsx`

```
 │┌────────────────────────────┐
 ●│ 🖼  Image node        a1b2 │●   ← left target handle / right source handle
 │├────────────────────────────┤      3px status strip on the far-left edge
 ││  [ thumbnail grid ]        │      pulses (flow-pulse) while running
 │└────────────────────────────┘
```

```tsx
<div className={`node-card${selected ? " node-card--selected" : ""}`}>
  <span className={`status-strip status-strip--${status}`} aria-hidden="true" />
  <Handle type="target" position={Position.Left} className="node-handle" />

  <div className="node-header">
    <span className="node-icon" aria-hidden="true">{ICON[data.type] ?? "□"}</span>
    <span className="node-title">{data.title}</span>
    <span className="node-short-id">{data.shortId}</span>
  </div>

  <div className="node-body">{/* slot per node type */}</div>

  <Handle type="source" position={Position.Right} className="node-handle" />
</div>
```

```css
.node-card { width: 240px; padding: 12px 12px 12px 18px; background: var(--panel);
  border: 1px solid var(--border); border-radius: 12px;
  transition: transform 80ms ease, box-shadow 80ms ease; }
.node-card:hover { transform: translateY(-1px); }
.node-card--selected { outline: 2px solid rgba(124,92,255,.8); outline-offset: 1px; }
.status-strip { position: absolute; left: 0; top: 0; bottom: 0; width: 3px; }
.status-strip--running { animation: flow-pulse 2s ease-in-out infinite; }
/* Handle: 8px visible dot via ::after over a 20px invisible hit target */
.node-handle { width: 20px !important; height: 20px !important;
  background: transparent !important; border: none !important; }
.node-handle::after { content: ""; position: absolute; top: 50%; left: 50%;
  width: 8px; height: 8px; margin: -4px 0 0 -4px; border-radius: 50%;
  background: var(--panel-high); border: 1.5px solid var(--muted); }
.node-handle:hover::after { width: 14px; height: 14px; margin: -7px 0 0 -7px;
  background: var(--accent); border-color: var(--accent);
  box-shadow: 0 0 0 4px rgba(124,92,255,.28); }
```

---

### 8.10 Empty state

```
┌ - - - - - - - - - - - - ┐
│   Drop an image here    │  dashed border, --panel-high fill
│   or  [ Generate ]      │  muted hint + action button
└ - - - - - - - - - - - - ┘
```

```tsx
<div className={`character-empty${over ? " character-empty--over" : ""}`}>
  <span className="character-drop__hint">Drop an image here</span>
  <button className="character-drop__generate">Generate</button>
</div>
```

```css
.character-empty { display: flex; gap: 6px; align-items: center; justify-content: center;
  min-height: 96px; border: 1px dashed var(--border); border-radius: 6px;
  background: var(--panel-high); transition: border-color 80ms linear, background-color 80ms linear; }
.character-empty--over { border-color: var(--accent); background: rgba(110,168,254,.08); }
```

**Pattern:** keep the empty footprint equal to the filled state (`min-height`) so
the card doesn't jump when media arrives; drag-over swaps border to accent.

---

*Source of truth for tokens & components: [`src/styles.css`](src/styles.css).
Component markup lives under [`src/components/`](src/components),
[`src/canvas/`](src/canvas).*
