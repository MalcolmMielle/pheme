"""Domain exceptions for the places package."""

from app.reviews import Review


class AlreadyReviewed(Exception):
    """An actor tried to add a second review at a place they already
    reviewed. Carries the existing review."""

    def __init__(self, review: Review) -> None:
        super().__init__(f"already reviewed this place (review id {review['id']})")
        self.review = review
