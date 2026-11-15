"""Tests for the app/reviews package — the Reviews manager (queries +
create factory) and the Review entity (row dict + save()/delete())."""

from app.activitypub.signing import generate_keypair
from app.db import create_actor
from app.reviews import Review, reviews
from tests.base import AsyncTestCase


async def _make_actor(username: str = "alice") -> dict:
    priv, pub = generate_keypair()
    base = f"http://testserver/actor/{username}"
    return await create_actor(
        username=username,
        display_name=username.capitalize(),
        summary="",
        private_key_pem=priv,
        public_key_pem=pub,
        actor_uri=base,
        inbox_uri=f"{base}/inbox",
        outbox_uri=f"{base}/outbox",
        followers_uri=f"{base}/followers",
        following_uri=f"{base}/following",
    )


class TestReviewsManager(AsyncTestCase):
    """The moved-over CRUD/query tests, now against the Reviews manager."""

    async def test_create_and_get_review(self):
        actor = await _make_actor()
        review = await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="Great place!",
            rating=5,
            latitude=37.7749,
            longitude=-122.4194,
            place_name="Test Place",
            place_address="123 Test St",
        )
        assert isinstance(review, Review)
        assert not isinstance(review, dict)  # plain entity, not a dict subclass
        assert review["content"] == "Great place!"
        assert review["rating"] == 5
        # Entity attribute access works too (Review is a row dict + behavior).
        assert review.content == "Great place!"
        assert review.rating == 5

        fetched = await reviews.by_id(review["id"])
        assert fetched is not None
        assert fetched["content"] == "Great place!"
        assert fetched["username"] == "alice"  # actor info joined

    async def test_all_includes_actor_info(self):
        actor = await _make_actor()
        await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="Nice",
            rating=4,
            latitude=37.0,
            longitude=-122.0,
        )
        found = await reviews.all()
        assert len(found) == 1
        assert found[0]["username"] == "alice"
        assert found[0]["display_name"] == "Alice"

    async def test_by_bounds(self):
        actor = await _make_actor()
        # Inside SF bounds
        await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="In SF",
            rating=5,
            latitude=37.7749,
            longitude=-122.4194,
        )
        # Outside SF bounds (NYC)
        await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/2",
            content="In NYC",
            rating=3,
            latitude=40.7128,
            longitude=-74.0060,
        )
        sf_reviews = await reviews.by_bounds(
            min_lat=37.70, max_lat=37.85, min_lng=-122.50, max_lng=-122.35
        )
        assert len(sf_reviews) == 1
        assert sf_reviews[0]["content"] == "In SF"
        assert await reviews.count_by_bounds(37.70, 37.85, -122.50, -122.35) == 1
        assert await reviews.count() == 2

    async def test_by_actor(self):
        alice = await _make_actor("alice")
        bob = await _make_actor("bob")
        await reviews.create(
            actor_id=alice["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="Alice's review",
            rating=5,
            latitude=37.0,
            longitude=-122.0,
        )
        await reviews.create(
            actor_id=bob["id"],
            ap_id="http://testserver/actor/bob/review/1",
            content="Bob's review",
            rating=3,
            latitude=37.0,
            longitude=-122.0,
        )
        alice_reviews = await reviews.by_actor(alice["id"])
        assert len(alice_reviews) == 1
        assert alice_reviews[0]["content"] == "Alice's review"

    async def test_duplicate_ap_id_returns_existing(self):
        actor = await _make_actor()
        ap_id = "http://testserver/actor/alice/review/dup"
        r1 = await reviews.create(
            actor_id=actor["id"],
            ap_id=ap_id,
            content="First",
            rating=5,
            latitude=37.0,
            longitude=-122.0,
        )
        r2 = await reviews.create(
            actor_id=actor["id"],
            ap_id=ap_id,
            content="Second",
            rating=1,
            latitude=0,
            longitude=0,
        )
        assert r1["id"] == r2["id"]
        assert r2["content"] == "First"  # original preserved

    async def test_exists_and_by_ap_id(self):
        actor = await _make_actor()
        ap_id = "http://testserver/actor/alice/review/exists"
        assert await reviews.exists(ap_id) is False
        assert await reviews.by_ap_id(ap_id) is None
        await reviews.create(
            actor_id=actor["id"],
            ap_id=ap_id,
            content="Test",
            rating=3,
            latitude=0,
            longitude=0,
        )
        assert await reviews.exists(ap_id) is True
        found = await reviews.by_ap_id(ap_id)
        assert found is not None
        assert found["content"] == "Test"
        assert found["actor_id"] == actor["id"]

    async def test_rating_constraint(self):
        """Rating outside 1-5 should fail the CHECK constraint."""
        actor = await _make_actor()
        # create catches IntegrityError and returns {} on failure
        result = await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/bad",
            content="Bad rating",
            rating=6,  # > 5
            latitude=0,
            longitude=0,
        )
        assert result.row == {}  # insert rejected by CHECK constraint
        result = await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/bad2",
            content="Bad rating",
            rating=0,  # < 1
            latitude=0,
            longitude=0,
        )
        assert result.row == {}

    async def test_actor_uri_filter(self):
        alice = await _make_actor("alice")
        bob = await _make_actor("bob")
        for actor, ap_id in (
            (alice, "http://testserver/actor/alice/review/1"),
            (bob, "http://testserver/actor/bob/review/1"),
        ):
            await reviews.create(
                actor_id=actor["id"],
                ap_id=ap_id,
                content="x",
                rating=3,
                latitude=37.0,
                longitude=-122.0,
            )
        assert await reviews.count(actor_uris=[alice["actor_uri"]]) == 1
        assert await reviews.count(actor_uris=[]) == 0  # empty = match nothing
        assert await reviews.count() == 2
        assert len(await reviews.all(actor_uris=[bob["actor_uri"]])) == 1


