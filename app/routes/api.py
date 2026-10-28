"""
JSON API routes — review CRUD, follow, and bootstrap for the frontend.
"""

import logging
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse

from app.activitypub.actor import actor_to_ap, build_follow_activity
from app.activitypub.delivery import deliver_to_inbox, fanout_activity
from app.activitypub.signing import generate_keypair
from app.auth import get_current_user
from app.db import (
    count_reviews,
    create_actor,
    create_review,
    delete_review,
    follow_actor,
    get_actor_by_username,
    get_follower_inboxes,
    get_review_by_id,
    get_reviews,
    get_reviews_by_bounds,
    hash_password,
)
from app.routes.activitypub import actor_uri, inbox_uri, outbox_uri

logger = logging.getLogger("federated-reviews")

router = APIRouter()


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


@router.post("/api/reviews")
async def api_create_review(
    actor: dict = Depends(get_current_user),
    content: str = Form(...),
    rating: int = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    place_name: str = Form(""),
    place_address: str = Form(""),
) -> JSONResponse:
    """Create a new review and federate it to followers."""
    ap_id = f"{actor['actor_uri']}/review/{uuid.uuid4()}"
    review = await create_review(
        actor_id=actor["id"],
        ap_id=ap_id,
        content=content,
        rating=rating,
        latitude=latitude,
        longitude=longitude,
        place_name=place_name,
        place_address=place_address,
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
            "content": content,
            "latitude": latitude,
            "longitude": longitude,
            "rating": rating,
            "placeName": place_name,
            "placeAddress": place_address,
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
    from app.routes.activitypub import _fetch_remote_actor

    remote_actor = await _fetch_remote_actor(target_uri)
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

    priv, pub = generate_keypair()
    actor = await create_actor(
        username=username,
        display_name=display_name,
        summary="",
        private_key_pem=priv,
        public_key_pem=pub,
        actor_uri=actor_uri(username),
        inbox_uri=inbox_uri(username),
        outbox_uri=outbox_uri(username),
        followers_uri=f"{actor_uri(username)}/followers",
        following_uri=f"{actor_uri(username)}/following",
        password_hash=hash_password(password) if password else None,
    )
    return JSONResponse({"status": "created", "actor": actor_to_ap(actor).model_dump()})


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
