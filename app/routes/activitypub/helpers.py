"""
Shared helpers for ActivityPub routes — URI builders, actor lookup,
and remote actor fetching.
"""

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from app.activitypub.signing import generate_keypair
from app.config import config
from app.db import get_actor_by_uri, get_actor_by_username, get_db

logger = logging.getLogger("federated-reviews")


def actor_uri(username: str) -> str:
    return f"{config.base_url}/actor/{username}"


def inbox_uri(username: str) -> str:
    return f"{actor_uri(username)}/inbox"


def outbox_uri(username: str) -> str:
    return f"{actor_uri(username)}/outbox"


async def require_local_actor(username: str) -> dict[str, Any]:
    """Return a local actor by username, or raise 404."""
    actor = await get_actor_by_username(username)
    if not actor:
        raise HTTPException(404, "Actor not found")
    return actor


async def fetch_remote_actor(uri: str) -> dict[str, Any] | None:
    """Fetch a remote actor document over HTTP, caching in the DB."""
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
