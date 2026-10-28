"""Actor CRUD operations and password helpers."""

from typing import Any

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
) -> dict[str, Any]:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO actors (username, display_name, summary,
           private_key_pem, public_key_pem, actor_uri,
           inbox_uri, outbox_uri, followers_uri, following_uri,
           password_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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


# ── password helpers ───────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Check *password* against a bcrypt hash."""
    import bcrypt

    return bcrypt.checkpw(password.encode(), password_hash.encode())
