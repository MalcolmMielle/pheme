"""
Inbox endpoint and activity handlers.

Receives activities from remote servers: Create (new review), Update (edited
review), Follow, Accept, Delete, and Undo.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.activitypub.actor import build_accept_activity
from app.activitypub.delivery import deliver_to_inbox
from app.activitypub.signing import parse_signature_header, verify_signature
from app.db import (
    accept_follow,
    follow_actor,
    get_actor_by_uri,
    unfollow_actor,
)
from app.places import places
from app.reviews import reviews
from app.routes.activitypub.helpers import (
    fetch_remote_actor,
    require_local_actor,
    sqlite_from_iso8601,
)

logger = logging.getLogger("pheme")

router = APIRouter()


@router.post("/actor/{username}/inbox")
async def post_inbox(username: str, request: Request) -> JSONResponse:
    """Receive an activity from a remote server."""
    actor = await require_local_actor(username)
    body = await request.body()

    sig_headers = {
        "host": request.headers.get("host", ""),
        "date": request.headers.get("date", ""),
        "digest": request.headers.get("digest", ""),
        "signature": request.headers.get("signature", ""),
    }

    sender_key_id = parse_signature_header(request.headers.get("signature", "")).get(
        "keyId", ""
    )
    sender_actor_uri = sender_key_id.split("#")[0] if sender_key_id else ""

    sender_actor = await get_actor_by_uri(sender_actor_uri)
    if not sender_actor and sender_actor_uri:
        logger.warning("Unknown sender actor %s — fetching remotely", sender_actor_uri)
        sender_actor = await fetch_remote_actor(sender_actor_uri)

    if not sender_actor:
        raise HTTPException(401, "Unknown sender")

    if not verify_signature(
        method="POST",
        path=request.url.path,
        headers=sig_headers,
        public_key_pem=sender_actor["public_key_pem"],
        body=body,
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
    elif activity_type == "Update":
        return await _handle_update(activity, sender_actor)
    elif activity_type == "Follow":
        return await _handle_follow(activity, actor, sender_actor)
    elif activity_type == "Accept":
        return await _handle_accept(activity, sender_actor)
    elif activity_type == "Delete":
        return await _handle_delete(activity, sender_actor)
    elif activity_type == "Undo":
        return await _handle_undo(activity, sender_actor)

    return JSONResponse({"status": "ok"})


def _invalid_note_reason(obj: dict[str, Any]) -> str | None:
    """Validate the Note fields of a federated Create activity.

    Returns a reason string when the object must be rejected. Without this,
    e.g. rating=99 trips the DB CHECK constraint and the insert silently
    fails while the inbox still reports "created".
    """
    for name in ("content", "placeName", "placeAddress"):
        if not isinstance(obj.get(name, ""), str):
            return f"{name} must be a string"
    rating = obj.get("rating", 3)
    if (
        isinstance(rating, bool)
        or not isinstance(rating, (int, float))
        or not float(rating).is_integer()
        or not 1 <= rating <= 5
    ):
        return "rating must be a whole number 1-5"
    for name, lo, hi in (("latitude", -90.0, 90.0), ("longitude", -180.0, 180.0)):
        value = obj.get(name, 0.0)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not lo <= value <= hi
        ):
            return f"{name} must be a number between {lo} and {hi}"
    return None


async def _handle_create(
    activity: dict[str, Any], sender_actor: dict[str, Any]
) -> JSONResponse:
    obj = activity.get("object", {})
    ap_id = obj.get("id", "")

    if not ap_id or await reviews.exists(ap_id):
        return JSONResponse({"status": "duplicate"})

    reason = _invalid_note_reason(obj)
    if reason is not None:
        logger.warning("Rejecting Create %s: %s", ap_id, reason)
        return JSONResponse({"status": "ignored", "reason": reason}, status_code=400)

    # One review per actor per place: ignore a second Create from the same
    # sender at the same coordinates (different ap_id, same place bucket).
    p = await places.at(
        float(obj.get("latitude", 0.0)), float(obj.get("longitude", 0.0))
    )
    if p.review_by(sender_actor["id"]) is not None:
        logger.info(
            "Ignoring Create %s — %s already reviewed this place",
            ap_id,
            sender_actor["actor_uri"],
        )
        return JSONResponse({"status": "duplicate"})

    # Attribute the review to the signature-verified sender — the object's
    # attributedTo is not trusted unless it is the sender itself.
    # Keep the object's published date (the original review date); fall
    # back to the local receipt time when it is missing or unparseable.
    published = obj.get("published", "")
    created_at = sqlite_from_iso8601(published) if isinstance(published, str) else None
    await reviews.create(
        actor_id=sender_actor["id"],
        ap_id=ap_id,
        content=obj.get("content", ""),
        rating=int(obj.get("rating", 3)),
        latitude=float(obj.get("latitude", 0.0)),
        longitude=float(obj.get("longitude", 0.0)),
        place_name=obj.get("placeName", ""),
        place_address=obj.get("placeAddress", ""),
        created_at=created_at,
    )

    logger.info("Stored federated review %s", ap_id)
    return JSONResponse({"status": "created"})


async def _handle_update(
    activity: dict[str, Any], sender_actor: dict[str, Any]
) -> JSONResponse:
    """Handle an Update activity — apply the author's edits to a review we
    already stored (matched by the Note's ap_id)."""
    obj = activity.get("object", {})
    ap_id = obj.get("id", "") if isinstance(obj, dict) else str(obj)
    if not ap_id:
        return JSONResponse({"status": "ignored", "reason": "no object id"})

    review = await reviews.by_ap_id(ap_id)
    if not review:
        return JSONResponse({"status": "not_found"})

    # Only apply the edit if the sender is the original author
    if review["actor_id"] != sender_actor["id"]:
        logger.warning(
            "Update for %s rejected — sender %s is not the author",
            ap_id,
            sender_actor["actor_uri"],
        )
        return JSONResponse({"status": "forbidden"}, status_code=403)

    if not isinstance(obj, dict):
        return JSONResponse({"status": "ignored", "reason": "object is not a Note"})
    reason = _invalid_note_reason(obj)
    if reason is not None:
        logger.warning("Rejecting Update %s: %s", ap_id, reason)
        return JSONResponse({"status": "ignored", "reason": reason}, status_code=400)

    await review.save(
        content=obj.get("content", ""),
        rating=int(obj.get("rating", 3)),
        latitude=float(obj.get("latitude", 0.0)),
        longitude=float(obj.get("longitude", 0.0)),
        place_name=obj.get("placeName", ""),
        place_address=obj.get("placeAddress", ""),
    )
    logger.info("Updated federated review %s (via Update activity)", ap_id)
    return JSONResponse({"status": "updated"})


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
    # object is the original Follow activity; its actor is the local actor
    # whose pending follow is being accepted.
    follower_uri = activity.get("object", {}).get("actor", "")
    follower = await get_actor_by_uri(follower_uri) if follower_uri else None
    if follower:
        await accept_follow(follower["id"], sender_actor["actor_uri"])
    return JSONResponse({"status": "ok"})


async def _handle_undo(
    activity: dict[str, Any], sender_actor: dict[str, Any]
) -> JSONResponse:
    """Handle an Undo activity — only Undo{Follow} is supported: the
    signature-verified sender stops following the Follow's target."""
    obj = activity.get("object", {})
    if isinstance(obj, dict) and obj.get("type") == "Follow":
        target_uri = obj.get("object")
        target_uri = (
            target_uri.get("id", "")
            if isinstance(target_uri, dict)
            else str(target_uri or "")
        )
        if target_uri:
            removed = await unfollow_actor(sender_actor["id"], target_uri)
            logger.info(
                "Undo Follow: %s unfollowed %s (removed=%s)",
                sender_actor["actor_uri"],
                target_uri,
                removed,
            )
    return JSONResponse({"status": "ok"})


async def _handle_delete(
    activity: dict[str, Any], sender_actor: dict[str, Any]
) -> JSONResponse:
    """Handle a Delete activity — remove the referenced review locally."""
    obj = activity.get("object", {})
    ap_id = obj.get("id", "") if isinstance(obj, dict) else str(obj)
    if not ap_id:
        return JSONResponse({"status": "ignored", "reason": "no object id"})

    review = await reviews.by_ap_id(ap_id)
    if not review:
        return JSONResponse({"status": "not_found"})

    # Only delete if the sender is the original author
    if review["actor_id"] != sender_actor["id"]:
        logger.warning(
            "Delete for %s rejected — sender %s is not the author",
            ap_id,
            sender_actor["actor_uri"],
        )
        return JSONResponse({"status": "forbidden"}, status_code=403)

    await review.delete()
    logger.info("Deleted federated review %s (via Delete activity)", ap_id)
    return JSONResponse({"status": "deleted"})
