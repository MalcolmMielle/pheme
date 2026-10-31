# React migration — job spec

**Status: NOT STARTED.** This file is the complete handoff for converting the
Pheme web interface from Jinja2 + vanilla JS to React
(Vite + TypeScript). Everything a future session needs is in here.

**To relaunch the job:** open a new session in this repo and say:
> "Read REACT-MIGRATION.md and execute it."

Git state at time of writing: branch `fix/security-hardening` @ `beb2e64`
(same as `main`), clean tree.

---

## 1. Project context

**pheme** — a decentralized, ActivityPub-federated review platform
("Mastodon, but for location-based reviews"). Every server runs its own
instance; reviews are tied to lat/lng and federate between servers.

- **Backend (pure Python, stays as-is):** FastAPI + uvicorn, aiosqlite,
  hand-rolled ActivityPub (WebFinger, Actor, Inbox/Outbox, Followers/Following,
  HTTP Signatures RSA-SHA256), session-cookie auth (Starlette
  `SessionMiddleware` + itsdangerous), bcrypt password hashing via passlib.
- **Stack tooling:** Python ≥ 3.13, `uv`. Run server: `uv run pheme`
  (port 8000). Seed demo data: `uv run bootstrap` (actor `alice` + 8 reviews
  in San Francisco). Lint: `uv run ruff check app/`.
- **DB:** `data/reviews.db` (gitignored). Tables: `actors`, `reviews`,
  `follows`.
- **Frontend today:** Jinja2 templates that are thin shells +
  `app/static/app.js` (503 lines of hand-rolled vanilla JS driving Leaflet)
  + `app/static/style.css` (465 lines, desktop-first). It is already a
  de-facto SPA: all rendering happens client-side via `innerHTML`.
- **JS tooling today:** none. Root `package.json` is literally `{}`.

## 2. Decision (already made — do not re-litigate)

- **Convert the interface to React + Vite + TypeScript.** The backend stays
  Python/FastAPI, unchanged in architecture.
- **The React app lives in a new folder `react-app/`** (user wrote "react app";
  kebab-case chosen to avoid spaces in paths). Rationale: a future Sailfish OS
  app will get its own folder too (e.g. `sailfish-app/`), so each client app
  is self-contained. Root `package.json` stays `{}`; `react-app/` gets its own
  `package.json`.
