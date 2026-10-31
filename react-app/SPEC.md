---
id: react-app-ui
type: module-design
title: React SPA — map UI, theming and component conventions
status: draft
tags: [frontend, ui, react]
---

# React SPA (`react-app/`)

## What it owns

The live web UI served at `/` — a React 18 + Vite + Leaflet single-page app
("Pheme"): a full-screen map with one avg-rating-colored marker per place, a
380 px sidebar (review list synced to map bounds, global place search,
scope toggle, user strip, place panel, review form) that becomes a draggable
bottom sheet under 768 px, plus a `/profile` page (identity card, following
list, follow form, admin panel). The Flask templates under `app/templates`
are legacy; all new UI work happens here. In dev, Vite proxies the same-origin
API (`/api/*`, `/login`, …) to the backend.

## Boundary / contracts

- Talks to the backend only through the typed helpers in `src/api.ts`
  (`/api/reviews`, `/api/me`, `/api/geocode`, …) including the CSRF
  double-submit header handling. Shapes live in `src/types.ts`.
- All map state flows through `MapPage` (reviews, scope, draft, selected
  place, focus); `MapView` is a pure renderer of that state plus Leaflet.
- Colors and radii are **CSS custom properties only** — components never
  hardcode colors. `:root` is the light theme, `:root[data-theme="dark"]` the
  dark theme; new styles must add both.

## Theming contract (decision, 2026 UI polish pass)

- Theme = `light` | `dark`, applied as `data-theme` on `<html>`.
  Initial value: `prefers-color-scheme`; an explicit toggle is persisted in
  `localStorage["pheme-theme"]` and wins; OS changes are followed while no
  override is stored. `index.html` has an inline boot script (mirroring
  `initTheme` in `src/theme.ts`) so the theme is correct before first paint —
  keep the two in sync.
- `src/theme.ts` owns theme state (`getTheme`/`setTheme`/`toggleTheme` +
  `useTheme` via `useSyncExternalStore`); `ThemeToggle` renders the
  sun/moon button (sidebar header and profile header).
- Dark map: OSM tiles are darkened with a CSS filter on
  `.leaflet-tile-pane`; popups, zoom bar and attribution are styled with the
  same variables. Marker colors (`ratingColor`) are theme-independent — they
  encode rating, not theme.

## Component conventions

- Stars are SVG (`components/Stars.tsx` for display, `StarRating.tsx` for
  input) — never text glyphs.
- Review/following rows show a hash-colored avatar (`avatarColor`); dates are
  relative (`formatRelative`) with the absolute date in `title`.
- On sidebar review cards the rating is one grouped element under the place
  name: SVG stars followed by the number (`.rating-row`, `.rating-num`) — the
  numeric chip was removed because split stars/number across the card read as
  two unrelated items. Place-panel cards show stars only; map popups show
  stars + "avg" inline. Map markers still use `ratingColor` teardrops.
- The scope toggle is a segmented control: `.scope-toggle` positions its
  `.scope-thumb` with `--active` / `--count` CSS vars set inline.
- Empty states use `.empty-state` (icon + copy); first review load shows
  shimmer skeletons (`.sk-*`) instead of a blank list.
- Markers animate in via `.marker-pin`; `prefers-reduced-motion` disables
  animations.
- Map ↔ profile navigation uses a hero shared-element transition: `App.tsx`
  wraps the view swap in `document.startViewTransition`, and the sidebar user
  chip's avatar shares `view-transition-name: hero-avatar` with the profile
  avatar, so the avatar flies between the pages (~300 ms ease-out, root
  cross-fade disabled). The username deliberately does NOT morph: the chip
  name and profile name carry *different* names (`hero-name-src` /
  `hero-name-dst`) so they never pair into a size/position morph — morphing a
  text snapshot between the two differently-sized rects doubles/balloons it —
  and instead cross-fade in place at their own size (300 ms, normal blend). Supported in all current
  evergreen browsers — Chrome/Edge 111+, Safari 18+, Firefox 144+ (Baseline
  since Oct 2025) — so only Firefox < 144 / Safari < 18 and reduced-motion
  users get the instant-swap fallback. **The state update inside the callback
  must be wrapped in `flushSync`** (React 18 batches it otherwise): Firefox
  captures the new snapshot immediately after the callback, and without a
  synchronous DOM change it captures old == new and no animation runs.

## Known limitations

- Review cards in the sidebar list are click-only (not keyboard-focusable).
- The hero transition only falls back to an instant swap in browsers without
  the View Transitions API (Firefox < 144, Safari < 18). On mobile the sheet
  peek hides the username, so only the avatar flies.
- No test suite for the SPA; verification is `npm run build` (tsc + vite).