class TestReviewsSearch(AsyncTestCase):
    """Reviews manager text search (``q``) — matches content, place name and
    place address, case-insensitively, and combines with bounds/actor URIs."""

    async def _make(
        self,
        actor: dict,
        ap_id: str,
        content: str,
        place_name: str = "",
        place_address: str = "",
        lat: float = 37.0,
    ) -> None:
        await reviews.create(
            actor_id=actor["id"],
            ap_id=ap_id,
            content=content,
            rating=4,
            latitude=lat,
            longitude=-122.0,
            place_name=place_name,
            place_address=place_address,
        )

    async def test_search_matches_content_case_insensitive(self):
        actor = await _make_actor()
        await self._make(actor, "http://t/actor/a/review/1", "Great COFFEE and staff")
        await self._make(actor, "http://t/actor/a/review/2", "Loud music", lat=38.0)
        found = await reviews.all(q="coffee")
        assert [r["content"] for r in found] == ["Great COFFEE and staff"]
        assert await reviews.count(q="Coffee") == 1

    async def test_search_matches_place_name_and_address(self):
        actor = await _make_actor()
        await self._make(
            actor, "http://t/actor/a/review/1", "Nice", place_name="Blue Bottle Coffee"
        )
        await self._make(
            actor,
            "http://t/actor/a/review/2",
            "OK",
            place_address="12 Rue du Café, Lausanne",
            lat=38.0,
        )
        await self._make(actor, "http://t/actor/a/review/3", "Meh", lat=39.0)
        # Place name match, case-insensitive (ASCII).
        found = await reviews.all(q="coffee")
        assert [r["place_name"] for r in found] == ["Blue Bottle Coffee"]
        # Address match.
        found = await reviews.all(q="Café")
        assert [r["place_address"] for r in found] == ["12 Rue du Café, Lausanne"]

    async def test_search_no_match_returns_empty(self):
        actor = await _make_actor()
        await self._make(actor, "http://t/actor/a/review/1", "abc")
        assert await reviews.all(q="zzz") == []
        assert await reviews.count(q="zzz") == 0

    async def test_search_escapes_like_wildcards(self):
        """q="%" / "_" must not match everything; a literal % is findable."""
        actor = await _make_actor()
        await self._make(actor, "http://t/actor/a/review/1", "plain text")
        await self._make(actor, "http://t/actor/a/review/2", "100% good", lat=38.0)
        assert await reviews.count(q="%") == 1  # only the literal "100% good"
        assert await reviews.count(q="_") == 0
        assert await reviews.count(q="100%") == 1
        assert await reviews.count(q="100\\%") == 0  # backslash itself is literal

    async def test_search_combined_with_bounds(self):
        actor = await _make_actor()
        await self._make(actor, "http://t/actor/a/review/1", "coffee in SF", lat=37.0)
        await self._make(actor, "http://t/actor/a/review/2", "coffee in NYC", lat=40.7)
        found = await reviews.by_bounds(37.0, 38.0, -123.0, -121.0, q="coffee")
        assert [r["content"] for r in found] == ["coffee in SF"]
        assert (
            await reviews.count_by_bounds(37.0, 38.0, -123.0, -121.0, q="coffee") == 1
        )
        assert await reviews.count_by_bounds(37.0, 41.0, -123.0, -70.0, q="coffee") == 2

    async def test_search_combined_with_actor_uris(self):
        alice = await _make_actor("alice")
        bob = await _make_actor("bob")
        await self._make(alice, "http://t/actor/alice/review/1", "coffee by alice")
        await self._make(bob, "http://t/actor/bob/review/1", "coffee by bob")
        found = await reviews.all(q="coffee", actor_uris=[alice["actor_uri"]])
        assert [r["content"] for r in found] == ["coffee by alice"]
        assert await reviews.count(q="coffee", actor_uris=[]) == 0


