"""Tests for the database layer (actors, follows, invites, connection).

Review CRUD tests live in tests/test_reviews.py (the app/reviews package)."""

import unittest

from tests.base import AsyncTestCase

from app.activitypub.signing import generate_keypair
from app.db import (
    accept_follow,
    create_actor,
    follow_actor,
    get_actor_by_id,
    get_actor_by_uri,
    get_actor_by_username,
    get_followers,
    get_following,
    hash_password,
    list_local_actors,
    verify_password,
)


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
        password_hash=hash_password("secret"),
    )


class TestPasswordHashing(unittest.TestCase):
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


class TestActorCRUD(AsyncTestCase):
    async def test_create_and_get_by_username(self):
        actor = await _make_actor("alice")
        assert actor["username"] == "alice"
        assert actor["is_local"] == 1

        fetched = await get_actor_by_username("alice")
        assert fetched is not None
        assert fetched["id"] == actor["id"]

    async def test_get_by_uri(self):
        actor = await _make_actor("bob")
        fetched = await get_actor_by_uri(actor["actor_uri"])
        assert fetched is not None
        assert fetched["username"] == "bob"

    async def test_get_by_id(self):
        actor = await _make_actor("carol")
        fetched = await get_actor_by_id(actor["id"])
        assert fetched is not None
        assert fetched["username"] == "carol"

    async def test_get_nonexistent_returns_none(self):
        assert await get_actor_by_username("nobody") is None
        assert await get_actor_by_uri("http://testserver/actor/nobody") is None
        assert await get_actor_by_id(9999) is None

    async def test_list_local_actors(self):
        await _make_actor("alice")
        await _make_actor("bob")
        actors = await list_local_actors()
        assert len(actors) == 2
        assert {a["username"] for a in actors} == {"alice", "bob"}

    async def test_duplicate_username_rejected(self):
        await _make_actor("alice")
        with self.assertRaises(Exception):
            await _make_actor("alice")


class TestFollows(AsyncTestCase):
    """Tests for follow relationships (corrected semantics)."""

    async def test_follow_and_accept(self):
        alice = await _make_actor("alice")
        bob = await _make_actor("bob")

        # Bob follows Alice
        await follow_actor(bob["id"], alice["actor_uri"])
        await accept_follow(bob["id"], alice["actor_uri"])

        # Alice's followers should include Bob
        followers = await get_followers(alice["id"])
        assert bob["actor_uri"] in followers

        # Bob's following should include Alice
        following = await get_following(bob["id"])
        assert alice["actor_uri"] in following

    async def test_follow_is_idempotent(self):
        alice = await _make_actor("alice")
        bob = await _make_actor("bob")

        await follow_actor(bob["id"], alice["actor_uri"])
        await follow_actor(bob["id"], alice["actor_uri"])  # duplicate
        await accept_follow(bob["id"], alice["actor_uri"])

        following = await get_following(bob["id"])
        assert following.count(alice["actor_uri"]) == 1

    async def test_pending_follow_not_in_followers(self):
        alice = await _make_actor("alice")
        bob = await _make_actor("bob")

        # Bob follows Alice but not yet accepted
        await follow_actor(bob["id"], alice["actor_uri"])

        followers = await get_followers(alice["id"])
        assert len(followers) == 0  # not accepted yet

    async def test_follower_inboxes(self):
        from app.db import get_follower_inboxes

        alice = await _make_actor("alice")
        bob = await _make_actor("bob")

        await follow_actor(bob["id"], alice["actor_uri"])
        await accept_follow(bob["id"], alice["actor_uri"])

        inboxes = await get_follower_inboxes(alice["id"])
        assert bob["inbox_uri"] in inboxes

    async def test_delete_actor_removes_incoming_follows(self):
        """Deleting an actor must also drop follow rows where others follow
        them — otherwise orphan rows linger forever."""
        from app.db import delete_actor, get_db

        alice = await _make_actor("alice")
        bob = await _make_actor("bob")
        await follow_actor(bob["id"], alice["actor_uri"])
        await accept_follow(bob["id"], alice["actor_uri"])
        assert await get_followers(alice["id"]) == [bob["actor_uri"]]

        assert await delete_actor(alice["id"])
        db = await get_db()
        row = await db.execute("SELECT COUNT(*) AS n FROM follows")
        result = await row.fetchone()
        assert result is not None
        assert result["n"] == 0


class TestConnectionLifecycle(AsyncTestCase):
    """The shared connection's lifecycle, owned by the FastAPI lifespan.

    httpx's ASGITransport does not run the lifespan, so tests drive
    init_db()/close_db() themselves (see AsyncTestCase.asyncSetUp) — these
    tests pin down that contract.
    """

    async def test_get_db_returns_same_open_connection(self):
        from app.db import get_db

        db1 = await get_db()
        db2 = await get_db()
        assert db1 is db2
        row = await db1.execute("SELECT 1 AS one")
        result = await row.fetchone()
        assert result is not None
        assert result["one"] == 1

    async def test_init_db_is_idempotent(self):
        from app.db import get_db, init_db

        assert await init_db() is await get_db()

    async def test_close_db_when_not_open_is_noop(self):
        from app.db import close_db

        await close_db()
        await close_db()  # must not raise

    async def test_get_db_reopens_after_close(self):
        from app.db import close_db, get_db

        old = await get_db()
        await close_db()
        new = await get_db()  # lazy re-init
        assert new is not old
        # The old handle is really closed (aiosqlite: no active connection).
        with self.assertRaises(ValueError):
            await old.execute("SELECT 1")

    async def test_lifespan_opens_at_startup_and_closes_at_shutdown(self):
        from app.db import close_db, get_db
        from app.main import app, lifespan

        await close_db()  # simulate an app that has not started yet
        async with lifespan(app):
            inside = await get_db()  # opened by the lifespan
            row = await inside.execute("SELECT COUNT(*) AS n FROM actors")
            count = await row.fetchone()
            assert count is not None
            assert count["n"] == 0
        # After shutdown the connection is closed: get_db() opens a
        # different one and the old handle raises.
        after = await get_db()
        assert after is not inside
        with self.assertRaises(ValueError):
            await inside.execute("SELECT 1")
