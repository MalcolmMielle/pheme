"""WebFinger endpoint (RFC 7033) — map acct:user@domain to actor URI."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.config import config
from app.db import get_actor_by_username

router = APIRouter()


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
