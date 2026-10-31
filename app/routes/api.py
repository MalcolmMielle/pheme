"""
JSON API routes — review CRUD, geocode proxy, /api/me, and bootstrap.

Follow/unfollow live in routes/follow.py; admin endpoints (accounts, invite
codes) live in routes/admin.py. The WebFinger resolution helpers at the
bottom are shared with routes/follow.py.
"""

import asyncio
import ipaddress
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.activitypub.actor import actor_to_ap
from app.activitypub.delivery import fanout_activity
from app.activitypub.fetchguard import check_fetch_url
from app.auth import get_current_user, get_session_actor
from app.db import (
    count_reviews,
    count_reviews_by_bounds,
    create_review,
    delete_review,
    get_actor_by_id,
    get_actor_by_username,
    get_follower_inboxes,
    get_following,
    get_following_actors,
    get_review_by_id,
    get_reviews,
    get_reviews_by_bounds,
    hash_password,
    list_local_actors,
)
from app.config import config
from app.ratelimit import limiter
from app.routes.activitypub import create_local_actor
from app.routes.activitypub.helpers import build_create_activity

logger = logging.getLogger("pheme")

router = APIRouter()

_NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
_NOMINATIM_HEADERS = {
    "User-Agent": f"Pheme/0.1 ({config.base_url})",
    "Accept-Language": "en",
}

# Nominatim usage policy: at most 1 request/second — throttle upstream
# calls and cache repeated lookups.
_NOMINATIM_MIN_INTERVAL = 1.0
_NOMINATIM_CACHE_TTL = 300.0
_nominatim_cache: dict[tuple, tuple[float, Any]] = {}
_nominatim_last_request = 0.0
_nominatim_lock = asyncio.Lock()


async def _nominatim_get(path: str, params: dict[str, Any]) -> JSONResponse:
    """GET a Nominatim endpoint, cached and throttled to 1 req/s.

    Only successful (200) responses are cached; upstream errors surface as
    502 instead of leaking Nominatim's status/body to the SPA.
    """
    global _nominatim_last_request

    key = (path, tuple(sorted(params.items())))
    now = time.monotonic()
    cached = _nominatim_cache.get(key)
    if cached is not None and now - cached[0] < _NOMINATIM_CACHE_TTL:
        return JSONResponse(cached[1])

    async with _nominatim_lock:
        wait = _NOMINATIM_MIN_INTERVAL - (time.monotonic() - _nominatim_last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        _nominatim_last_request = time.monotonic()
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    f"{_NOMINATIM_BASE}{path}",
                    params=params,
                    headers=_NOMINATIM_HEADERS,
                )
            except httpx.RequestError as exc:
                logger.warning("Nominatim %s failed: %s", path, exc)
                raise HTTPException(502, "Geocoding service unavailable") from exc

    if resp.status_code != 200:
        logger.warning("Nominatim %s returned %d", path, resp.status_code)
        raise HTTPException(502, "Geocoding service unavailable")

    data = resp.json()
    if len(_nominatim_cache) > 1000:
        _nominatim_cache.clear()
    _nominatim_cache[key] = (time.monotonic(), data)
    return JSONResponse(data)


@router.get("/api/me")
async def api_me(request: Request) -> JSONResponse:
    """Current session user for the SPA, or 401 JSON when logged out.

    The CSRF token is not returned here — the SPA reads the ``csrftoken``
    cookie (starlette-csrf double-submit) and sends it as the x-csrftoken
    header on unsafe requests.
    """
    actor = await get_session_actor(request)
    if actor is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return JSONResponse(
        {
            "id": actor["id"],
            "username": actor["username"],
            "display_name": actor["display_name"],
            "is_admin": bool(actor.get("is_admin")),
            "actor_uri": actor["actor_uri"],
        }
    )


@router.get("/api/meta")
async def api_meta() -> JSONResponse:
    """Public server metadata for the SPA (registration mode, etc.)."""
    return JSONResponse({"registration_mode": config.registration_mode})


@router.get("/api/me/following")
async def api_me_following(actor: dict = Depends(get_current_user)) -> JSONResponse:
    """The logged-in user's accepted follows, with cached actor details.

    Returns ``{"following": [{actor_uri, username, display_name}]}`` —
    the accounts whose new reviews federate to this server.
    """
    return JSONResponse({"following": await get_following_actors(actor["id"])})


