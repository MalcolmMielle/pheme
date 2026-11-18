# How it works

Every server runs its own instance.  Users post reviews tied to a latitude /
longitude.  When Alice on **server-a.example.com** follows Bob on
**server-b.example.com**, Alice's server receives every review Bob publishes
— and displays them on its own map alongside local reviews.  No central
authority, no paid API keys, no vendor lock-in.

## ActivityPub in 60 seconds

| Concept | What it is | Route on this server |
| --------- | ----------- | --------------------- |
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

## Tech stack

| Layer | Choice | Rationale |
| ------- | -------- | ----------- |
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
| **CI** | Forgejo Actions (`node:22`) | unittest suite, ruff, basedpyright and the React build on push + PRs; on `v*` tag pushes: Forgejo release (source snapshot) + PyPI publish |
