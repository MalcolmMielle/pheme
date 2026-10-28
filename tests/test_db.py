"""Tests for the database layer (actors, reviews, follows)."""

import pytest

from app.activitypub.signing import generate_keypair
from app.db import (
    accept_follow,
    create_actor,
    create_review,
    follow_actor,
    get_actor_by_id,
    get_actor_by_uri,
    get_actor_by_username,
    get_followers,
    get_following,
    get_reviews,
    get_reviews_by_bounds,
    hash_password,
    list_local_actors,
    review_exists,
    verify_password,
)


async def _make_actor(db, username: str = "alice") -> dict:
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
        password_hash=hash_password("secret"),
    )


class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = hash_password("mypassword")
        assert h != "mypassword"
        assert verify_password("mypassword", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("mypassword")
        assert verify_password("wrongpassword", h) is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt uses random salt


class TestActorCRUD:
    async def test_create_and_get_by_username(self, db):
        actor = await _make_actor(db, "alice")
        assert actor["username"] == "alice"
        assert actor["is_local"] == 1

        fetched = await get_actor_by_username("alice")
        assert fetched is not None
        assert fetched["id"] == actor["id"]

    async def test_get_by_uri(self, db):
        actor = await _make_actor(db, "bob")
        fetched = await get_actor_by_uri(actor["actor_uri"])
        assert fetched is not None
        assert fetched["username"] == "bob"

    async def test_get_by_id(self, db):
        actor = await _make_actor(db, "carol")
        fetched = await get_actor_by_id(actor["id"])
        assert fetched is not None
        assert fetched["username"] == "carol"

    async def test_get_nonexistent_returns_none(self, db):
        assert await get_actor_by_username("nobody") is None
        assert await get_actor_by_uri("http://testserver/actor/nobody") is None
        assert await get_actor_by_id(9999) is None

    async def test_list_local_actors(self, db):
        await _make_actor(db, "alice")
        await _make_actor(db, "bob")
        actors = await list_local_actors()
        assert len(actors) == 2
        assert {a["username"] for a in actors} == {"alice", "bob"}

    async def test_duplicate_username_rejected(self, db):
        await _make_actor(db, "alice")
        with pytest.raises(Exception):
            await _make_actor(db, "alice")


class TestReviewCRUD:
    async def test_create_and_get_review(self, db):
        actor = await _make_actor(db)
        review = await create_review(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="Great place!",
            rating=5,
            latitude=37.7749,
            longitude=-122.4194,
            place_name="Test Place",
            place_address="123 Test St",
        )
        assert review["content"] == "Great place!"
        assert review["rating"] == 5

    async def test_get_reviews_includes_actor_info(self, db):
        actor = await _make_actor(db)
        await create_review(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="Nice",
            rating=4,
            latitude=37.0,
            longitude=-122.0,
        )
        reviews = await get_reviews()
        assert len(reviews) == 1
        assert reviews[0]["username"] == "alice"
        assert reviews[0]["display_name"] == "Alice"

    async def test_get_reviews_by_bounds(self, db):
        actor = await _make_actor(db)
        # Inside SF bounds
        await create_review(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/1",
            content="In SF",
            rating=5,
            latitude=37.7749,
            longitude=-122.4194,
        )
        # Outside SF bounds (NYC)
        await create_review(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/2",
            content="In NYC",
            rating=3,
            latitude=40.7128,
            longitude=-74.0060,
        )
        sf_reviews = await get_reviews_by_bounds(
            min_lat=37.70, max_lat=37.85, min_lng=-122.50, max_lng=-122.35
        )
        assert len(sf_reviews) == 1
        assert sf_reviews[0]["content"] == "In SF"

    async def test_duplicate_ap_id_returns_existing(self, db):
        actor = await _make_actor(db)
        ap_id = "http://testserver/actor/alice/review/dup"
        r1 = await create_review(
            actor_id=actor["id"],
            ap_id=ap_id,
            content="First",
            rating=5,
            latitude=37.0,
            longitude=-122.0,
        )
        r2 = await create_review(
            actor_id=actor["id"],
            ap_id=ap_id,
            content="Second",
            rating=1,
            latitude=0,
            longitude=0,
        )
        assert r1["id"] == r2["id"]
        assert r2["content"] == "First"  # original preserved

    async def test_review_exists(self, db):
        actor = await _make_actor(db)
        ap_id = "http://testserver/actor/alice/review/exists"
        assert await review_exists(ap_id) is False
        await create_review(
            actor_id=actor["id"],
            ap_id=ap_id,
            content="Test",
            rating=3,
            latitude=0,
            longitude=0,
        )
        assert await review_exists(ap_id) is True

    async def test_rating_constraint(self, db):
        """Rating outside 1-5 should fail the CHECK constraint."""
        actor = await _make_actor(db)
        # create_review catches IntegrityError and returns {} on failure
        result = await create_review(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/bad",
            content="Bad rating",
            rating=6,  # > 5
            latitude=0,
            longitude=0,
        )
        assert result == {}  # insert rejected by CHECK constraint
        result = await create_review(
            actor_id=actor["id"],
            ap_id="http://testserver/actor/alice/review/bad2",
            content="Bad rating",
            rating=0,  # < 1
            latitude=0,
            longitude=0,
        )
        assert result == {}


class TestFollows:
    """Tests for follow relationships.

    Note: on main, get_followers and get_following have inverted semantics
    (get_followers returns who the actor follows, get_following returns who
    follows the actor). These tests match the current main behavior.
    """

    async def test_follow_and_accept(self, db):
        alice = await _make_actor(db, "alice")
        bob = await _make_actor(db, "bob")

        # Bob follows Alice
        await follow_actor(bob["id"], alice["actor_uri"])
        await accept_follow(bob["id"], alice["actor_uri"])

        # On main: get_followers(bob) returns who Bob follows (= Alice)
        following = await get_followers(bob["id"])
        assert alice["actor_uri"] in following

        # On main: get_following(alice) returns who follows Alice (= Bob)
        followers = await get_following(alice["id"])
        assert bob["actor_uri"] in followers

    async def test_follow_is_idempotent(self, db):
        alice = await _make_actor(db, "alice")
        bob = await _make_actor(db, "bob")

        await follow_actor(bob["id"], alice["actor_uri"])
        await follow_actor(bob["id"], alice["actor_uri"])  # duplicate
        await accept_follow(bob["id"], alice["actor_uri"])

        following = await get_followers(bob["id"])
        assert following.count(alice["actor_uri"]) == 1

    async def test_pending_follow_not_in_followers(self, db):
        alice = await _make_actor(db, "alice")
        bob = await _make_actor(db, "bob")

        # Bob follows Alice but not yet accepted
        await follow_actor(bob["id"], alice["actor_uri"])

        following = await get_followers(bob["id"])
        assert len(following) == 0  # not accepted yet
