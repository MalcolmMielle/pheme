"""Domain exceptions for the places package."""

from typing import Any


class AlreadyReviewed(Exception):
    """An actor tried to add a second review at a place they already
    reviewed. Carries the existing review."""

    def __init__(self, review: dict[str, Any]) -> None:
        super().__init__(f"already reviewed this place (review id {review['id']})")
        self.review = review
