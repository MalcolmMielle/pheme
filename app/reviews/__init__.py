"""The reviews package — review entities and the review manager.

One class per file:
  review.py   — Review: one review row (dict subclass) with save()/delete()
  reviews.py  — Reviews: the manager (all review queries + create factory)
                + the ``reviews`` singleton

Import from the package root: ``from app.reviews import Review, Reviews, reviews``.
"""

from app.reviews.review import Review
from app.reviews.reviews import Reviews, reviews

__all__ = ["Review", "Reviews", "reviews"]
