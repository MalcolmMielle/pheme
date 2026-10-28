"""Follow relationship operations."""

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


async def get_followers(actor_id: int) -> list[str]:
    """Return actor URIs of actors that follow *this* actor."""
    actor = await get_actor_by_id(actor_id)
    if not actor:
        return []
    db = await get_db()
    rows = await db.execute(
        """SELECT a.actor_uri FROM follows f
           JOIN actors a ON f.actor_id = a.id
           WHERE f.target_actor_uri = ? AND f.is_accepted = 1""",
        (actor["actor_uri"],),
    )
    return [r["actor_uri"] for r in await rows.fetchall()]


async def get_follower_inboxes(actor_id: int) -> list[str]:
    """Return inbox URIs of actors that follow *this* actor (for federation fan-out)."""
    actor = await get_actor_by_id(actor_id)
    if not actor:
        return []
    db = await get_db()
    rows = await db.execute(
        """SELECT a.inbox_uri FROM follows f
           JOIN actors a ON f.actor_id = a.id
           WHERE f.target_actor_uri = ? AND f.is_accepted = 1""",
        (actor["actor_uri"],),
    )
    return [r["inbox_uri"] for r in await rows.fetchall()]


async def get_following(actor_id: int) -> list[str]:
    """Return actor URIs that *this* actor follows."""
    db = await get_db()
    rows = await db.execute(
        "SELECT target_actor_uri FROM follows WHERE actor_id = ? AND is_accepted = 1",
        (actor_id,),
    )
    return [r["target_actor_uri"] for r in await rows.fetchall()]
