"""Follow/unfollow API — signed Follow/Undo activities to remote actors.

The acct/URI resolution helpers (_webfinger_schemes, _resolve_actor_uri)
stay in routes/api.py and are imported from there.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse

from app.activitypub.actor import build_follow_activity
from app.activitypub.delivery import deliver_to_inbox
from app.auth import get_current_user
from app.db import follow_actor, get_actor_by_uri, unfollow_actor
from app.routes.activitypub import fetch_remote_actor
from app.routes.api import _resolve_actor_uri

logger = logging.getLogger("pheme")

router = APIRouter()


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


@router.post("/api/unfollow")
async def api_unfollow(
    actor: dict = Depends(get_current_user),
    target: str = Form(...),
) -> JSONResponse:
    """Unfollow an actor by URI or acct (user@domain).

    Removes the local follow relationship and sends a signed Undo activity
    wrapping the original Follow to the remote actor's inbox, so the remote
    server drops this actor from its followers too.
    """
    target_uri = await _resolve_actor_uri(target)
    if not target_uri:
        raise HTTPException(400, f"Could not resolve actor: {target}")

    removed = await unfollow_actor(actor["id"], target_uri)

    # Notify the remote server (best effort — no retry in MVP).
    delivered = False
    remote_actor = await get_actor_by_uri(target_uri)
    if remote_actor and remote_actor.get("inbox_uri"):
        undo = {
            "id": f"{actor['actor_uri']}/undo/{uuid.uuid4()}",
            "type": "Undo",
            "actor": actor["actor_uri"],
            "to": [target_uri],
            "object": build_follow_activity(actor["actor_uri"], target_uri).model_dump(
                exclude_none=True
            ),
        }
        delivered = await deliver_to_inbox(
            remote_actor["inbox_uri"],
            undo,
            f"{actor['actor_uri']}#main-key",
            actor["private_key_pem"],
        )

    logger.info(
        "Unfollow %s → %s (removed=%s, delivered=%s)",
        actor["username"],
        target_uri,
        removed,
        delivered,
    )
    return JSONResponse(
        {
            "status": "unfollowed",
            "target": target_uri,
            "was_following": removed,
            "delivered": delivered,
        }
    )
