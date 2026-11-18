# Development

## Frontend development (hot reload)

Run the backend and the Vite dev server side by side — the Vite server
(port 5173) proxies API / auth / ActivityPub requests to the backend
(port 8000), so session cookies work same-origin:

```bash
# Terminal 1 — backend
uv run pheme

# Terminal 2 — React dev server
cd react-app && npm run dev
```

Open **<http://localhost:5173>**.  The production build (`npm run build`)
writes `react-app/dist/`, which FastAPI serves at `/`.

## Releasing

Releases are driven by git tags:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Pushing a `v*` tag runs the Forgejo Actions release pipeline
(`.forgejo/workflows/release.yml`): it uploads a source snapshot of the
tagged tree to a Forgejo release and publishes the sdist + wheel to PyPI
(the wheel bundles the built `react-app/dist`).  The published version is
the static `version` in `pyproject.toml` — bump it before tagging.

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

# Full-text search over review content / place name / address
curl "http://localhost:8000/api/reviews?q=coffee"

# Place search (proxied to Nominatim)
curl "http://localhost:8000/api/geocode?q=Ferry%20Building%20San%20Francisco"
```

### 2. Create a review through the API

Log in first (as `alice`, with the password printed by `uv run bootstrap`),
then post — the API accepts both form-encoded and JSON bodies:

```bash
# Log in (keeps the session cookie; the first response also sets the
# csrftoken cookie used for CSRF protection)
curl -s -c /tmp/pheme-cookies -b /tmp/pheme-cookies \
  -X POST http://localhost:8000/login \
  -d "username=alice&password=<password-from-bootstrap>"

# CSRF (starlette-csrf double-submit): while logged in, every unsafe
# request must send the csrftoken cookie's value back as a header.
CSRF=$(awk '$6=="csrftoken" {print $7}' /tmp/pheme-cookies)

# Form-encoded or JSON both work — include the X-CSRFToken header either way
curl -b /tmp/pheme-cookies -X POST http://localhost:8000/api/reviews \
  -H "X-CSRFToken: $CSRF" \
  -d "content=Great coffee and friendly staff!" \
  -d "rating=5" \
  -d "latitude=37.7749" \
  -d "longitude=-122.4194" \
  -d "place_name=Best Coffee" \
  -d "place_address=123 Main St"

curl -b /tmp/pheme-cookies -X POST http://localhost:8000/api/reviews \
  -H "X-CSRFToken: $CSRF" \
  -H "Content-Type: application/json" \
  -d '{"content":"Great coffee and friendly staff!","rating":5,"latitude":37.7749,"longitude":-122.4194,"place_name":"Best Coffee","place_address":"123 Main St"}'
```

### 3. Test federation between two local instances

```bash
# Terminal 1 — "Server A" on port 8000
uv run pheme

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
pheme/
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
├── docs/                     # Documentation (how it works, development, deployment, config, API)
│   └── screenshot.png        # Hero screenshot shown in the README
├── .forgejo/workflows/       # Forgejo Actions: Python + React pipelines on push; release on v* tags (Forgejo snapshot + PyPI)
├── data/                     # SQLite databases live here (auto-created)
├── .env.example              # Environment variable template
├── pyproject.toml            # Dependencies, RUFF config, build system
└── README.md
```
