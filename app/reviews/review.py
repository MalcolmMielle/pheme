"""Review — one review entity: a row of the reviews table (with actor info
joined in) plus behavior.

Not a dict subclass: the row lives in ``self.row``. Reads keep working both
ways — ``review["content"]`` (``__getitem__``) and ``review.content``
(``__getattr__``) — while ``to_dict()`` provides the plain dict where one is
required (JSON responses). ``SELECT_JOINED`` is the row query and lives on
the class.
"""

from typing import Any

from app.db.connection import get_db


class Review:
    """One review. Build via the ``Reviews`` manager (app/reviews/reviews.py)."""

    SELECT_JOINED = """SELECT r.*, a.username, a.display_name, a.actor_uri
                       FROM reviews r JOIN actors a ON r.actor_id = a.id"""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = dict(row)

    def __getitem__(self, key: str) -> Any:
        return self.row[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.row.get(key, default)

    def __getattr__(self, name: str) -> Any:
        """Attribute access for row fields: ``review.content`` etc."""
        if name == "row":
            raise AttributeError(name)
        try:
            return self.row[name]
        except KeyError:
            raise AttributeError(name) from None

    def to_dict(self) -> dict[str, Any]:
        """The row as a plain dict (for JSON responses)."""
        return dict(self.row)

    async def save(
        self,
        *,
        content: str,
        rating: int,
        latitude: float,
        longitude: float,
        place_name: str = "",
        place_address: str = "",
    ) -> bool:
        """Persist edits to this review's editable fields and refresh this
        object in place (with actor info). Returns False when the row no
        longer exists."""
        db = await get_db()
        cursor = await db.execute(
            """UPDATE reviews SET content = ?, rating = ?, latitude = ?,
               longitude = ?, place_name = ?, place_address = ?
               WHERE id = ?""",
            (
                content,
                rating,
                latitude,
                longitude,
                place_name,
                place_address,
                self.row["id"],
            ),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return False
        row = await db.execute(
            f"{self.SELECT_JOINED} WHERE r.id = ?", (self.row["id"],)
        )
        fresh = await row.fetchone()
        if fresh is not None:
            self.row = dict(fresh)
        return True

    async def delete(self) -> bool:
        """Delete this review's row. Returns True if a row was deleted."""
        db = await get_db()
        cursor = await db.execute("DELETE FROM reviews WHERE id = ?", (self.row["id"],))
        await db.commit()
        return cursor.rowcount > 0
