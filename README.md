# 🗺️ Federated Reviews

A decentralised review platform that looks and feels like Google Maps /
OpenStreetMap — but built on ActivityPub so that independent servers can
federate reviews with each other.  Think Mastodon, but for location-based
reviews.

## How it works

Every server runs its own instance.  Users post reviews tied to a latitude /
longitude.  When Alice on **server-a.example.com** follows Bob on
**server-b.example.com**, Alice's server receives every review Bob publishes
— and displays them on its own map alongside local reviews.  No central
authority, no paid API keys, no vendor lock-in.

### ActivityPub in 60 seconds

| Concept | What it is | Route on this server |
|---------|-----------|---------------------|
| **Actor** | A user (or server) with a public/private keypair | `GET /actor/{username}` |
| **WebFinger** | Maps `user@domain` → actor URI so servers can discover each other | `GET /.well-known/webfinger` |
| **Inbox** | Where remote servers POST activities for *this* actor | `POST /actor/{username}/inbox` |
| **Outbox** | Where *this* actor's activities are published | `GET /actor/{username}/outbox` |
| **HTTP Signatures** | Every federated delivery is RSA-SHA256-signed; the receiver verifies with the sender's public key | `Signature` header |
| **Review** | An ActivityStreams `Note` with extra location fields (`latitude`, `longitude`, `rating`, `placeName`) | Embedded in `Create` activities |

**Federation flow in one picture:**

```txt
Alice creates a review on Server A
        │
        ▼
Stored in Server A's local database
        │
        ▼
Server A builds a "Create" activity wrapping the review,
signs it with Alice's private key
        │
        ▼
Server A POSTs to every follower's inbox:
  → Bob@ServerB/inbox    (Server B verifies signature, stores review)
  → Carol@ServerC/inbox  (Server C verifies signature, stores review)
        │
        ▼
Users on Server B and C now see Alice's review on their maps
```

## Quick start

