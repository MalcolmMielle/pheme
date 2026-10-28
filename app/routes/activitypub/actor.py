"""Actor endpoint — return an ActivityPub Actor document (JSON-LD)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.activitypub.actor import actor_to_ap
from app.routes.activitypub.helpers import require_local_actor

router = APIRouter()


@router.get("/actor/{username}")
async def get_actor(username: str) -> JSONResponse:
    """Return an ActivityPub Actor document (JSON-LD with publicKey)."""
    actor = await require_local_actor(username)
    ap = actor_to_ap(actor)
    return JSONResponse(
        ap.model_dump(exclude_none=True),
        headers={"Content-Type": "application/activity+json"},
    )
