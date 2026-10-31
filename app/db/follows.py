"""Follow relationship operations."""

from typing import Any

from app.db.actors import get_actor_by_id
from app.db.connection import get_db


async def follow_actor(actor_id: int, target_actor_uri: str) -> None:
    db = await get_db()
    await db.execute(
        """INSERT OR IGNORE INTO follows (actor_id, target_actor_uri, is_accepted)
           VALUES (?, ?, 0)""",
        (actor_id, target_actor_uri),
    )
    await db.commit()


async def accept_follow(actor_id: int, target_actor_uri: str) -> None:
    db = await get_db()
    await db.execute(
        """UPDATE follows SET is_accepted = 1
           WHERE actor_id = ? AND target_actor_uri = ?""",
        (actor_id, target_actor_uri),
    )
    await db.commit()


async def unfollow_actor(actor_id: int, target_actor_uri: str) -> bool:
    """Remove a follow relationship. Returns True if a row was deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM follows WHERE actor_id = ? AND target_actor_uri = ?",
        (actor_id, target_actor_uri),
    )
    await db.commit()
    return cursor.rowcount > 0


async def _follower_actors(actor_id: int) -> list[dict[str, Any]]:
    """Accepted followers of *this* actor, joined with their actor rows."""
    actor = await get_actor_by_id(actor_id)
    if not actor:
        return []
    db = await get_db()
    rows = await db.execute(
        """SELECT a.* FROM follows f
           JOIN actors a ON f.actor_id = a.id
           WHERE f.target_actor_uri = ? AND f.is_accepted = 1""",
        (actor["actor_uri"],),
    )
    return [dict(r) for r in await rows.fetchall()]


async def get_followers(actor_id: int) -> list[str]:
    """Return actor URIs of actors that follow *this* actor."""
    return [a["actor_uri"] for a in await _follower_actors(actor_id)]


async def get_follower_inboxes(actor_id: int) -> list[str]:
    """Return inbox URIs of actors that follow *this* actor (for federation fan-out)."""
    return [a["inbox_uri"] for a in await _follower_actors(actor_id)]


async def get_following(actor_id: int) -> list[str]:
    """Return actor URIs that *this* actor follows."""
    db = await get_db()
    rows = await db.execute(
        "SELECT target_actor_uri FROM follows WHERE actor_id = ? AND is_accepted = 1",
        (actor_id,),
    )
    return [r["target_actor_uri"] for r in await rows.fetchall()]


async def get_following_actors(actor_id: int) -> list[dict[str, Any]]:
    """Accepted follows of *this* actor, joined with the cached actor rows.

    Returns ``[{actor_uri, username, display_name}]``. username/display_name
    come from the cached actor row when there is one; otherwise the username
    falls back to the actor URI's last path segment.
    """
    db = await get_db()
    rows = await db.execute(
        """SELECT f.target_actor_uri AS actor_uri, a.username, a.display_name
           FROM follows f
           LEFT JOIN actors a ON a.actor_uri = f.target_actor_uri
           WHERE f.actor_id = ? AND f.is_accepted = 1
           ORDER BY f.created_at""",
        (actor_id,),
    )
    result: list[dict[str, Any]] = []
    for r in await rows.fetchall():
        username = r["username"]
        if username is None:
            username = r["actor_uri"].rstrip("/").rsplit("/", 1)[-1]
        result.append(
            {
                "actor_uri": r["actor_uri"],
                "username": username,
                "display_name": r["display_name"] or "",
            }
        )
    return result
