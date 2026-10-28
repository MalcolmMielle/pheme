"""
ActivityPub routes — WebFinger, Actor, Inbox, Outbox, Followers, Following.

These endpoints make this server a conforming ActivityPub implementation:
remote servers can discover our actors, fetch their keys, and deliver
activities to their inboxes.

Package layout:
  helpers      — URI builders, actor lookup, remote actor fetch
  webfinger    — /.well-known/webfinger
  actor        — /actor/{username}
  inbox        — /actor/{username}/inbox + activity handlers
  collections  — /inbox, /actor/{username}/outbox, /followers, /following
"""

from fastapi import APIRouter

from app.routes.activitypub.actor import router as actor_router
from app.routes.activitypub.collections import router as collections_router
from app.routes.activitypub.helpers import (
    actor_uri,
    fetch_remote_actor,
    inbox_uri,
    outbox_uri,
)
from app.routes.activitypub.inbox import router as inbox_router
from app.routes.activitypub.webfinger import router as webfinger_router

router = APIRouter()
router.include_router(webfinger_router)
router.include_router(actor_router)
router.include_router(inbox_router)
router.include_router(collections_router)

__all__ = [
    "router",
    "actor_uri",
    "inbox_uri",
    "outbox_uri",
    "fetch_remote_actor",
]
