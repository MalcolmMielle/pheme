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
    created_at: str | None = None,
) -> dict[str, Any]:
    """Insert a review. ``created_at`` (SQLite UTC 'YYYY-MM-DD HH:MM:SS')
    overrides the DB default — used to preserve the original ``published``
    date of a federated review instead of the local receipt time."""
    db = await get_db()
    try:
        if created_at is not None:
            cursor = await db.execute(
                """INSERT INTO reviews (actor_id, ap_id, content, rating,
                   latitude, longitude, place_name, place_address, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    actor_id,
                    ap_id,
                    content,
                    rating,
                    latitude,
                    longitude,
                    place_name,
                    place_address,
                    created_at,
                ),
            )
        else:
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


async def get_review_by_actor_at_place(
    actor_id: int, latitude: float, longitude: float
) -> dict[str, Any] | None:
    """Return the actor's review at the given place, or None.

    "Same place" means coordinates bucketed by the server's place precision
    (the ``PLACE_DECIMALS`` runtime param, default 4 ≈ 11 m) — the same
    definition the map UI uses to group reviews into one place (see placeKey
    in react-app/src/places.ts and app/places). Different actors may review
    the same place; only a second review by the *same* actor matches.
    """
    # Local import: app.places builds its Place objects on this module's
    # create_review, so a module-level import would be circular.
    from app.places import Place, places

    db = await get_db()
    p = Place(places.decimals, latitude, longitude)
    row = await db.execute(
        f"""SELECT r.*, a.username, a.display_name, a.actor_uri
           FROM reviews r JOIN actors a ON r.actor_id = a.id
           WHERE r.actor_id = ?
             AND {p.same_place_sql("r.latitude", "r.longitude")}
           LIMIT 1""",
        (actor_id, latitude, longitude),
    )
    result = await row.fetchone()
    return dict(result) if result else None


async def update_review(
    review_id: int,
    content: str,
    rating: int,
    latitude: float,
    longitude: float,
    place_name: str = "",
    place_address: str = "",
) -> dict[str, Any] | None:
    """Update a review's editable fields. Returns the updated row (with actor
    info), or None when no review with that ID exists."""
    db = await get_db()
    cursor = await db.execute(
        """UPDATE reviews SET content = ?, rating = ?, latitude = ?,
           longitude = ?, place_name = ?, place_address = ?
           WHERE id = ?""",
        (content, rating, latitude, longitude, place_name, place_address, review_id),
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    return await get_review_by_id(review_id)


def _actor_uri_where(actor_uris: list[str] | None) -> tuple[str, list[str]]:
    """SQL WHERE fragment restricting reviews to the given actor URIs.

    Returns (clause, params) — ``None`` means no filter ("1=1"), an empty
    list means "match nothing" ("1=0").
    """
    if actor_uris is None:
        return "1=1", []
    if not actor_uris:
        return "1=0", []
    placeholders = ",".join("?" for _ in actor_uris)
    return f"a.actor_uri IN ({placeholders})", list(actor_uris)


async def get_reviews(
    limit: int = 200,
    offset: int = 0,
    actor_uris: list[str] | None = None,
) -> list[dict[str, Any]]:
    where, params = _actor_uri_where(actor_uris)
    db = await get_db()
    rows = await db.execute(
        f"""SELECT r.*, a.username, a.display_name, a.actor_uri
           FROM reviews r JOIN actors a ON r.actor_id = a.id
           WHERE {where}
           ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
        (*params, limit, offset),
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
    actor_uris: list[str] | None = None,
) -> list[dict[str, Any]]:
    where, params = _actor_uri_where(actor_uris)
    db = await get_db()
    rows = await db.execute(
        f"""SELECT r.*, a.username, a.display_name, a.actor_uri
           FROM reviews r JOIN actors a ON r.actor_id = a.id
           WHERE r.latitude BETWEEN ? AND ?
             AND r.longitude BETWEEN ? AND ?
             AND {where}
           ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
        (min_lat, max_lat, min_lng, max_lng, *params, limit, offset),
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


async def count_reviews(actor_uris: list[str] | None = None) -> int:
    """Return the total number of reviews (optionally for given actor URIs)."""
    where, params = _actor_uri_where(actor_uris)
    db = await get_db()
    row = await db.execute(
        f"""SELECT COUNT(*) AS cnt FROM reviews r
           JOIN actors a ON r.actor_id = a.id WHERE {where}""",
        params,
    )
    result = await row.fetchone()
    return result["cnt"] if result else 0


async def count_reviews_by_bounds(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    actor_uris: list[str] | None = None,
) -> int:
    """Return the number of reviews within the given map bounds."""
    where, params = _actor_uri_where(actor_uris)
    db = await get_db()
    row = await db.execute(
        f"""SELECT COUNT(*) AS cnt FROM reviews r
           JOIN actors a ON r.actor_id = a.id
           WHERE r.latitude BETWEEN ? AND ?
             AND r.longitude BETWEEN ? AND ?
             AND {where}""",
        (min_lat, max_lat, min_lng, max_lng, *params),
    )
    result = await row.fetchone()
    return result["cnt"] if result else 0
