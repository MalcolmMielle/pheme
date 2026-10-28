"""
ActivityPub routes — WebFinger, Actor, Inbox, Outbox, Followers, Following.

These endpoints make this server a conforming ActivityPub implementation:
remote servers can discover our actors, fetch their keys, and deliver
activities to their inboxes.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.activitypub.actor import actor_to_ap, build_accept_activity
from app.activitypub.signing import generate_keypair, verify_signature
from app.config import config
from app.db import (
    accept_follow,
    create_review,
    follow_actor,
    get_actor_by_uri,
    get_actor_by_username,
    get_followers,
    get_following,
    get_reviews,
    list_local_actors,
    review_exists,
)

logger = logging.getLogger("federated-reviews")

router = APIRouter()


# ── shared helpers ───────────────────────────────────────────────────────


def actor_uri(username: str) -> str:
    return f"{config.base_url}/actor/{username}"


def inbox_uri(username: str) -> str:
    return f"{actor_uri(username)}/inbox"


def outbox_uri(username: str) -> str:
    return f"{actor_uri(username)}/outbox"


async def _require_local_actor(username: str) -> dict[str, Any]:
    actor = await get_actor_by_username(username)
    if not actor:
        raise HTTPException(404, "Actor not found")
    return actor


# ── WebFinger ───────────────────────────────────────────────────────────


@router.get("/.well-known/webfinger")
async def webfinger(resource: str = "") -> JSONResponse:
    """WebFinger (RFC 7033) — map ``acct:user@domain`` → actor URI."""
    if not resource.startswith("acct:"):
        raise HTTPException(400, "Only acct: resources are supported")
    acct = resource[5:]
    username, _, domain = acct.partition("@")
    if domain and domain != config.domain:
        raise HTTPException(404, "Unknown domain")

    actor = await get_actor_by_username(username)
    if not actor:
        raise HTTPException(404, "User not found")

    return JSONResponse(
        {
            "subject": f"acct:{username}@{config.domain}",
            "links": [
                {
                    "rel": "self",
                    "type": "application/activity+json",
                    "href": actor["actor_uri"],
                }
            ],
        }
    )


# ── Actor ──────────────────────────────────────────────────────────────


@router.get("/actor/{username}")
async def get_actor(username: str) -> JSONResponse:
    """Return an ActivityPub Actor document (JSON-LD with publicKey)."""
    actor = await _require_local_actor(username)
    ap = actor_to_ap(actor)
    return JSONResponse(
        ap.model_dump(exclude_none=True),
        headers={"Content-Type": "application/activity+json"},
    )


# ── Inbox ──────────────────────────────────────────────────────────────


@router.post("/actor/{username}/inbox")
async def post_inbox(username: str, request: Request) -> JSONResponse:
    """Receive an activity from a remote server."""
    actor = await _require_local_actor(username)
    body = await request.body()

    sig_headers = {
        "host": request.headers.get("host", ""),
        "date": request.headers.get("date", ""),
        "digest": request.headers.get("digest", ""),
        "signature": request.headers.get("signature", ""),
    }

    signature = request.headers.get("signature", "")
    sender_key_id = ""
    for part in signature.split(","):
        part = part.strip()
        if part.startswith("keyId="):
            sender_key_id = part.split("=", 1)[1].strip().strip('"')

    sender_actor_uri = sender_key_id.split("#")[0] if sender_key_id else ""

    sender_actor = await get_actor_by_uri(sender_actor_uri)
    if not sender_actor and sender_actor_uri:
        logger.warning("Unknown sender actor %s — fetching remotely", sender_actor_uri)
        sender_actor = await _fetch_remote_actor(sender_actor_uri)

    if not sender_actor:
        raise HTTPException(401, "Unknown sender")

    if not verify_signature(
        method="POST",
        path=request.url.path,
        headers=sig_headers,
        public_key_pem=sender_actor["public_key_pem"],
    ):
        raise HTTPException(401, "Invalid signature")

    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON") from None

    activity_type = activity.get("type", "")
    logger.info("Inbox for %s received %s", username, activity_type)

    if activity_type == "Create":
        return await _handle_create(activity, sender_actor)
    elif activity_type == "Follow":
        return await _handle_follow(activity, actor, sender_actor)
    elif activity_type == "Accept":
        return await _handle_accept(activity, sender_actor)
    elif activity_type == "Undo":
        return JSONResponse({"status": "ok"})

    return JSONResponse({"status": "ok"})


async def _handle_create(
    activity: dict[str, Any], sender_actor: dict[str, Any]
) -> JSONResponse:
    obj = activity.get("object", {})
    ap_id = obj.get("id", "")

    if not ap_id or await review_exists(ap_id):
        return JSONResponse({"status": "duplicate"})

    actor_uri_val = obj.get("attributedTo", sender_actor["actor_uri"])
    local_actor = await get_actor_by_uri(actor_uri_val)
    if not local_actor:
        local_actor = sender_actor
    elif local_actor["actor_uri"] != sender_actor["actor_uri"]:
        local_actor = sender_actor

    await create_review(
        actor_id=local_actor["id"],
        ap_id=ap_id,
        content=obj.get("content", ""),
        rating=obj.get("rating", 3),
        latitude=obj.get("latitude", 0.0),
        longitude=obj.get("longitude", 0.0),
        place_name=obj.get("placeName", ""),
        place_address=obj.get("placeAddress", ""),
    )

    logger.info("Stored federated review %s", ap_id)
    return JSONResponse({"status": "created"})


async def _handle_follow(
    activity: dict[str, Any], target_actor: dict[str, Any], sender_actor: dict[str, Any]
) -> JSONResponse:
    follower_uri = activity.get("actor", "")
    if not follower_uri:
        raise HTTPException(400, "Missing actor in Follow")

    await follow_actor(sender_actor["id"], target_actor["actor_uri"])
    await accept_follow(sender_actor["id"], target_actor["actor_uri"])

    accept = build_accept_activity(target_actor["actor_uri"], activity)
    follower_actor = await get_actor_by_uri(follower_uri)
    if follower_actor:
        from app.activitypub.delivery import deliver_to_inbox

        await deliver_to_inbox(
            follower_actor["inbox_uri"],
            accept.model_dump(exclude_none=True),
            f"{target_actor['actor_uri']}#main-key",
            target_actor["private_key_pem"],
        )

    return JSONResponse(accept.model_dump(exclude_none=True))


async def _handle_accept(
    activity: dict[str, Any], sender_actor: dict[str, Any]
) -> JSONResponse:
    obj = activity.get("object", {})
    follow_actor_uri = obj.get("actor", "")
    if follow_actor_uri:
        local_actors = await list_local_actors()
        for la in local_actors:
            await accept_follow(la["id"], sender_actor["actor_uri"])
    return JSONResponse({"status": "ok"})


# ── Shared inbox ───────────────────────────────────────────────────────


@router.post("/inbox")
async def shared_inbox(request: Request) -> JSONResponse:
    """Shared inbox — delegates to the first local actor's inbox."""
    actors = await list_local_actors()
    if not actors:
        raise HTTPException(404, "No local actors")
    return await post_inbox(actors[0]["username"], request)


