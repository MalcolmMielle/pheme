"""Place — one place on the map: a coordinate bucket plus its reviews from
the DB.

Self-contained: takes the bucket precision (``decimals``) directly in the
constructor — the ``Places`` manager just passes its configured value when
building places via ``await places.at(lat, lng)``, so this module never
imports the manager (no circular import possible).
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.db.connection import get_db
from app.places.errors import AlreadyReviewed
from app.reviews import Review, reviews


class Place:
    """One place on the map — a coordinate bucket plus its reviews from the
    DB. Owns the place identity (``key``, ``place_key``, ``same_place_sql``,
    ``__eq__``) and the place's info (reviews, name, address, average
    rating), and offers ``reviews_at`` / ``add_review`` / ``update_review`` /
    ``review_by`` on it."""

    MAX_DECIMALS = 8

    def __init__(
        self,
        decimals: int,
        lat: float,
        lng: float,
        reviews: list[Review] | None = None,
    ) -> None:
        if not 1 <= decimals <= self.MAX_DECIMALS:
            raise ValueError(
                f"decimals must be between 1 and {self.MAX_DECIMALS} (got {decimals!r})"
            )
        self.decimals = decimals
        self.lat = lat
        self.lng = lng
        self.reviews = reviews if reviews is not None else []
        self.key = self.place_key()

    def __eq__(self, other: object) -> bool:
        """Two Place objects are equal when they fall in the same place
        bucket (same key) — their raw coordinates may differ within the
        bucket. Comparing against a non-Place is NotImplemented (→ False)."""
        if not isinstance(other, Place):
            return NotImplemented
        return self.key == other.key

    def __hash__(self) -> int:
        """Places are value objects keyed by their bucket."""
        return hash(self.key)

    # ── place identity ──────────────────────────────────────────────────

    def _bucket(self, value: float) -> float:
        """Round to ``decimals`` places, half away from zero (like SQLite)."""
        quantum = Decimal(1).scaleb(-self.decimals)
        return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))

    def place_key(self) -> str:
        """Bucket key for this place's coordinates, e.g. "37.7749,-122.4194".

        Same format as the map UI's placeKey, so keys can be compared
        across the API boundary if ever needed.
        """
        d = self.decimals
        return f"{self._bucket(self.lat):.{d}f},{self._bucket(self.lng):.{d}f}"

    def same_place_sql(self, lat_col: str, lng_col: str) -> str:
        """SQL WHERE fragment matching rows in this place's bucket, against
        two bound parameters (latitude, longitude), in that order — e.g.::

            WHERE {place.same_place_sql("r.latitude", "r.longitude")}
            -- params: (latitude, longitude)
        """
        d = self.decimals
        return (
            f"ROUND({lat_col}, {d}) = ROUND(?, {d}) "
            f"AND ROUND({lng_col}, {d}) = ROUND(?, {d})"
        )

    # ── DB access ───────────────────────────────────────────────────────

    async def reviews_at(self) -> list[Review]:
        """All reviews at this place (the bucket containing this object's
        coordinates), with actor info, newest first."""
        db = await get_db()
        rows = await db.execute(
            f"""SELECT r.*, a.username, a.display_name, a.actor_uri
               FROM reviews r JOIN actors a ON r.actor_id = a.id
               WHERE {self.same_place_sql("r.latitude", "r.longitude")}
               ORDER BY r.created_at DESC""",
            (self.lat, self.lng),
        )
        return [Review(dict(r)) for r in await rows.fetchall()]

    @property
    def name(self) -> str:
        """Most common non-empty place name among the reviews (mirrors the
        map UI's grouping in react-app/src/places.ts)."""
        counts: dict[str, int] = {}
        for r in self.reviews:
            name = (r["place_name"] or "").strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
        return max(counts, key=lambda name: counts[name]) if counts else ""

    @property
    def address(self) -> str:
        """First non-empty place address among the reviews."""
        return next(
            (r["place_address"] for r in self.reviews if r["place_address"]), ""
        )

    @property
    def avg_rating(self) -> float | None:
        """Average rating of the reviews at this place, or None when empty."""
        if not self.reviews:
            return None
        return sum(r["rating"] for r in self.reviews) / len(self.reviews)

    def review_by(self, actor_id: int) -> Review | None:
        """The actor's own review at this place, or None."""
        return next((r for r in self.reviews if r["actor_id"] == actor_id), None)

    async def add_review(
        self,
        actor: dict[str, Any],
        *,
        content: str,
        rating: int,
        place_name: str = "",
        place_address: str = "",
    ) -> Review:
        """Add the actor's review at this place. Enforces one review per
        actor per place — raises AlreadyReviewed when they already have one.
        The new review is appended to this object's ``reviews``."""
        existing = self.review_by(actor["id"])
        if existing is not None:
            raise AlreadyReviewed(existing)
        ap_id = f"{actor['actor_uri']}/review/{uuid.uuid4()}"
        review = await reviews.create(
            actor_id=actor["id"],
            ap_id=ap_id,
            content=content,
            rating=rating,
            latitude=self.lat,
            longitude=self.lng,
            place_name=place_name,
            place_address=place_address,
        )
        self.reviews.append(review)
        return review

    async def update_review(
        self,
        review_id: int,
        *,
        content: str,
        rating: int,
        place_name: str = "",
        place_address: str = "",
    ) -> Review | None:
        """Update a review of this place (kept at the place's coordinates).
        Returns the updated review, or None when the ID doesn't exist. The
        object's ``reviews`` list is kept in sync."""
        review = await reviews.by_id(review_id)
        if review is None:
            return None
        await review.save(
            content=content,
            rating=rating,
            latitude=self.lat,
            longitude=self.lng,
            place_name=place_name,
            place_address=place_address,
        )
        for i, r in enumerate(self.reviews):
            if r["id"] == review_id:
                self.reviews[i] = review
                break
        return review
