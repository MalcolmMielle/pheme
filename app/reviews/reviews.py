"""Reviews — the review manager: all DB access for the reviews table plus
the factory for ``Review`` objects.

Mirrors the app/places package layout: this module owns the queries, the
``Review`` entity (app/reviews/review.py) owns a single row and its
save/delete behavior. The manager is stateless (the DB connection is the
global one from app.db.connection), so the module singleton ``reviews`` is
all the app needs.
"""

from typing import Any

import aiosqlite

from app.db.connection import get_db
from app.reviews.review import Review


def _like_pattern(q: str) -> str:
    """A ``%…%`` LIKE pattern for the search text, with LIKE wildcards in the
    text itself escaped (``ESCAPE '\\'`` in the SQL) so e.g. ``q="100%"``
    matches a literal percent sign, not everything."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _where(
    actor_uris: list[str] | None,
    search_text: str | None = None,
    min_rating: int | None = None,
) -> tuple[str, list[str]]:
    """SQL WHERE fragment for the review queries: optionally restrict to the
    given actor URIs, to reviews whose content, place name or address contains
    the search text ``search_text`` (case-insensitive LIKE), and/or to reviews
    with at least ``min_rating`` stars.

    Returns (clause, params) — no filters means "1=1"; an empty ``actor_uris``
    list means "match nothing" ("1=0").
    """
    clauses: list[str] = []
    params: list[Any] = []  # actor URIs (str), LIKE patterns (str), rating (int)
    if actor_uris is not None:
        if not actor_uris:
            return "1=0", []
        placeholders = ",".join("?" for _ in actor_uris)
        clauses.append(f"a.actor_uri IN ({placeholders})")
        params.extend(actor_uris)
    if search_text:
        pattern = _like_pattern(search_text)
        clauses.append(
            "(r.content LIKE ? ESCAPE '\\' OR r.place_name LIKE ? ESCAPE '\\' "
            "OR r.place_address LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern])
    if min_rating is not None:
        clauses.append("r.rating >= ?")
        params.append(min_rating)
    if not clauses:
        return "1=1", []
    return " AND ".join(clauses), params


class Reviews:
    """Manager for the reviews table: queries + create factory."""

    async def create(
        self,
        *,
        actor_id: int,
        ap_id: str,
        content: str,
        rating: int,
        latitude: float,
        longitude: float,
        place_name: str = "",
        place_address: str = "",
        created_at: str | None = None,
    ) -> Review:
        """Insert a review. ``created_at`` (SQLite UTC 'YYYY-MM-DD HH:MM:SS')
        overrides the DB default — used to preserve the original ``published``
        date of a federated review instead of the local receipt time.

        On a duplicate ap_id (already federated to us) returns the existing row.
        """
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
            return Review(dict(result) if result else {})
        row = await db.execute(
            "SELECT * FROM reviews WHERE id = ?", (cursor.lastrowid,)
        )
        return Review(dict(await row.fetchone()))  # type: ignore[arg-type]

    async def exists(self, ap_id: str) -> bool:
        db = await get_db()
        row = await db.execute("SELECT 1 FROM reviews WHERE ap_id = ?", (ap_id,))
        return await row.fetchone() is not None

    async def by_id(self, review_id: int) -> Review | None:
        """Return a single review with actor info, or None."""
        db = await get_db()
        row = await db.execute(f"{Review.SELECT_JOINED} WHERE r.id = ?", (review_id,))
        result = await row.fetchone()
        return Review(dict(result)) if result else None

    async def by_ap_id(self, ap_id: str) -> Review | None:
        """Return a single review by its ActivityPub id, with actor info, or None."""
        db = await get_db()
        row = await db.execute(f"{Review.SELECT_JOINED} WHERE r.ap_id = ?", (ap_id,))
        result = await row.fetchone()
        return Review(dict(result)) if result else None

    async def all(
        self,
        limit: int = 200,
        offset: int = 0,
        actor_uris: list[str] | None = None,
        q: str | None = None,
        min_rating: int | None = None,
    ) -> list[Review]:
        """All reviews (optionally filtered by actor URIs, a text search ``q``
        over content, place name and address, and/or a ``min_rating`` floor)."""
        where, params = _where(actor_uris, q, min_rating)
        db = await get_db()
        rows = await db.execute(
            f"""{Review.SELECT_JOINED}
               WHERE {where}
               ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        )
        return [Review(dict(r)) for r in await rows.fetchall()]

    async def by_actor(
        self,
        actor_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Review]:
        db = await get_db()
        rows = await db.execute(
            f"""{Review.SELECT_JOINED}
               WHERE r.actor_id = ?
               ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
            (actor_id, limit, offset),
        )
        return [Review(dict(r)) for r in await rows.fetchall()]

    async def by_bounds(
        self,
        min_lat: float,
        max_lat: float,
        min_lng: float,
        max_lng: float,
        limit: int = 200,
        offset: int = 0,
        actor_uris: list[str] | None = None,
        q: str | None = None,
        min_rating: int | None = None,
    ) -> list[Review]:
        """Reviews within the given map bounds (optionally filtered by actor
        URIs, a text search ``q`` and/or a ``min_rating`` floor)."""
        where, params = _where(actor_uris, q, min_rating)
        db = await get_db()
        rows = await db.execute(
            f"""{Review.SELECT_JOINED}
               WHERE r.latitude BETWEEN ? AND ?
                 AND r.longitude BETWEEN ? AND ?
                 AND {where}
               ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
            (min_lat, max_lat, min_lng, max_lng, *params, limit, offset),
        )
        return [Review(dict(r)) for r in await rows.fetchall()]

    async def count(
        self,
        actor_uris: list[str] | None = None,
        q: str | None = None,
        min_rating: int | None = None,
    ) -> int:
        """Return the total number of reviews (optionally for given actor
        URIs, a text search ``q`` and/or a ``min_rating`` floor)."""
        where, params = _where(actor_uris, q, min_rating)
        db = await get_db()
        row = await db.execute(
            f"""SELECT COUNT(*) AS cnt FROM reviews r
               JOIN actors a ON r.actor_id = a.id WHERE {where}""",
            params,
        )
        result = await row.fetchone()
        return result["cnt"] if result else 0

    async def count_by_bounds(
        self,
        min_lat: float,
        max_lat: float,
        min_lng: float,
        max_lng: float,
        actor_uris: list[str] | None = None,
        q: str | None = None,
        min_rating: int | None = None,
    ) -> int:
        """Return the number of reviews within the given map bounds
        (optionally filtered by actor URIs, a text search ``q`` and/or a
        ``min_rating`` floor)."""
        where, params = _where(actor_uris, q, min_rating)
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


#: The server's Reviews instance.
reviews = Reviews()
