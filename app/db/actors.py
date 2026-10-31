"""Actor CRUD operations and password helpers."""

from typing import Any

import bcrypt

from app.db.connection import get_db


async def create_actor(
    username: str,
    display_name: str,
    summary: str,
    private_key_pem: str,
    public_key_pem: str,
    actor_uri: str,
    inbox_uri: str,
    outbox_uri: str,
    followers_uri: str,
    following_uri: str,
    password_hash: str | None = None,
    is_admin: bool = False,
    is_local: bool = True,
) -> dict[str, Any]:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO actors (username, display_name, summary,
           private_key_pem, public_key_pem, actor_uri,
           inbox_uri, outbox_uri, followers_uri, following_uri,
           password_hash, is_admin, is_local)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            username,
            display_name,
            summary,
            private_key_pem,
            public_key_pem,
            actor_uri,
            inbox_uri,
            outbox_uri,
            followers_uri,
            following_uri,
            password_hash,
            1 if is_admin else 0,
            1 if is_local else 0,
        ),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM actors WHERE id = ?", (cursor.lastrowid,))
    return dict(await row.fetchone())  # type: ignore[arg-type]


async def get_actor_by_username(username: str) -> dict[str, Any] | None:
    db = await get_db()
    row = await db.execute(
        "SELECT * FROM actors WHERE username = ? AND is_local = 1", (username,)
    )
    result = await row.fetchone()
    return dict(result) if result else None


async def get_actor_by_uri(uri: str) -> dict[str, Any] | None:
    db = await get_db()
    row = await db.execute("SELECT * FROM actors WHERE actor_uri = ?", (uri,))
    result = await row.fetchone()
    return dict(result) if result else None


async def get_actor_by_id(actor_id: int) -> dict[str, Any] | None:
    db = await get_db()
    row = await db.execute("SELECT * FROM actors WHERE id = ?", (actor_id,))
    result = await row.fetchone()
    return dict(result) if result else None


async def list_local_actors() -> list[dict[str, Any]]:
    db = await get_db()
    rows = await db.execute("SELECT * FROM actors WHERE is_local = 1 ORDER BY username")
    return [dict(r) for r in await rows.fetchall()]


async def set_actor_admin(actor_id: int, is_admin: bool) -> bool:
    """Set an actor's admin flag. Returns False if the actor doesn't exist."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE actors SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, actor_id)
    )
    await db.commit()
    return cursor.rowcount > 0


async def delete_actor(actor_id: int) -> bool:
    """Delete an actor row. Returns False if the actor doesn't exist.

    Only safe for actors with no content (e.g. a just-registered account
    whose invite claim lost a race) — admin deletion of a user with
    reviews uses the cascade delete in ``app.db.reviews``/moderation.
    """
    db = await get_db()
    cursor = await db.execute("DELETE FROM actors WHERE id = ?", (actor_id,))
    await db.commit()
    return cursor.rowcount > 0


async def count_admins() -> int:
    """Number of local actors with the admin flag set."""
    db = await get_db()
    row = await db.execute(
        "SELECT COUNT(*) AS n FROM actors WHERE is_local = 1 AND is_admin = 1"
    )
    result = await row.fetchone()
    return int(result["n"]) if result else 0


# ── password helpers ───────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Check *password* against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())
