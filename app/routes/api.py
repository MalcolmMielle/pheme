"""
JSON API routes — review CRUD, follow, and bootstrap for the frontend.
"""

import asyncio
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.activitypub.actor import actor_to_ap, build_follow_activity
from app.activitypub.delivery import deliver_to_inbox, fanout_activity
from app.auth import get_current_admin, get_current_user
from app.db import (
    count_admins,
    count_reviews,
    count_reviews_by_bounds,
    create_review,
    delete_review,
    follow_actor,
    get_actor_by_id,
    get_actor_by_username,
    get_follower_inboxes,
    get_review_by_id,
    get_reviews,
    get_reviews_by_bounds,
    hash_password,
    list_local_actors,
    set_actor_admin,
)
from app.config import config
from app.routes.activitypub import create_local_actor, fetch_remote_actor

logger = logging.getLogger("federated-reviews")

router = APIRouter()

_NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
_NOMINATIM_HEADERS = {
    "User-Agent": f"FederatedReviews/0.1 ({config.base_url})",
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

    Also returns the session's CSRF token so the SPA can include it in
    form-encoded posts (e.g. logout) — JSON requests are CSRF-exempt.
    """
    user_id = request.session.get("user_id")
    if user_id is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    actor = await get_actor_by_id(user_id)
    if actor is None:
        request.session.clear()
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return JSONResponse(
        {
            "id": actor["id"],
            "username": actor["username"],
            "display_name": actor["display_name"],
            "is_admin": bool(actor.get("is_admin")),
            "csrf_token": request.session.get("csrf_token", ""),
        }
    )


@router.get("/api/geocode")
async def api_geocode(q: str, limit: int = 5) -> JSONResponse:
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
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lng: float | None = None,
    max_lng: float | None = None,
    limit: int = 200,
    offset: int = 0,
) -> JSONResponse:
    """Return reviews, optionally filtered by map bounds. Supports pagination."""
    if (
        min_lat is not None
        and max_lat is not None
        and min_lng is not None
        and max_lng is not None
    ):
        reviews = await get_reviews_by_bounds(
            min_lat, max_lat, min_lng, max_lng, limit=limit, offset=offset
        )
        total = await count_reviews_by_bounds(min_lat, max_lat, min_lng, max_lng)
    else:
        reviews = await get_reviews(limit=limit, offset=offset)
        total = await count_reviews()
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

    activity = {
        "id": f"{ap_id}/activity",
        "type": "Create",
        "actor": actor["actor_uri"],
        "published": review["created_at"],
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [actor["followers_uri"]],
        "object": {
            "id": ap_id,
            "type": "Note",
            "attributedTo": actor["actor_uri"],
            "content": payload.content,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "rating": payload.rating,
            "placeName": payload.place_name,
            "placeAddress": payload.place_address,
            "published": review["created_at"],
        },
    }

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


@router.post("/api/follow")
async def api_follow(
    actor: dict = Depends(get_current_user),
    target: str = Form(...),
) -> JSONResponse:
    """Follow a remote actor by URI or acct (user@domain).

    Sends a signed Follow activity to the remote actor's inbox.
    The follow is stored locally as pending until the remote server
    sends back an Accept activity.
    """
    target_uri = await _resolve_actor_uri(target)
    if not target_uri:
        raise HTTPException(400, f"Could not resolve actor: {target}")

    if target_uri == actor["actor_uri"]:
        raise HTTPException(400, "Cannot follow yourself")

    # Fetch and cache the remote actor
    remote_actor = await fetch_remote_actor(target_uri)
    if not remote_actor:
        raise HTTPException(400, f"Could not fetch remote actor: {target_uri}")

    # Store follow relationship locally (pending)
    await follow_actor(actor["id"], target_uri)

    # Send Follow activity to the remote inbox
    follow = build_follow_activity(actor["actor_uri"], target_uri)
    delivered = await deliver_to_inbox(
        remote_actor["inbox_uri"],
        follow.model_dump(exclude_none=True),
        f"{actor['actor_uri']}#main-key",
        actor["private_key_pem"],
    )

    logger.info(
        "Follow %s → %s (delivered=%s)", actor["username"], target_uri, delivered
    )
    return JSONResponse(
        {
            "status": "follow_sent",
            "target": target_uri,
            "delivered": delivered,
        }
    )


@router.post("/api/bootstrap")
async def api_bootstrap(
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

    # No explicit is_admin: the first account created on the server
    # automatically becomes the first admin (see create_local_actor).
    actor = await create_local_actor(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password) if password else None,
    )
    return JSONResponse({"status": "created", "actor": actor_to_ap(actor).model_dump()})


# ── admin endpoints ─────────────────────────────────────────────────────


def _public_user(actor: dict[str, Any]) -> dict[str, Any]:
    """Actor row reduced to the fields the admin UI needs (no keys/hashes)."""
    return {
        "id": actor["id"],
        "username": actor["username"],
        "display_name": actor["display_name"],
        "is_admin": bool(actor.get("is_admin")),
        "created_at": actor["created_at"],
    }


@router.get("/api/admin/users")
async def api_admin_list_users(
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """List all local accounts with their admin flag (admin only)."""
    users = [_public_user(a) for a in await list_local_actors()]
    return JSONResponse({"users": users, "admin_count": await count_admins()})


@router.post("/api/admin/users")
async def api_admin_create_user(
    admin: dict = Depends(get_current_admin),
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    is_admin: bool = Form(False),
) -> JSONResponse:
    """Create a new local account, optionally as an admin (admin only)."""
    existing = await get_actor_by_username(username)
    if existing:
        raise HTTPException(409, "Username already taken")

    actor = await create_local_actor(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        is_admin=is_admin,
    )
    logger.info(
        "Admin '%s' created account '%s' (is_admin=%s)",
        admin["username"],
        username,
        is_admin,
    )
    return JSONResponse({"status": "created", "user": _public_user(actor)})


@router.post("/api/admin/users/{user_id}/promote")
async def api_admin_promote(
    user_id: int,
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Grant admin to a local account (admin only)."""
    target = await get_actor_by_id(user_id)
    if not target or not target.get("is_local"):
        raise HTTPException(404, "User not found")
    await set_actor_admin(user_id, True)
    logger.info(
        "Admin '%s' promoted '%s' to admin", admin["username"], target["username"]
    )
    promoted = target | {"is_admin": 1}
    return JSONResponse({"status": "promoted", "user": _public_user(promoted)})


@router.post("/api/admin/users/{user_id}/demote")
async def api_admin_demote(
    user_id: int,
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Revoke admin from a local account (admin only).

    An admin cannot demote themselves — that would risk locking the
    server out of admin access entirely.
    """
    if user_id == admin["id"]:
        raise HTTPException(403, "You cannot demote yourself")
    target = await get_actor_by_id(user_id)
    if not target or not target.get("is_local"):
        raise HTTPException(404, "User not found")
    await set_actor_admin(user_id, False)
    logger.info("Admin '%s' demoted '%s'", admin["username"], target["username"])
    demoted = target | {"is_admin": 0}
    return JSONResponse({"status": "demoted", "user": _public_user(demoted)})


# ── helpers ─────────────────────────────────────────────────────────────


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
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://{domain}/.well-known/webfinger",
                    params={"resource": f"acct:{username}@{domain}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for link in data.get("links", []):
                        if link.get("rel") == "self":
                            return link["href"]
        except Exception as exc:
            logger.warning("WebFinger resolution failed for %s: %s", target, exc)
    return None
