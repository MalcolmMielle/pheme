# API reference

## ActivityPub endpoints

| Method | Path | Description |
| -------- | ------ | ------------- |
| `GET` | `/.well-known/webfinger?resource=acct:{user}@{domain}` | WebFinger discovery |
| `GET` | `/actor/{username}` | Actor document (JSON-LD) |
| `POST` | `/actor/{username}/inbox` | Receive activities (signed) |
| `GET` | `/actor/{username}/outbox` | Published activities |
| `GET` | `/actor/{username}/followers` | Followers collection |
| `GET` | `/actor/{username}/following` | Following collection |
| `POST` | `/inbox` | Shared inbox fallback |

## Web & JSON API

| Method | Path | Description |
| -------- | ------ | ------------- |
| `GET` | `/` | Map-based review browser (React SPA) |
| `GET` | `/review/{id}` | Single review page (server-rendered) |
| `GET` | `/api/meta` | Public server metadata (`{"registration_mode": ...}`) |
| `GET` | `/api/me` | Current session user (`{id, username, display_name, is_admin, actor_uri}`); 401 when logged out or suspended |
| `GET` | `/api/me/following` | The logged-in user's accepted follows (`{"following": [{actor_uri, username, display_name}]}`); 401 when logged out |
| `GET` | `/api/reviews` | JSON reviews (optional `?min_lat=&max_lat=&min_lng=&max_lng=&limit=&offset=&scope=&q=&min_rating=`; `scope` is `all` (default), `following` (own + followed actors, needs login), or `local` (this server's users only); `q` is a full-text filter over review content, place name and address and `min_rating` (1-5) keeps only reviews with at least that many stars — both combine with bounds and scope; the SPA's sidebar filter bar passes the visible map bounds, so review filtering stays in the shown region |
| `GET` | `/api/reviews/{id}` | Single review as JSON |
| `POST` | `/api/reviews` | Create review — form-encoded or JSON body (`content`, `rating`, `latitude`, `longitude`, `place_name`, `place_address`); requires login + `X-CSRFToken` header |
| `DELETE` | `/api/reviews/{id}` | Delete a review (author only) |
| `POST` | `/api/follow` | Follow a remote actor (form: `target` — URI or `acct:user@domain`) |
| `POST` | `/api/unfollow` | Unfollow an actor (form: `target` — URI or `acct:user@domain`); sends an `Undo` to the remote inbox |
| `GET` | `/api/geocode?q=` | Proxy place search to Nominatim |
| `GET` | `/api/reverse-geocode?lat=&lon=` | Reverse geocode via Nominatim (`addressdetails=1`, so the structured address is returned as `address_details`), preferring a nearby POI (commerce, hospital, parking, …) over a bare street address (OSM API lookup); the response includes a ranked `candidates` list of nearby POIs — each with its reviewable tag key (`type`), value (`value`) and a whitelist of OSM tags (`tags`: website, phone, opening_hours, cuisine, wheelchair, ele, addr:*) — so the UI can disambiguate when several share one spot (each row shows the place's own address) and show the place's details |
| `POST` | `/api/bootstrap` | Create the first actor (one-time; 403 once any account exists) |

## Admin API (session of an admin required; unsafe methods need `X-CSRFToken`)

| Method | Path | Description |
| -------- | ------ | ------------- |
| `GET` | `/api/admin/users` | List local accounts (`is_admin`, `is_suspended`, …) |
| `POST` | `/api/admin/users` | Create an account (form: `username`, `display_name`, `password`, `is_admin`) |
| `POST` | `/api/admin/users/{id}/promote` / `/demote` | Grant / revoke admin |
| `POST` | `/api/admin/users/{id}/suspend` / `/unsuspend` | Block / restore login (invalidates sessions) |
| `DELETE` | `/api/admin/users/{id}` | Delete the account and its local reviews |
| `GET` | `/api/admin/invites` | List invite codes (`registration_mode`, shareable `register_url`) |
| `POST` | `/api/admin/invites` | Create a one-time invite code (optional form field `expires_in_days`) |
| `DELETE` | `/api/admin/invites/{id}` | Revoke an unused invite code |
