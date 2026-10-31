"""
Collection endpoints — Outbox, Followers, Following, and Shared Inbox.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.db import (
    get_followers,
    get_following,
    get_reviews_by_actor,
    list_local_actors,
)
from app.routes.activitypub.helpers import (
    iso8601_from_sqlite,
    outbox_uri,
    require_local_actor,
)
from app.routes.activitypub.inbox import post_inbox

router = APIRouter()


@router.post("/inbox")
async def shared_inbox(request: Request) -> JSONResponse:
    """Shared inbox — delegates to the first local actor's inbox."""
    actors = await list_local_actors()
    if not actors:
        raise HTTPException(404, "No local actors")
    return await post_inbox(actors[0]["username"], request)


@router.get("/actor/{username}/outbox")
async def get_outbox(username: str) -> JSONResponse:
    """Return an actor's outbox (published activities)."""
    actor = await require_local_actor(username)
    reviews = await get_reviews_by_actor(actor["id"], limit=50)
    items: list[dict[str, Any]] = []
    for r in reviews:
        published = iso8601_from_sqlite(r["created_at"])
        items.append(
            {
                "id": r["ap_id"],
                "type": "Create",
                "actor": actor["actor_uri"],
                "published": published,
                "object": {
                    "id": r["ap_id"],
                    "type": "Note",
                    "attributedTo": actor["actor_uri"],
                    "content": r["content"],
                    "latitude": r["latitude"],
                    "longitude": r["longitude"],
                    "rating": r["rating"],
                    "placeName": r["place_name"],
                    "placeAddress": r["place_address"],
                    "published": published,
                },
            }
        )
    return JSONResponse(
        {
            "id": outbox_uri(username),
            "type": "OrderedCollection",
            "totalItems": len(items),
            "orderedItems": items,
        },
        headers={"Content-Type": "application/activity+json"},
    )


@router.get("/actor/{username}/followers")
async def get_followers_collection(username: str) -> JSONResponse:
    actor = await require_local_actor(username)
    followers = await get_followers(actor["id"])
    return JSONResponse(
        {
            "id": actor["followers_uri"],
            "type": "OrderedCollection",
            "totalItems": len(followers),
            "orderedItems": followers,
        },
        headers={"Content-Type": "application/activity+json"},
    )


@router.get("/actor/{username}/following")
async def get_following_collection(username: str) -> JSONResponse:
    actor = await require_local_actor(username)
    following = await get_following(actor["id"])
    return JSONResponse(
        {
            "id": actor["following_uri"],
            "type": "OrderedCollection",
            "totalItems": len(following),
            "orderedItems": following,
        },
        headers={"Content-Type": "application/activity+json"},
    )