- **Flutter was considered and rejected.** Sailfish OS was the deciding
  factor: Flutter has no official Sailfish support (upstream feature request
  flutter/flutter#152624 still open); the only option is an unofficial
  proof-of-concept runner (`mehmetfiskindal/flutter-sailfish`) whose own
  release notes say apps using its custom Sailjail permissions are "fine for
  side-loading but not suited to the Harbour store". React Native has no
  Sailfish support either. **Web tech + thin native shells is the only
  single-codebase path that reaches Sailfish cleanly.**
- **Future platform plan (separate folders/jobs, out of scope here):**
  Capacitor wrapper for Android/iOS around the same React app; `sailfish-app/`
  = thin Qt/QML shell using the official `Sailfish.WebView` component
  (`sailfishos/sailfish-components-webview`, Gecko engine) loading the deployed
  React app — a proven Harbour-accepted pattern (e.g. `harbour-smallworld`).
  JWT/token auth gets added when native apps arrive; cookie sessions are fine
  for the same-origin web app and the WebView shell.

## 3. Current state — what exists and must be ported or preserved

### Pages
| Route | Today | Notes |
|---|---|---|
| `GET /` | `index.html` shell + `app.js` | The map SPA. Biggest port. |
| `GET /review/{id}` | `review.html`, server-rendered | Standalone detail page. Keep SSR (shareable links / OG for a federated platform). |
| `GET/POST /login`, `GET/POST /register` | Jinja form pages | Simple forms. First pass may stay Jinja; React links to them. |
| `POST /logout` | clears session, 303 → `/` | Keep. |

### JSON API (exists, reusable as-is)
- `GET /api/reviews` → JSON array. Optional bounds filter:
  `?min_lat=&max_lat=&min_lng=&max_lng=`.
- Review JSON shape (from `app.js` usage): `id`, `content`, `rating` (1–5),
  `latitude`, `longitude`, `place_name`, `place_address`, `created_at`,
  `username`, `display_name`.
- `POST /api/reviews` — form fields: `content`, `rating`, `latitude`,
  `longitude`, `place_name`, `place_address`. **Requires login** (session
  cookie). Creates the review and federates it to followers.
- `POST /api/bootstrap` — form: `username`, `display_name`, `password`.
- ActivityPub routes (must never be shadowed by the SPA catch-all):
  `/.well-known/webfinger`, `/actor/{username}`, `/actor/{username}/inbox`
  (POST), `/outbox`, `/followers`, `/following`, `/inbox` (POST).

### Frontend logic to port (`app/static/app.js`, 503 lines)
- Leaflet map, OSM tiles, default center `[37.7749, -122.4194]` zoom 13.
- Markers: custom `divIcon`, teardrop shape, color by rating:
  1 `#ef4444`, 2 `#f97316`, 3 `#eab308`, 4 `#84cc16`, 5 `#22c55e`.
- `moveend` → fetch `/api/reviews` with map bounds → re-render markers +
  sidebar list.
- Sidebar: header, user strip (login/logout), global map search
  (Nominatim), review cards, FAB "＋" to add review.
- Review form panel: Nominatim place search dropdown (350 ms debounce),
  address auto-fill, star rating (1–5, default 5), textarea, hidden lat/lng,
  map click places a draggable marker, reverse-geocode fills name/address,
  submit → `POST /api/reviews` (FormData) → refresh list.
- Detail panel: slide-in with place name, address, stars, content, author,
  date.
- `escHtml` helper for XSS-safe rendering.

### Design tokens (`style.css` `:root`)
`--accent: #2563eb`, `--star: #f59e0b`, `--danger: #ef4444`,
`--sidebar-w: 380px`, `--panel-w: 400px`, `--radius: 12px`,
fonts: system stack. Mobile today is a single `@media (max-width: 768px)`
hack (sidebar → 100vw) — replace with a real phone layout (see phase 3).

## 4. Target architecture

```
pheme/
├── app/                  # Python backend (FastAPI) — minimal changes, see §6
├── react-app/            # NEW: Vite + React + TypeScript SPA
│   ├── package.json      # own deps; root package.json stays {}
│   ├── vite.config.ts    # build.target es2020; dev proxy → :8000
│   └── dist/             # build output, served by FastAPI (gitignored)
├── sailfish-app/         # FUTURE, separate job: Qt/QML WebView shell
└── REACT-MIGRATION.md    # this file
```

- **Dev:** `npm run dev` in `react-app/` (Vite, port 5173) with
  `server.proxy` forwarding `/api`, `/actor`, `/.well-known`, `/login`,
  `/register`, `/logout`, `/review`, `/static` → `http://localhost:8000`
  (backend running via `uv run pheme`). Cookie auth works through the
  proxy if `changeOrigin` + cookie domain are handled (same-origin via proxy
  is the default path of least resistance).
- **Prod/dev serve:** FastAPI mounts `react-app/dist` assets and adds an SPA
  catch-all for client-side routes — registered **after** all API,
  ActivityPub, auth, and `/static` routes so it never shadows them.

## 5. Plan (phases)

Suggest committing on a new branch, e.g. `feature/react-frontend`.

### Phase 0 — scaffold
1. `git checkout -b feature/react-frontend`
2. Scaffold `react-app/`: Vite + React + TypeScript
   (`npm create vite@latest react-app -- --template react-ts`, or hand-write
   `package.json` / `vite.config.ts` / `tsconfig.json` / `index.html`).
3. Deps: `react`, `react-dom`, `leaflet`, `react-leaflet`,
   `typescript`, `vite`, `@types/react`, `@types/react-dom`, `@types/leaflet`.
4. `vite.config.ts`: `build.target: 'es2020'` (**required** — the bundle must
   run on Sailfish's Gecko WebView later), dev `server.proxy` as above.
5. `.gitignore`: add `react-app/node_modules/` and `react-app/dist/`.

### Phase 1 — port the map page (the whole app, really)
Component tree (port from `app.js`):
- `App` — routing (react-router or a tiny hand-rolled switch; only `/` is
  client-side, everything else stays server-rendered initially).
- `MapPage` — layout: map + sidebar (desktop) / bottom sheet (phone) + FAB +
  panels.
- `MapView` — react-leaflet: OSM tile layer, marker layer (colored divIcons),
  popups, `moveend` → bounds-filtered reload, click-to-place when the form
  is open, draggable placement marker. Import `leaflet/dist/leaflet.css`.
  Custom divIcons mean no default marker-image asset problem.
- `ReviewList` — sidebar cards / phone bottom sheet.
- `ReviewDetail` — slide-up/slide-in panel.
- `ReviewForm` — Nominatim search dropdown, star rating, textarea, hidden
  lat/lng, submit → `POST /api/reviews`.
- `SearchBox` — global map search (Nominatim).
- Keep the 350 ms debounce on Nominatim (usage policy).

### Phase 2 — auth
1. Add `GET /api/me` (see §6) so the React app knows the current user.
2. First pass: keep `/login`, `/register` as the existing Jinja pages; the
   React app just links to them and shows user state from `/api/me`.
   Logout = link/form POST to `/logout`, then refetch `/api/me`.
3. Handle unauthenticated `POST /api/reviews` gracefully (see §6 gotcha) —
   redirect the user to `/login` from the client.

### Phase 3 — mobile-first redesign (the actual point of this migration)
Replace the `@media` hack with a real phone layout:
- Full-screen map; review list as a **bottom sheet** (peek height + expanded).
- Review detail as a slide-up panel; review form as a full-screen sheet.
- FAB for "add review"; `100dvh` (not `100vh`); ≥ 44 px touch targets.
- Desktop keeps the 380 px sidebar + 400 px panels look.

### Phase 4 — FastAPI serves the SPA
1. Mount `react-app/dist` (StaticFiles, `html=True` or explicit asset mount).
2. Add SPA catch-all (`/{full_path:path}` → `index.html`) **last**, after all
   API/ActivityPub/auth routes. Verify ActivityPub content negotiation
   (`Accept: application/activity+json`) still works.
3. Decide fate of old assets: `app/static/app.js` and the map markup in
   `index.html` become dead — remove the script include and either delete
   `index.html`/`app.js` or leave the templates for auth/review pages only.
   Keep `style.css` only if still referenced.

### Phase 5 — verify
- `npm run build` succeeds; `uv run pheme` serves the built app at `/`.
- Manual smoke: map loads with seeded reviews, markers, sidebar, search,
  detail panel, form submit creates a review, auth flow works, phone-width
  layout works (browser devtools device mode).
- README smoke tests still pass (WebFinger, actor, outbox, `/api/reviews`,
  POST review, two-instance federation).
- `uv run ruff check app/` passes.

## 6. Backend changes (small, in scope)

1. **`GET /api/me`** → `{id, username, display_name}` for the session user,
   else 401 JSON. *Required* — today the user is only available via Jinja
   template context.
2. **401 JSON instead of 303 for fetch calls.** Today an unauthenticated
   `POST /api/reviews` raises `_LoginRequired` → 303 redirect to `/login`;
   `fetch()` follows it and returns HTML, which is confusing in a SPA.
   When the request's `Accept` includes `application/json` (or an
   `X-Requested-With` header is present), return `401 {"detail": ...}`
   instead. Keep the redirect for plain browser form posts.
3. **Accept JSON bodies on `POST /api/reviews`** in addition to form-encoded
   (future-proofs Capacitor/Sailfish clients). Recommended, small.
4. Keep `/review/{id}` server-rendered (shareable links / OG meta for a
   federated platform). Revisit only if native apps need a JSON detail route.

## 7. Gotchas

- **Vite `build.target: 'es2020'`** — Sailfish's Gecko WebView must run the
  bundle (future `sailfish-app/`).
- **SPA catch-all ordering** — must not shadow `/api/*`, `/actor/*`,
  `/.well-known/*`, `/static/*`, `/login`, `/register`, `/logout`,
  `/review/*`.
- **`SECRET_KEY` default** is `dev-secret-change-me-in-production`
  (`app/config.py`) — must be env-set in production. Flagged, out of scope.
- **Nominatim** is called client-side today; keep debouncing, respect the
  usage policy.
- **Auth pages as Jinja first pass** means login/register are full page
  loads, not in-app routes — acceptable for the migration; revisit when
  native apps need JSON auth (JWT).
- **No tests exist** in this repo — verification is manual + the README curl
  smoke tests + ruff.
- Leaflet CSS import in Vite; custom divIcon markers avoid the classic
  missing-marker-image issue.

## 8. Definition of done

- [ ] `react-app/` scaffolds; `npm install`, `npm run dev` (with proxy), and
      `npm run build` all work.
- [ ] FastAPI serves the built SPA at `/`; deep links work.
- [ ] Map page fully ported: markers, bounds-filtered loading, list, search,
      detail panel, review form (Nominatim search + map click + draggable
      marker + star rating), submit creates a review and refreshes.
- [ ] Auth: logged-out users can browse; posting requires login and sends
      the user to `/login`; login/register/logout work.
- [ ] Phone layout works (bottom sheet, full-screen map, FAB, `100dvh`).
- [ ] ActivityPub/WebFinger/outbox + README curl smoke tests still pass.
- [ ] `uv run ruff check app/` passes.
- [ ] Old `app.js` map logic removed or clearly superseded.

## 9. Out of scope (future jobs, own folders)

- `sailfish-app/` — Qt/QML Sailfish OS shell using `Sailfish.WebView`.
- Capacitor wrapper for Android/iOS.
- JWT/token auth for native apps; JSON auth endpoints for login/register.
- PWA manifest / service worker.
- Pagination / infinite scroll on `/api/reviews`.

## 10. Research notes (verified 2026-10-29)

- Flutter on Sailfish: no official support; open upstream issue
  `flutter/flutter#152624`. Only an unofficial experimental PoC runner exists
  (`github.com/mehmetfiskindal/flutter-sailfish`); its releases warn that apps
  needing its custom Sailjail permissions are "not suited to the Harbour
  store".
- Sailfish officially supports embedding web content:
  `github.com/sailfishos/sailfish-components-webview` (`Sailfish.WebView`,
  Gecko-based). Harbour accepts web-wrapper apps
  (e.g. `github.com/kierennicolas/harbour-smallworld`).
- Python is a supported Sailfish app language via PyOtherSide + QML
  (`wiki.qt.io/SailfishOS_Logic`) — an option if a native Sailfish UI is ever
  wanted, but the UI would still be QML.
- React Native: no Sailfish support.
