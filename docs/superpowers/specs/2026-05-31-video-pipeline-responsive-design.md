# Spec: Video Pipeline /new — Responsive 2-Column Layout

**Date:** 2026-05-31  
**Status:** Approved by user

---

## Problem

The `/video-pipeline/new` wizard renders as a single full-width column with no `max-width` and no mobile breakpoints. On wide desktops the form stretches uncomfortably; on narrow screens tabs/pills overflow.

## Goal

- Desktop (≥ 768px): two-column grid — inputs left, settings right.
- Mobile (< 768px): single column, same visual order as current.

---

## Layout

### Desktop (≥ 768px)

```
┌─────────────────────────────────────────────────────────┐
│  Tạo Video Pipeline                    📂 Tải template  │  ← full-width header
├─────────────────────────┬───────────────────────────────┤
│  LEFT (3fr)             │  RIGHT (2fr)                  │
│                         │                               │
│  • Nhân vật             │  • Loại pipeline              │
│  • Sản phẩm (list)      │  • Thông số video             │
│  • Bối cảnh             │  • Số video / sản phẩm        │
│  • Prompt kịch bản      │  • Nâng cao (collapsible)     │
│                         │  • Actions (lưu + bắt đầu)   │
└─────────────────────────┴───────────────────────────────┘
```

### Mobile (< 768px)

Single column. Right col stacks below left col via natural DOM order.
Order on mobile: Header → Loại pipeline → Nhân vật → Sản phẩm → Bối cảnh → Prompt → Thông số → Số video → Nâng cao → Actions.

---

## JSX Changes — PipelineNewPage.tsx

1. Wrap sections in `<div className="vp-wizard__grid">`.
2. Left child: `<div className="vp-wizard__col vp-wizard__col--left">` — Nhân vật, Sản phẩm, Bối cảnh, Prompt kịch bản.
3. Right child: `<div className="vp-wizard__col vp-wizard__col--right">` — Loại pipeline, Thông số video, Số video, Nâng cao, Actions.
4. Header + template-picker remain outside the grid (full-width).
5. Move `.vp-wizard__actions` block inside the right column (bottom).

---

## CSS Changes — styles.css

- `.vp-wizard__grid`: `display:grid; grid-template-columns:3fr 2fr; gap:24px; align-items:start`
- `.vp-wizard__col`: `display:flex; flex-direction:column; gap:20px`
- `@media (max-width:767px)`: grid becomes 1 col; actions stack vertically; save-template wraps; start-btn full-width; input tabs wrap; variant thumbnails shrink

---

## Constraints

- No changes to component logic, store, or API calls.
- Only `PipelineNewPage.tsx` and `styles.css` are modified.

---

## Testing

After implementation, run Playwright against `/app/video-pipeline/new`:
1. Viewport 1280×800: assert both columns visible (left + right).
2. Viewport 375×812 (mobile): assert single column, no horizontal overflow.
3. Existing wizard fill → start flow must still pass.
