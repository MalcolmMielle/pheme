"""Reviews — the review manager: all DB access for the reviews table plus
the factory for ``Review`` objects.

Mirrors the app/places package layout: this module owns the queries, the
``Review`` entity (app/reviews/review.py) owns a single row and its
save/delete behavior. The manager is stateless (the DB connection is the
global one from app.db.connection), so the module singleton ``reviews`` is
all the app needs.
"""

import aiosqlite

from app.db.connection import get_db
from app.reviews.review import Review


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
    ) -> list[Review]:
        where, params = _actor_uri_where(actor_uris)
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
    ) -> list[Review]:
        where, params = _actor_uri_where(actor_uris)
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

    async def count(self, actor_uris: list[str] | None = None) -> int:
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

    async def count_by_bounds(
        self,
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


#: The server's Reviews instance.
reviews = Reviews()
