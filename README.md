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

**Prerequisites:** Python ≥ 3.13, [uv](https://docs.astral.sh/uv/)

```bash
# Clone and enter the project
git clone <repo-url> federated-reviews
cd federated-reviews

# Install dependencies
uv sync

# Optional: create a .env file from the template
cp .env.example .env
# Edit .env and set SECRET_KEY at minimum

# Seed demo data (creates actor "alice" + 8 sample reviews in San Francisco)
uv run bootstrap

# Start the development server
uv run fedreviews
```

Open **<http://localhost:8000>** — you should see a map of San Francisco with
8 coloured markers.  Click any marker or sidebar card to see the review
detail.  Click the **＋** button to write your own review.

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
```

### 2. Create a review through the API

```bash
curl -X POST http://localhost:8000/api/reviews \
  -d "username=alice" \
  -d "content=Great coffee and friendly staff!" \
  -d "rating=5" \
  -d "latitude=37.7749" \
  -d "longitude=-122.4194" \
  -d "place_name=Best Coffee" \
  -d "place_address=123 Main St"
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
uv sync --group dev     # install pytest + dev tools (once)
uv run pytest           # run all 67 tests
uv run pytest -v        # verbose output
uv run pytest tests/test_db.py   # run a single test file
```

### 5. Run the linter

```bash
uv sync --group dev     # install ruff + basedpyright (once)
uv run ruff check app/  # lint check
uv run ruff format app/ # auto-format
```

## Project layout

```
federated-reviews/
├── app/
│   ├── main.py               # FastAPI application — entry point
│   ├── config.py             # Config from environment / .env / defaults
│   ├── auth.py               # Session-based auth dependency
│   ├── middleware.py         # CSRF protection middleware
│   ├── bootstrap.py          # Seed script (actor + demo reviews)
│   ├── models.py             # ActivityPub Pydantic models
│   ├── db/
│   │   ├── connection.py     # SQLite connection, schema, pragmas
│   │   ├── actors.py         # Actor CRUD + password hashing
│   │   ├── reviews.py        # Review CRUD, bounds queries, pagination
│   │   └── follows.py        # Follow/follower relationships
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
│   │   ├── api.py            # JSON API: reviews, follow, geocode, bootstrap
│   │   └── web.py            # Server-rendered HTML: map, login, register
│   ├── templates/
│   │   ├── base.html         # Leaflet CSS/JS shell
│   │   ├── index.html        # Map + sidebar + review form
│   │   ├── review.html       # Standalone review detail page
│   │   ├── login.html        # Login form
│   │   └── register.html     # Registration form
│   └── static/
│       ├── style.css         # Google Maps-inspired design
│       └── app.js            # Leaflet map, markers, star rating, search
├── tests/                    # pytest suite (67 tests)
│   ├── conftest.py           # Fixtures: client, db, registered_user
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
| **Templates** | Jinja2 (via Starlette) | Server-rendered HTML |
| **Map** | Leaflet.js + OpenStreetMap | Free, no API keys, looks like Google Maps |
| **Database** | aiosqlite | Zero-config, async, perfect for MVP |
| **Federation** | ActivityPub (hand-rolled) | HTTP Signatures, WebFinger, Actor model |
| **HTTP client** | httpx | Async outbound requests for federation |
| **Crypto** | cryptography | RSA key generation, SHA256 signing |
| **Linting** | ruff | Fast, all-in-one replacement for Flake8/Black |

## Configuration

Configuration is read from environment variables. You can set them in the
shell or create a `.env` file (see `.env.example` for a template) — the
app loads it automatically via [python-dotenv](https://pypi.org/project/python-dotenv/).

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | `http://localhost:8000` | Public URL of this server (used in all ActivityPub IDs) |
| `HOST` | `127.0.0.1` | Bind address for uvicorn |
| `PORT` | `8000` | Port for uvicorn |
| `RELOAD` | `true` | Enable uvicorn auto-reload (set to `false` in production) |
| `DATABASE_PATH` | `data/reviews.db` | Path to the SQLite file |
| `SECRET_KEY` | *(random, with warning)* | Session signing key — set this in production |

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
| `GET` | `/` | Map-based review browser |
| `GET` | `/review/{id}` | Single review page |
| `GET` | `/api/reviews` | JSON reviews (optional `?min_lat=&max_lat=&min_lng=&max_lng=&limit=&offset=`) |
| `GET` | `/api/reviews/{id}` | Single review as JSON |
| `POST` | `/api/reviews` | Create review (form: `content`, `rating`, `latitude`, `longitude`, `place_name`, `place_address`) |
| `DELETE` | `/api/reviews/{id}` | Delete a review (author only) |
| `POST` | `/api/follow` | Follow a remote actor (form: `target` — URI or `acct:user@domain`) |
| `GET` | `/api/geocode?q=` | Proxy place search to Nominatim |
| `GET` | `/api/reverse-geocode?lat=&lon=` | Proxy reverse geocode to Nominatim |
| `POST` | `/api/bootstrap` | Create first actor (form: `username`, `display_name`) |

## Licence

MIT
