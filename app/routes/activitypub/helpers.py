"""
Shared helpers for ActivityPub routes — URI builders, actor lookup,
and remote actor fetching.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from app.activitypub.fetchguard import check_fetch_url
from app.activitypub.signing import generate_keypair
from app.config import config
from app.db import (
    count_admins,
    create_actor,
    get_actor_by_uri,
    get_actor_by_username,
    get_db,
)
from app.reviews import Review

logger = logging.getLogger("pheme")


def actor_uri(username: str) -> str:
    return f"{config.base_url}/actor/{username}"


def inbox_uri(username: str) -> str:
    return f"{actor_uri(username)}/inbox"


def outbox_uri(username: str) -> str:
    return f"{actor_uri(username)}/outbox"


# ── timestamps ──────────────────────────────────────────────────────────
#
# Reviews store their date as SQLite UTC text ("2026-08-02 21:45:00"),
# while ActivityPub `published` is ISO-8601 ("2026-08-02T21:45:00Z").
# These converters translate at the federation boundary.


def sqlite_to_datetime(value: str) -> datetime:
    """SQLite UTC text ("2026-08-02 21:45:00") -> aware UTC datetime."""
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def iso8601_from_sqlite(value: str) -> str:
    """SQLite UTC text -> ISO-8601 UTC ("2026-08-02 21:45:00" -> "...T21:45:00Z")."""
    return sqlite_to_datetime(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def sqlite_from_iso8601(value: str) -> str | None:
    """ISO-8601 timestamp -> SQLite UTC text, or None if unparseable.

    Naive timestamps are assumed UTC; anything else is converted to UTC.
    """
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def build_create_activity(actor: dict[str, Any], review: Review) -> dict[str, Any]:
    """Build the Create activity wrapping a review (Note) — used both when
    fanning out a new review to followers and when rendering the outbox."""
    ap_id = review["ap_id"]
    published = iso8601_from_sqlite(review["created_at"])
    return {
        "id": f"{ap_id}/activity",
        "type": "Create",
        "actor": actor["actor_uri"],
        "published": published,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [actor["followers_uri"]],
        "object": {
            "id": ap_id,
            "type": "Note",
            "attributedTo": actor["actor_uri"],
            "content": review["content"],
            "latitude": review["latitude"],
            "longitude": review["longitude"],
            "rating": review["rating"],
            "placeName": review["place_name"],
            "placeAddress": review["place_address"],
            "published": published,
        },
    }


def build_update_activity(actor: dict[str, Any], review: Review) -> dict[str, Any]:
    """Build the Update activity wrapping a review (Note) — fanned out to
    followers when the author edits their review. Same object shape as the
    Create (see build_create_activity), so remote servers can apply it the
    same way."""
    ap_id = review["ap_id"]
    published = iso8601_from_sqlite(review["created_at"])
    return {
        "id": f"{ap_id}/update",
        "type": "Update",
        "actor": actor["actor_uri"],
        "published": published,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [actor["followers_uri"]],
        "object": {
            "id": ap_id,
            "type": "Note",
            "attributedTo": actor["actor_uri"],
            "content": review["content"],
            "latitude": review["latitude"],
            "longitude": review["longitude"],
            "rating": review["rating"],
            "placeName": review["place_name"],
            "placeAddress": review["place_address"],
            "published": published,
        },
    }


def build_delete_activity(actor: dict[str, Any], review: Review) -> dict[str, Any]:
    """Build the Delete activity for a review — fanned out to followers when
    a review is deleted. ``actor`` must be the review's author: remote
    servers only accept a Delete for a review from its author."""
    ap_id = review["ap_id"]
    return {
        "id": f"{ap_id}/delete",
        "type": "Delete",
        "actor": actor["actor_uri"],
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [actor["followers_uri"]],
        "object": {
            "id": ap_id,
            "type": "Note",
        },
    }


async def create_local_actor(
    username: str,
    display_name: str,
    summary: str = "",
    password_hash: str | None = None,
    is_admin: bool | None = None,
) -> dict[str, Any]:
    """Create a local actor — generate its keypair and derive all URIs.

    is_admin=None (the default) applies the server rule: the first account
    created while no admin exists becomes the first admin account. Pass an
    explicit True/False to override (e.g. when an admin creates accounts).
    """
    if is_admin is None:
        is_admin = await count_admins() == 0
    priv, pub = generate_keypair()
    base = actor_uri(username)
    return await create_actor(
        username=username,
        display_name=display_name,
        summary=summary,
        private_key_pem=priv,
        public_key_pem=pub,
        actor_uri=base,
        inbox_uri=inbox_uri(username),
        outbox_uri=outbox_uri(username),
        followers_uri=f"{base}/followers",
        following_uri=f"{base}/following",
        password_hash=password_hash,
        is_admin=is_admin,
    )


async def require_local_actor(username: str) -> dict[str, Any]:
    """Return a local actor by username, or raise 404."""
    actor = await get_actor_by_username(username)
    if not actor:
        raise HTTPException(404, "Actor not found")
    return actor


async def fetch_remote_actor(uri: str) -> dict[str, Any] | None:
    """Fetch a remote actor document over HTTP, caching in the DB.

    The URI comes from user input (follow target) or an unverified inbox
    signature — refuse anything the SSRF guard rejects.
    """
    reason = await check_fetch_url(uri)
    if reason is not None:
        logger.warning("Refusing to fetch remote actor %s: %s", uri, reason)
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                uri,
                headers={"Accept": "application/activity+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                pub_key_data = data.get("publicKey", {})
                pub_key_pem = pub_key_data.get("publicKeyPem", "")

                db = await get_db()
                existing = await get_actor_by_uri(uri)
                if not existing:
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
                            uri,
                            data.get("inbox", ""),
                            data.get("outbox", ""),
                            data.get("followers", ""),
                            data.get("following", ""),
                        ),
                    )
                    await db.commit()
                return await get_actor_by_uri(uri)
        except Exception as exc:
            logger.warning("Failed to fetch remote actor %s: %s", uri, exc)
    return None