@router.get("/api/geocode")
async def api_geocode(
    q: str, limit: int = Query(default=5, ge=1, le=50)
) -> JSONResponse:
    """Proxy a place search to Nominatim (avoids exposing user IPs)."""
    return await _nominatim_get(
        "/search",
        {"q": q, "format": "json", "limit": limit, "addressdetails": 1},
    )


@router.get("/api/reverse-geocode")
async def api_reverse_geocode(lat: float, lon: float) -> JSONResponse:
    """Proxy a reverse geocode lookup to Nominatim."""
    return await _nominatim_get("/reverse", {"lat": lat, "lon": lon, "format": "json"})


@router.get("/api/reviews")
async def api_reviews(
    request: Request,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lng: float | None = None,
    max_lng: float | None = None,
    scope: str = "all",
    # ge=1: SQLite treats a negative LIMIT as "unlimited", which would dump
    # the whole table on ?limit=-1.
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """Return reviews, optionally filtered by map bounds. Supports pagination.

    ``scope=following`` restricts the result to the logged-in user's own
    reviews plus reviews by actors they follow (401 when logged out);
    ``scope=local`` returns only reviews by local actors (no login needed);
    ``scope=all`` (default) returns everything.
    """
    if scope not in ("all", "following", "local"):
        raise HTTPException(400, "scope must be 'all', 'following' or 'local'")

    actor_uris: list[str] | None = None
    if scope == "following":
        user_id = request.session.get("user_id")
        actor = await get_actor_by_id(user_id) if user_id is not None else None
        if actor is None:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        actor_uris = [actor["actor_uri"], *(await get_following(actor["id"]))]
    elif scope == "local":
        actor_uris = [a["actor_uri"] for a in await list_local_actors()]

    if (
        min_lat is not None
        and max_lat is not None
        and min_lng is not None
        and max_lng is not None
    ):
        reviews = await get_reviews_by_bounds(
            min_lat,
            max_lat,
            min_lng,
            max_lng,
            limit=limit,
            offset=offset,
            actor_uris=actor_uris,
        )
        total = await count_reviews_by_bounds(
            min_lat, max_lat, min_lng, max_lng, actor_uris=actor_uris
        )
    else:
        reviews = await get_reviews(limit=limit, offset=offset, actor_uris=actor_uris)
        total = await count_reviews(actor_uris=actor_uris)
    return JSONResponse(
        reviews,
        headers={"X-Total-Count": str(total)},
    )


@router.get("/api/reviews/{review_id}")
async def api_get_review(review_id: int) -> JSONResponse:
    """Return a single review by ID."""
    review = await get_review_by_id(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    return JSONResponse(review)


class CreateReviewPayload(BaseModel):
    """Payload for POST /api/reviews — JSON body or form fields."""

    content: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
    latitude: float
    longitude: float
    place_name: str = ""
    place_address: str = ""


@router.post("/api/reviews")
async def api_create_review(
    request: Request,
    actor: dict = Depends(get_current_user),
) -> JSONResponse:
    """Create a new review and federate it to followers.

    Accepts both form-encoded bodies (browser forms, curl) and JSON bodies
    (the React SPA and future native clients); both are validated against
    CreateReviewPayload.
    """
    content_type = request.headers.get("content-type", "")
    raw: Any
    if "application/json" in content_type:
        raw = await request.json()
    else:
        form = await request.form()
        # Keep plain text fields only (multipart uploads are not review data)
        raw = {k: v for k, v in form.items() if isinstance(v, str)}

    try:
        payload = CreateReviewPayload.model_validate(raw)
    except ValidationError:
        return JSONResponse(
            {"detail": "Required: content, rating (1-5), latitude, longitude"},
            status_code=422,
        )

    ap_id = f"{actor['actor_uri']}/review/{uuid.uuid4()}"
    review = await create_review(
        actor_id=actor["id"],
        ap_id=ap_id,
        content=payload.content,
        rating=payload.rating,
        latitude=payload.latitude,
        longitude=payload.longitude,
        place_name=payload.place_name,
        place_address=payload.place_address,
    )

    activity = build_create_activity(actor, review)

    follower_inboxes = await get_follower_inboxes(actor["id"])
    result = await fanout_activity(
        activity,
        f"{actor['actor_uri']}#main-key",
        actor["private_key_pem"],
        follower_inboxes,
    )

    logger.info(
        "Created review %s — federated to %d followers (%d ok, %d fail)",
        ap_id,
        len(follower_inboxes),
        result["ok"],
        result["fail"],
    )

    return JSONResponse({"status": "ok", "review": review, "federation": result})


@router.delete("/api/reviews/{review_id}")
async def api_delete_review(
    review_id: int,
    actor: dict = Depends(get_current_user),
) -> JSONResponse:
    """Delete a review. Only the author can delete their own reviews."""
    review = await get_review_by_id(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    if review["actor_id"] != actor["id"]:
        raise HTTPException(403, "You can only delete your own reviews")

    deleted = await delete_review(review_id)
    if not deleted:
        raise HTTPException(404, "Review not found")

    # Federate a Delete activity to followers
    delete_activity: dict[str, Any] = {
        "id": f"{review['ap_id']}/delete",
        "type": "Delete",
        "actor": actor["actor_uri"],
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [actor["followers_uri"]],
        "object": {
            "id": review["ap_id"],
            "type": "Note",
        },
    }
    follower_inboxes = await get_follower_inboxes(actor["id"])
    if follower_inboxes:
        await fanout_activity(
            delete_activity,
            f"{actor['actor_uri']}#main-key",
            actor["private_key_pem"],
            follower_inboxes,
        )

    logger.info("Deleted review %s (ap_id=%s)", review_id, review["ap_id"])
    return JSONResponse({"status": "deleted", "id": review_id})


@router.post("/api/bootstrap")
@limiter.limit("5/minute")
async def api_bootstrap(
    request: Request,
    username: str = Form("admin"),
    display_name: str = Form("Admin"),
    password: str = Form(""),
) -> JSONResponse:
    """Create the first local actor (one-time setup)."""
    existing = await get_actor_by_username(username)
    if existing:
        return JSONResponse(
            {"status": "exists", "actor": actor_to_ap(existing).model_dump()}
        )

    # One-time setup only: once any local account exists, bootstrap refuses —
    # otherwise it would be an unauthenticated account-creation backdoor.
    if await list_local_actors():
        raise HTTPException(403, "Server already has accounts — bootstrap is one-time")

    # No explicit is_admin: the first account created on the server
    # automatically becomes the first admin (see create_local_actor).
    actor = await create_local_actor(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password) if password else None,
    )
    return JSONResponse({"status": "created", "actor": actor_to_ap(actor).model_dump()})


# ── helpers ─────────────────────────────────────────────────────────────


def _webfinger_schemes(domain: str) -> list[str]:
    """URL schemes to try for WebFinger, in priority order.

    Public hosts are only contacted over HTTPS. Local/private hosts
    (localhost, loopback or private IPs — e.g. a dev server at
    http://localhost:8001, which has no TLS certificate) are tried over
    plain HTTP first.
    """
    host = domain.split(":", 1)[0].strip("[]").lower()
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_private:
            return ["http", "https"]
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".localhost"):
        return ["http", "https"]
    return ["https"]


async def _resolve_actor_uri(target: str) -> str | None:
    """Resolve an actor URI from a target string (URI or acct:user@domain)."""
    target = target.strip()

    # Direct URI
    if target.startswith("https://") or target.startswith("http://"):
        return target

    # acct:user@domain → WebFinger
    if target.startswith("acct:"):
        target = target[5:]
    if "@" in target:
        username, _, domain = target.partition("@")
        for scheme in _webfinger_schemes(domain):
            url = f"{scheme}://{domain}/.well-known/webfinger"
            reason = await check_fetch_url(url)
            if reason is not None:
                logger.warning("WebFinger lookup %s refused: %s", url, reason)
                continue
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        url,
                        params={"resource": f"acct:{username}@{domain}"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for link in data.get("links", []):
                            if link.get("rel") == "self":
                                return link["href"]
            except Exception as exc:
                logger.warning(
                    "WebFinger resolution failed for %s via %s: %s",
                    target,
                    scheme,
                    exc,
                )
    return None