**Prerequisites:** Python ≥ 3.13, [uv](https://docs.astral.sh/uv/),
Node.js ≥ 20

```bash
# Clone and enter the project
git clone <repo-url> federated-reviews
cd federated-reviews

# Install backend dependencies
uv sync

# Optional: create a .env file from the template
cp .env.example .env
# Edit .env and set SECRET_KEY at minimum

# Install + build the React frontend (react-app/)
cd react-app && npm install && npm run build && cd ..

# Seed demo data (creates actor "alice" + 8 sample reviews in San Francisco)
uv run bootstrap

# Start the development server
uv run fedreviews
```

Open **<http://localhost:8000>** — you should see a map of San Francisco with
8 coloured markers.  Click any marker or sidebar card to see the review
detail.  Click the **＋** button to write your own review.

### Frontend development (hot reload)

Run the backend and the Vite dev server side by side — the Vite server
(port 5173) proxies API / auth / ActivityPub requests to the backend
(port 8000), so session cookies work same-origin:

```bash
# Terminal 1 — backend
uv run fedreviews

# Terminal 2 — React dev server
cd react-app && npm run dev
```

Open **<http://localhost:5173>**.  The production build (`npm run build`)
writes `react-app/dist/`, which FastAPI serves at `/`.

## How to test

### 1. Smoke-test the endpoints

```bash
# Start the server first, then in another terminal:

# WebFinger — service discovery
curl "http://localhost:8000/.well-known/webfinger?resource=acct:alice@localhost:8000"

# Actor document (ActivityPub JSON)
curl -H "Accept: application/activity+json" http://localhost:8000/actor/alice

# Outbox — all published reviews as ActivityStreams activities
curl http://localhost:8000/actor/alice/outbox

# Reviews as JSON
curl http://localhost:8000/api/reviews

# Reviews filtered by map bounds
curl "http://localhost:8000/api/reviews?min_lat=37.70&max_lat=37.85&min_lng=-122.50&max_lng=-122.35"

# Place search (proxied to Nominatim)
curl "http://localhost:8000/api/geocode?q=Ferry%20Building%20San%20Francisco"
```

### 2. Create a review through the API

Log in first (as `alice`, with the password printed by `uv run bootstrap`),
then post — the API accepts both form-encoded and JSON bodies:

```bash
# Log in (keeps the session cookie; the first response also sets the
# csrftoken cookie used for CSRF protection)
curl -s -c /tmp/fedreviews-cookies -b /tmp/fedreviews-cookies \
  -X POST http://localhost:8000/login \
  -d "username=alice&password=<password-from-bootstrap>"

# CSRF (starlette-csrf double-submit): while logged in, every unsafe
# request must send the csrftoken cookie's value back as a header.
CSRF=$(awk '$6=="csrftoken" {print $7}' /tmp/fedreviews-cookies)

# Form-encoded or JSON both work — include the X-CSRFToken header either way
curl -b /tmp/fedreviews-cookies -X POST http://localhost:8000/api/reviews \
  -H "X-CSRFToken: $CSRF" \
  -d "content=Great coffee and friendly staff!" \
  -d "rating=5" \
  -d "latitude=37.7749" \
  -d "longitude=-122.4194" \
  -d "place_name=Best Coffee" \
  -d "place_address=123 Main St"

curl -b /tmp/fedreviews-cookies -X POST http://localhost:8000/api/reviews \
  -H "X-CSRFToken: $CSRF" \
  -H "Content-Type: application/json" \
  -d '{"content":"Great coffee and friendly staff!","rating":5,"latitude":37.7749,"longitude":-122.4194,"place_name":"Best Coffee","place_address":"123 Main St"}'
```

### 3. Test federation between two local instances

```bash
# Terminal 1 — "Server A" on port 8000
uv run fedreviews

# Terminal 2 — "Server B" on port 8001
BASE_URL=http://localhost:8001 DATABASE_PATH=data/reviews-b.db \
  uvicorn app.main:app --port 8001

# Bootstrap Server B
curl -X POST http://localhost:8001/api/bootstrap \
  -d "username=bob&display_name=Bob"

# On Server B, follow Alice on Server A:
# (Send a Follow activity to Alice's inbox)
# Alice's server will auto-accept and start federating reviews.
```

### 4. Run the tests

```bash
uv sync --group dev                           # install dev tools (once)
uv run python -m unittest discover -s tests   # run all 137 tests
uv run python -m unittest discover -s tests -v  # verbose output
uv run python -m unittest tests.test_db -v    # run a single test file
```

### 5. Run the linter

```bash
uv sync --group dev     # install ruff + basedpyright (once)
uv run ruff format --check app/ tests/  # format check (runs in CI)
uv run ruff check app/ tests/           # lint check
uv run ruff format app/                 # auto-format
uv run basedpyright app/ tests/         # type check
```

## Project layout

```
federated-reviews/
├── app/
│   ├── main.py               # FastAPI application — entry point + serves react-app/dist
│   ├── config.py             # Config from environment / .env / defaults
│   ├── auth.py               # Session-based auth dependency
│   ├── forms.py              # Pydantic validation for registration forms
│   ├── ratelimit.py          # slowapi rate limiter (login/register/bootstrap)
│   ├── bootstrap.py          # Seed script (actor + demo reviews)
│   ├── models.py             # ActivityPub Pydantic models
│   ├── db/
│   │   ├── connection.py     # SQLite connection, schema, pragmas
│   │   ├── actors.py         # Actor CRUD + password hashing
│   │   ├── reviews.py        # Review CRUD, bounds queries, pagination
│   │   ├── follows.py        # Follow/follower relationships
│   │   └── invites.py        # One-time invite codes (invite registration mode)
│   ├── activitypub/
│   │   ├── signing.py        # HTTP Signatures (RSA-SHA256)
│   │   ├── actor.py          # Actor JSON builders, Follow/Accept
│   │   └── delivery.py       # Federation fan-out to remote inboxes
│   ├── routes/
│   │   ├── activitypub/
│   │   │   ├── helpers.py        # URI builders, remote actor fetch
│   │   │   ├── webfinger.py      # /.well-known/webfinger
│   │   │   ├── actor.py          # /actor/{username}
│   │   │   ├── inbox.py          # /actor/{username}/inbox + handlers
│   │   │   └── collections.py    # Outbox, Followers, Following, Shared inbox
│   │   ├── api.py            # JSON API: reviews, follow, geocode, /api/me
│   │   └── web.py            # Server-rendered HTML: login, register, review detail
│   ├── templates/
│   │   ├── base.html         # Shell for the server-rendered pages
│   │   ├── login.html        # Login form
│   │   ├── register.html     # Registration form
│   │   └── review.html       # Standalone review detail page
│   └── static/
│       └── style.css         # Styles for the server-rendered pages
├── react-app/                # React + Vite + TypeScript SPA (the map page)
│   ├── src/                  # Components: map, list, detail, review form
│   ├── package.json          # JS dependencies
│   └── dist/                 # Production build, served by FastAPI (gitignored)
├── tests/                    # unittest suite (137 tests)
│   ├── base.py               # Shared test base: fresh DB + ASGI client per test
│   ├── test_signing.py       # HTTP Signature unit tests
│   ├── test_db.py            # Database layer tests
│   ├── test_api.py           # JSON API endpoint tests
│   ├── test_activitypub.py   # ActivityPub endpoint tests
│   └── test_web.py           # Web UI / auth flow tests
├── data/                     # SQLite databases live here (auto-created)
├── .env.example              # Environment variable template
├── pyproject.toml            # Dependencies, RUFF config, build system
└── README.md
```

## Tech stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Web framework** | FastAPI + uvicorn | Async, modern, great OpenAPI docs |
| **Frontend** | React + Vite + TypeScript (`react-app/`) | SPA for the map page; one codebase, reused by future native shells |
| **Templates** | Jinja2 (via Starlette) | Server-rendered pages: login/register, review detail |
| **Map** | Leaflet.js (react-leaflet) + OpenStreetMap | Free, no API keys, looks like Google Maps |
| **Database** | aiosqlite | Zero-config, async, perfect for MVP |
| **Federation** | ActivityPub (hand-rolled) | HTTP Signatures, WebFinger, Actor model |
| **HTTP client** | httpx | Async outbound requests for federation + Nominatim proxy |
| **Crypto** | cryptography | RSA key generation, SHA256 signing |
| **Testing** | unittest (137 tests) | Endpoint, database, signing and auth-flow coverage |
| **Linting** | ruff + basedpyright | Fast lint/format + static type checking |
| **CI** | Forgejo Actions (`node:22`) | unittest suite, ruff, basedpyright and the React build on push + PRs |

## Configuration

Configuration is read from environment variables. You can set them in the
shell or create a `.env` file (see `.env.example` for a template) — the
app loads it automatically via [python-dotenv](https://pypi.org/project/python-dotenv/).

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | `http://localhost:8000` | Public URL of this server (used in all ActivityPub IDs) |
| `HOST` | `127.0.0.1` | Bind address for uvicorn |
| `PORT` | `8000` | Port for uvicorn |
| `RELOAD` | `false` | Enable uvicorn auto-reload (development only) |
| `DATABASE_PATH` | `data/reviews.db` | Path to the SQLite file |
| `SECRET_KEY` | *(random, with warning)* | Session + CSRF signing key — set this in production |
| `SESSION_MAX_AGE` | `2592000` (30 days) | Session cookie lifetime in seconds |
| `PASSWORD_MIN_LENGTH` | `8` | Minimum password length for new accounts |
| `REGISTRATION_MODE` | `open` | `open` = anyone can register, `invite` = valid one-time invite code required, `closed` = admins create accounts only |

## Registration & moderation

Session auth is self-hosted (signed cookie + bcrypt passwords) — no external
identity provider. CSRF protection is the
[starlette-csrf](https://pypi.org/project/starlette-csrf/) library
(double-submit cookie): while logged in, unsafe requests must send the
`csrftoken` cookie's value as an `X-CSRFToken` header. Login and register are
rate-limited per IP (`slowapi`): 5/minute and 3/minute respectively.

Set `REGISTRATION_MODE` to control who can create accounts:

- **`open`** (default) — anyone can register at `/register`.
- **`invite`** — `/register` requires a one-time invite code. Admins create
  codes in the admin panel (profile page) or via `POST /api/admin/invites`;
  each code yields a shareable `/register?code=...` link. Codes can be revoked
  (`DELETE /api/admin/invites/{id}`) and may expire.
- **`closed`** — the registration form is disabled; admins create accounts via
  `POST /api/admin/users`. (`POST /api/bootstrap` is one-time setup only and
  refuses once any account exists.)

Admins (the first account created is the admin) can also suspend or delete
accounts from the admin panel: `POST /api/admin/users/{id}/suspend` /
`/unsuspend` block login and invalidate existing sessions;
`DELETE /api/admin/users/{id}` removes the account and all its local reviews.
An admin cannot moderate themselves or remove the last admin.

## API reference

### ActivityPub endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/.well-known/webfinger?resource=acct:{user}@{domain}` | WebFinger discovery |
| `GET` | `/actor/{username}` | Actor document (JSON-LD) |
| `POST` | `/actor/{username}/inbox` | Receive activities (signed) |
| `GET` | `/actor/{username}/outbox` | Published activities |
| `GET` | `/actor/{username}/followers` | Followers collection |
| `GET` | `/actor/{username}/following` | Following collection |
| `POST` | `/inbox` | Shared inbox fallback |

### Web & JSON API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Map-based review browser (React SPA) |
| `GET` | `/review/{id}` | Single review page (server-rendered) |
| `GET` | `/api/meta` | Public server metadata (`{"registration_mode": ...}`) |
| `GET` | `/api/me` | Current session user (`{id, username, display_name, is_admin, actor_uri}`); 401 when logged out or suspended |
| `GET` | `/api/me/following` | The logged-in user's accepted follows (`{"following": [{actor_uri, username, display_name}]}`); 401 when logged out |
| `GET` | `/api/reviews` | JSON reviews (optional `?min_lat=&max_lat=&min_lng=&max_lng=&limit=&offset=&scope=`; `scope` is `all` (default), `following` (own + followed actors, needs login), or `local` (this server's users only)) |
| `GET` | `/api/reviews/{id}` | Single review as JSON |
| `POST` | `/api/reviews` | Create review — form-encoded or JSON body (`content`, `rating`, `latitude`, `longitude`, `place_name`, `place_address`); requires login + `X-CSRFToken` header |
| `DELETE` | `/api/reviews/{id}` | Delete a review (author only) |
| `POST` | `/api/follow` | Follow a remote actor (form: `target` — URI or `acct:user@domain`) |
| `POST` | `/api/unfollow` | Unfollow an actor (form: `target` — URI or `acct:user@domain`); sends an `Undo` to the remote inbox |
| `GET` | `/api/geocode?q=` | Proxy place search to Nominatim |
| `GET` | `/api/reverse-geocode?lat=&lon=` | Proxy reverse geocode to Nominatim |
| `POST` | `/api/bootstrap` | Create the first actor (one-time; 403 once any account exists) |

### Admin API (session of an admin required; unsafe methods need `X-CSRFToken`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/users` | List local accounts (`is_admin`, `is_suspended`, …) |
| `POST` | `/api/admin/users` | Create an account (form: `username`, `display_name`, `password`, `is_admin`) |
| `POST` | `/api/admin/users/{id}/promote` / `/demote` | Grant / revoke admin |
| `POST` | `/api/admin/users/{id}/suspend` / `/unsuspend` | Block / restore login (invalidates sessions) |
| `DELETE` | `/api/admin/users/{id}` | Delete the account and its local reviews |
| `GET` | `/api/admin/invites` | List invite codes (`registration_mode`, shareable `register_url`) |
| `POST` | `/api/admin/invites` | Create a one-time invite code (optional form field `expires_in_days`) |
| `DELETE` | `/api/admin/invites/{id}` | Revoke an unused invite code |

## Licence

MIT
