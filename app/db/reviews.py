"""Review CRUD operations."""

from typing import Any

import aiosqlite

from app.db.connection import get_db


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


async def get_reviews_by_actor(
    actor_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    db = await get_db()
    rows = await db.execute(
        """SELECT r.*, a.username, a.display_name, a.actor_uri
           FROM reviews r JOIN actors a ON r.actor_id = a.id
           WHERE r.actor_id = ?
           ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
        (actor_id, limit, offset),
    )
    return [dict(r) for r in await rows.fetchall()]


async def get_reviews_by_bounds(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    db = await get_db()
    rows = await db.execute(
        """SELECT r.*, a.username, a.display_name, a.actor_uri
           FROM reviews r JOIN actors a ON r.actor_id = a.id
           WHERE r.latitude BETWEEN ? AND ?
             AND r.longitude BETWEEN ? AND ?
           ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
        (min_lat, max_lat, min_lng, max_lng, limit, offset),
    )
    return [dict(r) for r in await rows.fetchall()]


async def get_review_by_id(review_id: int) -> dict[str, Any] | None:
    """Return a single review with actor info, or None."""
    db = await get_db()
    row = await db.execute(
        """SELECT r.*, a.username, a.display_name, a.actor_uri
           FROM reviews r JOIN actors a ON r.actor_id = a.id
           WHERE r.id = ?""",
        (review_id,),
    )
    result = await row.fetchone()
    return dict(result) if result else None


async def delete_review(review_id: int) -> bool:
    """Delete a review by ID. Returns True if a row was deleted."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    await db.commit()
    return cursor.rowcount > 0


async def count_reviews() -> int:
    """Return the total number of reviews."""
    db = await get_db()
    row = await db.execute("SELECT COUNT(*) AS cnt FROM reviews")
    result = await row.fetchone()
    return result["cnt"] if result else 0


async def count_reviews_by_bounds(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
) -> int:
    """Return the number of reviews within the given map bounds."""
    db = await get_db()
    row = await db.execute(
        """SELECT COUNT(*) AS cnt FROM reviews
           WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?""",
        (min_lat, max_lat, min_lng, max_lng),
    )
    result = await row.fetchone()
    return result["cnt"] if result else 0