# ── Outbox ─────────────────────────────────────────────────────────────


@router.get("/actor/{username}/outbox")
async def get_outbox(username: str) -> JSONResponse:
    """Return an actor's outbox (published activities)."""
    actor = await _require_local_actor(username)
    reviews = await get_reviews(limit=50)
    items: list[dict[str, Any]] = []
    for r in reviews:
        items.append(
            {
                "id": r["ap_id"],
                "type": "Create",
                "actor": actor["actor_uri"],
                "published": r["created_at"],
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


# ── Followers / Following ──────────────────────────────────────────────


@router.get("/actor/{username}/followers")
async def get_followers_collection(username: str) -> JSONResponse:
    actor = await _require_local_actor(username)
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
    actor = await _require_local_actor(username)
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


# ── Remote actor fetch ─────────────────────────────────────────────────


async def _fetch_remote_actor(actor_uri: str) -> dict[str, Any] | None:
    """Fetch a remote actor document over HTTP, caching in the DB."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                actor_uri,
                headers={"Accept": "application/activity+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                pub_key_data = data.get("publicKey", {})
                pub_key_pem = pub_key_data.get("publicKeyPem", "")

                from app.db import get_db

                db = await get_db()
                existing = await get_actor_by_uri(actor_uri)
                if not existing:
                    _priv, _pub = generate_keypair()
                    await db.execute(
                        """INSERT OR REPLACE INTO actors
                           (username, display_name, summary,
                            private_key_pem, public_key_pem,
                            actor_uri, inbox_uri, outbox_uri,
                            followers_uri, following_uri, is_local)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (
                            data.get("preferredUsername", "remote"),
                            data.get("name", ""),
                            data.get("summary", ""),
                            "",
                            pub_key_pem,
                            actor_uri,
                            data.get("inbox", ""),
                            data.get("outbox", ""),
                            data.get("followers", ""),
                            data.get("following", ""),
                        ),
                    )
                    await db.commit()
                return await get_actor_by_uri(actor_uri)
        except Exception as exc:
            logger.warning("Failed to fetch remote actor %s: %s", actor_uri, exc)
    return None
