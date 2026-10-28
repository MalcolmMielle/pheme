"""
JSON API routes — review CRUD and bootstrap for the frontend.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse

from app.activitypub.actor import actor_to_ap
from app.activitypub.delivery import fanout_activity
from app.activitypub.signing import generate_keypair
from app.auth import get_current_user
from app.db import (
    create_actor,
    create_review,
    get_actor_by_username,
    get_follower_inboxes,
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
) -> JSONResponse:
    """Return reviews, optionally filtered by map bounds."""
    if (
        min_lat is not None
        and max_lat is not None
        and min_lng is not None
        and max_lng is not None
    ):
        reviews = await get_reviews_by_bounds(min_lat, max_lat, min_lng, max_lng)
    else:
        reviews = await get_reviews(limit=200)
    return JSONResponse(reviews)


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
