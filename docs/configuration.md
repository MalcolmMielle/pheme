# Configuration

Configuration is read from environment variables. You can set them in the
shell or create a `.env` file (see `.env.example` for a template) — the
app loads it automatically via [python-dotenv](https://pypi.org/project/python-dotenv/).

| Variable | Default | Description |
| ---------- | --------- | ------------- |
| `BASE_URL` | `http://localhost:8000` | Public URL of this server (used in all ActivityPub IDs) |
| `HOST` | `127.0.0.1` | Bind address for uvicorn |
| `PORT` | `8000` | Port for uvicorn |
| `RELOAD` | `false` | Enable uvicorn auto-reload (development only) |
| `PROXY_HEADERS` | `false` | Trust `X-Forwarded-*` headers from a reverse proxy on the same machine (set `true` behind Caddy/nginx so rate limiting sees real client IPs) |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Comma-separated proxy IPs allowed to set `X-Forwarded-For` |
| `DATABASE_PATH` | `data/reviews.db` | Path to the SQLite file |
| `SECRET_KEY` | *(random, with warning)* | Session + CSRF signing key — set this in production |
| `SESSION_MAX_AGE` | `2592000` (30 days) | Session cookie lifetime in seconds |
| `PASSWORD_MIN_LENGTH` | `8` | Minimum password length for new accounts |
| `REGISTRATION_MODE` | `open` | `open` = anyone can register, `invite` = valid one-time invite code required, `closed` = admins create accounts only |
| `PLACE_DECIMALS` | `4` | Precision of the "same place" coordinate bucket (decimal places of lat/lng, ~11 m per step at 4) — drives map place grouping and the one-review-per-actor-per-place rule; exposed to the SPA via `/api/meta` |
| `REVIEWABLE_TAGS` | `shop,office,tourism,leisure,healthcare,emergency,craft,historic,man_made,amenity,place,highway,natural=peak,natural=saddle,!amenity=toilets,!amenity=bench,!amenity=waste_basket,!amenity=drinking_water,!amenity=sanitary_dump_station,!amenity=recycling,!amenity=charging_station,!amenity=vending_machine,!amenity=water_point,!amenity=compressed_air` | Which OSM places can be reviewed (map-click candidates, sorted by distance): comma-separated `key` or `key=value` specs, `!key=value` to exclude. The default covers POIs, roads, localities and peaks/passes (`natural=peak`, `natural=saddle`) but excludes utility amenities like toilets/benches (add e.g. `amenity=toilets` back if you want to rate them) |

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
