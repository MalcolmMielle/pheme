"""
Database connection management and schema.

We use aiosqlite so all DB access is non-blocking — important because
the same process handles both federation traffic and the web UI.

Lifecycle: the FastAPI lifespan (app.main) calls init_db() at startup and
close_db() at shutdown. get_db() still lazily initialises so standalone
scripts (bootstrap) work without starting the app.

Schema
──────
  actors       — local users (plus cached remote actors after first contact)
  reviews      — every review (local + federated)
  follows      — follower/following relationships
"""

import os

import aiosqlite

from app.config import config

_db: aiosqlite.Connection | None = None


async def init_db() -> aiosqlite.Connection:
    """Open the shared connection, apply pragmas, schema and migrations.

    Idempotent — returns the existing connection if already open.
    """
    global _db
    if _db is not None:
        return _db
    os.makedirs(os.path.dirname(config.database_path), exist_ok=True)
    _db = await aiosqlite.connect(config.database_path)
    _db.row_factory = aiosqlite.Row
    # Enable foreign key enforcement (SQLite defaults to OFF)
    await _db.execute("PRAGMA foreign_keys = ON")
    # WAL mode for better concurrent read/write performance
    await _db.execute("PRAGMA journal_mode = WAL")
    # Wait up to 5s for locks instead of failing immediately
    await _db.execute("PRAGMA busy_timeout = 5000")
    await _db.executescript(SCHEMA)
    # Migrations: add columns to existing databases
    for column_def in (
        "ALTER TABLE actors ADD COLUMN password_hash TEXT",
        "ALTER TABLE actors ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            await _db.execute(column_def)
        except aiosqlite.OperationalError:
            pass  # column already exists
    await _db.commit()
    return _db


async def close_db() -> None:
    """Close the shared connection (lifespan shutdown)."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def get_db() -> aiosqlite.Connection:
    """Return the shared connection, initialising it if necessary."""
    if _db is None:
        return await init_db()
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
    password_hash   TEXT,
    is_admin        INTEGER NOT NULL DEFAULT 0,
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
