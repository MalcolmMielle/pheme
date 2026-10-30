"""
ActivityPub data models.

These Pydantic models represent the core ActivityStreams 2.0 objects used
for federation.  Every object has an `id` (its canonical URI), a `type`
(one of the ActivityStreams types), and optional standard properties.

Key ActivityPub concepts used here:

  Actor
    A user or server on the network.  Every actor has:
      - inbox   — where other servers POST activities *to* this actor
      - outbox  — where this actor's activities are published
      - followers / following — collections of actor URIs

  Review (extends Note)
    A piece of content with location metadata.  We use a Note with extra
    fields (latitude, longitude, rating, placeName) so it stays
    compatible with existing ActivityPub implementations.

  Create (Activity)
    Wraps a new Review.  When Alice creates a review, her server sends
    a `Create` activity whose `object` is the Review, to every follower's
    inbox.

  Follow / Accept
    Standard ActivityPub follow flow: server A sends Follow, server B
    replies with Accept (or Reject).

Federation flow in one picture:

  Alice@A creates review ─► stored in A's DB
       │
       ▼
  A looks up Alice's followers → [Bob@B, Carol@C]
       │
       ▼
  A signs a Create+Review with Alice's private key
       │
       ▼
  A POSTs to B's /actor/Bob/inbox   ─► B verifies signature, stores review
  A POSTs to C's /actor/Carol/inbox ─► C verifies signature, stores review
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ── helpers ────────────────────────────────────────────────────────────


def _now() -> str:
    """ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


# ── base ActivityStreams object ─────────────────────────────────────────


class ASObject(BaseModel):
    """Minimal ActivityStreams 2.0 object."""

    id: str
    type: str
    published: str = Field(default_factory=_now)


# ── Actor ───────────────────────────────────────────────────────────────


class Actor(ASObject):
    """An ActivityPub Actor (Person or Service)."""

    type: str = "Person"
    preferredUsername: str
    name: str = ""
    summary: str = ""
    inbox: str
    outbox: str
    followers: str
    following: str
    publicKey: dict[str, str] = Field(default_factory=dict)

    # Used internally — not serialised to JSON-ld.
    model_config = {"extra": "allow"}


# ── Activities ──────────────────────────────────────────────────────────


class Activity(ASObject):
    """Base Activity — relates an actor, an object, and (optionally) a target."""

    actor: str  # URI of the actor performing the activity
    object: dict[str, Any]  # the inner object (Review, etc.)
    to: list[str] = Field(default_factory=list)  # audience
    cc: list[str] = Field(default_factory=list)


class Follow(Activity):
    type: str = "Follow"


class Accept(Activity):
    type: str = "Accept"
