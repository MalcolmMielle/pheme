"""
JSON API routes — review CRUD, /api/me, and bootstrap.

Place identity and geocoding (the Nominatim proxy) live in app/places.py
(the ``place`` singleton); follow/unfollow in routes/follow.py; admin
endpoints (accounts, invite codes) in routes/admin.py. The WebFinger
resolution helpers at the bottom are shared with routes/follow.py.
"""

import ipaddress
import logging
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
    get_actor_by_id,
    get_actor_by_username,
    get_follower_inboxes,
    get_following,
    get_following_actors,
    hash_password,
    list_local_actors,
)
from app.config import config
from app.places import AlreadyReviewed, places
from app.ratelimit import limiter
from app.reviews import reviews
from app.routes.activitypub import create_local_actor
from app.routes.activitypub.helpers import (
    build_create_activity,
    build_update_activity,
)

logger = logging.getLogger("pheme")

router = APIRouter()


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
    """Public server metadata for the SPA (registration mode, place bucket
    precision, etc.)."""
    return JSONResponse(
        {
            "registration_mode": config.registration_mode,
            "place_decimals": config.place_decimals,
        }
    )


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
    return await places.nominatim_get(
        "/search",
        {"q": q, "format": "json", "limit": limit, "addressdetails": 1},
    )


@router.get("/api/reverse-geocode")
async def api_reverse_geocode(lat: float, lon: float) -> JSONResponse:
    """Proxy a reverse geocode lookup to Nominatim."""
    return await places.nominatim_get(
        "/reverse", {"lat": lat, "lon": lon, "format": "json"}
    )


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
        found = await reviews.by_bounds(
            min_lat,
            max_lat,
            min_lng,
            max_lng,
            limit=limit,
            offset=offset,
            actor_uris=actor_uris,
        )
        total = await reviews.count_by_bounds(
            min_lat, max_lat, min_lng, max_lng, actor_uris=actor_uris
        )
    else:
        found = await reviews.all(limit=limit, offset=offset, actor_uris=actor_uris)
        total = await reviews.count(actor_uris=actor_uris)
    return JSONResponse(
        [r.to_dict() for r in found],
        headers={"X-Total-Count": str(total)},
    )


@router.get("/api/reviews/{review_id}")
async def api_get_review(review_id: int) -> JSONResponse:
    """Return a single review by ID."""
    review = await reviews.by_id(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    return JSONResponse(review.to_dict())


class CreateReviewPayload(BaseModel):
    """Payload for POST /api/reviews and PUT /api/reviews/{id} — JSON body or
    form fields."""

    content: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
    latitude: float
    longitude: float
    place_name: str = ""
    place_address: str = ""


async def _parse_review_payload(request: Request) -> CreateReviewPayload | JSONResponse:
    """Read the request body as JSON or form fields and validate it against
    CreateReviewPayload. Returns the payload, or a 422 JSONResponse."""
    content_type = request.headers.get("content-type", "")
    raw: Any
    if "application/json" in content_type:
        raw = await request.json()
    else:
        form = await request.form()
        # Keep plain text fields only (multipart uploads are not review data)
        raw = {k: v for k, v in form.items() if isinstance(v, str)}

    try:
        return CreateReviewPayload.model_validate(raw)
    except ValidationError:
        return JSONResponse(
            {"detail": "Required: content, rating (1-5), latitude, longitude"},
            status_code=422,
        )


@router.post("/api/reviews")
async def api_create_review(
    request: Request,
    actor: dict = Depends(get_current_user),
) -> JSONResponse:
    """Create a new review and federate it to followers.

    Accepts both form-encoded bodies (browser forms, curl) and JSON bodies
    (the React SPA and future native clients); both are validated against
    CreateReviewPayload. One review per actor per place: a second review at
    the same place returns 409 with the existing review's ID.
    """
    parsed = await _parse_review_payload(request)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = parsed

    # Materialize the place object for the clicked coordinates (loaded with
    # its reviews from the DB) and add the review on it — one review per
    # actor per place is enforced there (AlreadyReviewed → 409).
    p = await places.at(payload.latitude, payload.longitude)
    try:
        review = await p.add_review(
            actor,
            content=payload.content,
            rating=payload.rating,
            place_name=payload.place_name,
            place_address=payload.place_address,
        )
    except AlreadyReviewed as exc:
        return JSONResponse(
            {
                "detail": "You already reviewed this place — edit your review instead.",
                "review_id": exc.review["id"],
            },
            status_code=409,
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
        review["ap_id"],
        len(follower_inboxes),
        result["ok"],
        result["fail"],
    )

    return JSONResponse(
        {"status": "ok", "review": review.to_dict(), "federation": result}
    )


@router.put("/api/reviews/{review_id}")
async def api_update_review(
    review_id: int,
    request: Request,
    actor: dict = Depends(get_current_user),
) -> JSONResponse:
    """Update a review and federate an Update activity to followers.

    Only the author can edit their own review. The body is the same shape as
    POST /api/reviews (validated against CreateReviewPayload).
    """
    review = await reviews.by_id(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    if review["actor_id"] != actor["id"]:
        raise HTTPException(403, "You can only edit your own reviews")

    parsed = await _parse_review_payload(request)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = parsed

    # Edit through the place object for the target coordinates — the edit
    # must not move the review onto a place where the author already has a
    # different review (one review per actor per place still holds).
    p = await places.at(payload.latitude, payload.longitude)
    at_place = p.review_by(actor["id"])
    if at_place is not None and at_place["id"] != review_id:
        return JSONResponse(
            {
                "detail": "You already have a review at that place.",
                "review_id": at_place["id"],
            },
            status_code=409,
        )

    updated = await p.update_review(
        review_id,
        content=payload.content,
        rating=payload.rating,
        place_name=payload.place_name,
        place_address=payload.place_address,
    )
    if not updated:
        raise HTTPException(404, "Review not found")

    activity = build_update_activity(actor, updated)
    follower_inboxes = await get_follower_inboxes(actor["id"])
    result = await fanout_activity(
        activity,
        f"{actor['actor_uri']}#main-key",
        actor["private_key_pem"],
        follower_inboxes,
    )

    logger.info(
        "Updated review %s — federated to %d followers (%d ok, %d fail)",
        review["ap_id"],
        len(follower_inboxes),
        result["ok"],
        result["fail"],
    )

    return JSONResponse(
        {"status": "ok", "review": updated.to_dict(), "federation": result}
    )


@router.delete("/api/reviews/{review_id}")
async def api_delete_review(
    review_id: int,
    actor: dict = Depends(get_current_user),
) -> JSONResponse:
    """Delete a review. Only the author can delete their own reviews."""
    review = await reviews.by_id(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    if review["actor_id"] != actor["id"]:
        raise HTTPException(403, "You can only delete your own reviews")

    deleted = await review.delete()
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
