"""
Async SQLite database layer.

We use aiosqlite so all DB access is non-blocking — important because
the same process handles both federation traffic and the web UI.

Schema
──────
  actors       — local users (plus cached remote actors after first contact)
  reviews      — every review (local + federated)
  follows      — follower/following relationships
"""

import os
from typing import Any

import aiosqlite

from app.config import config

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """Return (and lazily initialise) the shared database connection."""
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(config.database_path), exist_ok=True)
        _db = await aiosqlite.connect(config.database_path)
        _db.row_factory = aiosqlite.Row
        await _db.executescript(SCHEMA)
        await _db.commit()
    return _db


SCHEMA = """
CREATE TABLE IF NOT EXISTS actors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL DEFAULT '',
    summary         TEXT NOT NULL DEFAULT '',
    private_key_pem TEXT NOT NULL,
    public_key_pem  TEXT NOT NULL,
    actor_uri       TEXT NOT NULL UNIQUE,
    inbox_uri       TEXT NOT NULL,
    outbox_uri      TEXT NOT NULL,
    followers_uri   TEXT NOT NULL,
    following_uri   TEXT NOT NULL,
    is_local        INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id        INTEGER NOT NULL REFERENCES actors(id),
    -- ActivityPub id (URI) so we can deduplicate during federation
    ap_id           TEXT NOT NULL UNIQUE,
    content         TEXT NOT NULL DEFAULT '',
    rating          INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    place_name      TEXT NOT NULL DEFAULT '',
    place_address   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS follows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id        INTEGER NOT NULL REFERENCES actors(id),
    target_actor_uri TEXT NOT NULL,
    is_accepted     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(actor_id, target_actor_uri)
);

CREATE INDEX IF NOT EXISTS idx_reviews_lat_lng ON reviews(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_reviews_actor ON reviews(actor_id);
CREATE INDEX IF NOT EXISTS idx_follows_actor ON follows(actor_id);
"""


# ── actor helpers ───────────────────────────────────────────────────────


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
) -> dict[str, Any]:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO actors (username, display_name, summary,
           private_key_pem, public_key_pem, actor_uri,
           inbox_uri, outbox_uri, followers_uri, following_uri)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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


# ── review helpers ──────────────────────────────────────────────────────


async def create_review(
    actor_id: int,
    ap_id: str,
    content: str,
    rating: int,
    latitude: float,
    longitude: float,
    place_name: str = "",
    place_address: str = "",
) -> dict[str, Any]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO reviews (actor_id, ap_id, content, rating,
               latitude, longitude, place_name, place_address)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                actor_id,
                ap_id,
                content,
                rating,
                latitude,
                longitude,
                place_name,
                place_address,
            ),
        )
        await db.commit()
    except aiosqlite.IntegrityError:
        # Duplicate — already federated to us
        row = await db.execute("SELECT * FROM reviews WHERE ap_id = ?", (ap_id,))
        result = await row.fetchone()
        return dict(result) if result else {}
    row = await db.execute("SELECT * FROM reviews WHERE id = ?", (cursor.lastrowid,))
    return dict(await row.fetchone())  # type: ignore[arg-type]


async def review_exists(ap_id: str) -> bool:
    db = await get_db()
    row = await db.execute("SELECT 1 FROM reviews WHERE ap_id = ?", (ap_id,))
    return await row.fetchone() is not None


async def get_reviews(
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    db = await get_db()
    rows = await db.execute(
        """SELECT r.*, a.username, a.display_name, a.actor_uri
           FROM reviews r JOIN actors a ON r.actor_id = a.id
           ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    return [dict(r) for r in await rows.fetchall()]


async def get_reviews_by_bounds(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    limit: int = 200,
) -> list[dict[str, Any]]:
    db = await get_db()
    rows = await db.execute(
        """SELECT r.*, a.username, a.display_name, a.actor_uri
           FROM reviews r JOIN actors a ON r.actor_id = a.id
           WHERE r.latitude BETWEEN ? AND ?
             AND r.longitude BETWEEN ? AND ?
           ORDER BY r.created_at DESC LIMIT ?""",
        (min_lat, max_lat, min_lng, max_lng, limit),
    )
    return [dict(r) for r in await rows.fetchall()]


# ── follow helpers ──────────────────────────────────────────────────────


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
    db = await get_db()
    rows = await db.execute(
        "SELECT target_actor_uri FROM follows WHERE actor_id = ? AND is_accepted = 1",
        (actor_id,),
    )
    return [r["target_actor_uri"] for r in await rows.fetchall()]


async def get_following(actor_id: int) -> list[str]:
    """Return URIs of actors that follow *this* actor."""
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