class TestReviewsMinRating(AsyncTestCase):
    """Reviews manager ``min_rating`` filter — keeps reviews with at least
    that many stars; combines with q, bounds and actor URIs."""

    async def _make(
        self, actor: dict, ap_id: str, content: str, rating: int, lat: float = 37.0
    ):
        await reviews.create(
            actor_id=actor["id"],
            ap_id=ap_id,
            content=content,
            rating=rating,
            latitude=lat,
            longitude=-122.0,
        )

    async def test_min_rating_filters(self):
        actor = await _make_actor()
        for i, rating in enumerate((1, 2, 3, 4, 5)):
            await self._make(
                actor, f"http://t/actor/a/review/{i}", f"r{rating}", rating
            )
        found = await reviews.all(min_rating=4)
        assert sorted(r["rating"] for r in found) == [4, 5]
        assert await reviews.count(min_rating=5) == 1
        assert await reviews.count(min_rating=1) == 5
        assert await reviews.count() == 5  # no filter = everything

    async def test_min_rating_combined_with_q(self):
        actor = await _make_actor()
        await self._make(actor, "http://t/a/1", "coffee great", 5)
        await self._make(actor, "http://t/a/2", "coffee bad", 2, lat=38.0)
        found = await reviews.all(q="coffee", min_rating=4)
        assert [r["content"] for r in found] == ["coffee great"]

    async def test_min_rating_combined_with_bounds(self):
        actor = await _make_actor()
        await self._make(actor, "http://t/a/1", "a", 5, lat=37.0)
        await self._make(actor, "http://t/a/2", "b", 5, lat=40.7)
        await self._make(actor, "http://t/a/3", "c", 1, lat=37.5)
        found = await reviews.by_bounds(37.0, 38.0, -123.0, -121.0, min_rating=4)
        assert [r["content"] for r in found] == ["a"]
        assert (
            await reviews.count_by_bounds(37.0, 38.0, -123.0, -121.0, min_rating=4) == 1
        )


class TestReviewEntity(AsyncTestCase):
    """Review.save() / Review.delete() — the entity's own DB behavior."""

    async def test_save_updates_and_refreshes(self):
        actor = await _make_actor()
        review = await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="Old",
            rating=2,
            latitude=37.0,
            longitude=-122.0,
        )
        ok = await review.save(
            content="New",
            rating=5,
            latitude=37.0,
            longitude=-122.0,
            place_name="Cafe",
        )
        assert ok is True
        # The object itself was refreshed in place (with actor info).
        assert review["content"] == "New"
        assert review.rating == 5
        assert review["username"] == "alice"
        # And it is persisted.
        fetched = await reviews.by_id(review["id"])
        assert fetched is not None
        assert fetched["content"] == "New"

    async def test_save_missing_row_returns_false(self):
        actor = await _make_actor()
        review = await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="x",
            rating=3,
            latitude=0,
            longitude=0,
        )
        await review.delete()
        ok = await review.save(content="y", rating=1, latitude=0, longitude=0)
        assert ok is False

    async def test_delete(self):
        actor = await _make_actor()
        review = await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="x",
            rating=3,
            latitude=0,
            longitude=0,
        )
        assert await review.delete() is True
        assert await reviews.by_id(review["id"]) is None
        assert await reviews.exists(review["ap_id"]) is False
        # Deleting again is a no-op.
        assert await review.delete() is False

    async def test_review_is_json_serializable_dict(self):
        """Review is a dict subclass — API responses serialize it directly."""
        import json

        actor = await _make_actor()
        review = await reviews.create(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="x",
            rating=3,
            latitude=0,
            longitude=0,
        )
        by_id = await reviews.by_id(review["id"])
        assert by_id is not None
        data = json.loads(json.dumps(by_id.to_dict()))
        assert data["content"] == "x"
        assert data["username"] == "alice"
