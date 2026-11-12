"""Tests for ActivityPub endpoints (WebFinger, Actor, Outbox, etc.)."""

import json
import unittest

from app.activitypub.signing import generate_keypair, sign_request
from app.db import (
    accept_follow,
    create_actor,
    follow_actor,
    get_actor_by_username,
    get_followers,
    get_review_by_id,
)
from tests.base import AsyncTestCase, get_csrf_token


class TestWebFinger(AsyncTestCase):
    async def test_webfinger_valid(self):
        # Bootstrap an actor first
        await self.client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw123456"},
        )
        resp = await self.client.get(
            "/.well-known/webfinger",
            params={"resource": "acct:alice@testserver"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject"] == "acct:alice@testserver"
        assert data["links"][0]["href"] == "http://testserver/actor/alice"

    async def test_webfinger_unknown_user(self):
        resp = await self.client.get(
            "/.well-known/webfinger",
            params={"resource": "acct:nobody@testserver"},
        )
        assert resp.status_code == 404

    async def test_webfinger_rejects_non_acct(self):
        resp = await self.client.get(
            "/.well-known/webfinger",
            params={"resource": "https://example.com"},
        )
        assert resp.status_code == 400


class TestActor(AsyncTestCase):
    async def test_get_actor(self):
        await self.client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw123456"},
        )
        resp = await self.client.get(
            "/actor/alice",
            headers={"Accept": "application/activity+json"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/activity+json"
        data = resp.json()
        assert data["type"] == "Person"
        assert data["preferredUsername"] == "alice"
        assert data["name"] == "Alice"
        assert "publicKey" in data
        assert data["publicKey"]["publicKeyPem"]

    async def test_get_actor_not_found(self):
        resp = await self.client.get("/actor/nobody")
        assert resp.status_code == 404


class TestOutbox(AsyncTestCase):
    async def test_outbox_empty(self):
        await self.client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw123456"},
        )
        resp = await self.client.get("/actor/alice/outbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "OrderedCollection"
        assert data["totalItems"] == 0
        assert data["orderedItems"] == []

    async def test_outbox_contains_reviews(self):
        # Register and log in
        csrf = await get_csrf_token(self.client, "/register")
        await self.client.post(
            "/register",
            data={
                "username": "alice",
                "display_name": "Alice",
                "password": "pw123456",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        # Already logged in after register, so login is a no-op but let's
        # verify the session is active by getting CSRF from the register page
        csrf = await get_csrf_token(self.client, "/register")
        await self.client.post(
            "/api/reviews",
            data={
                "content": "Great place",
                "rating": "5",
                "latitude": "37.7749",
                "longitude": "-122.4194",
                "place_name": "Test Place",
                "csrf_token": csrf,
            },
        )
        # Check outbox
        resp = await self.client.get("/actor/alice/outbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalItems"] == 1
        item = data["orderedItems"][0]
        assert item["type"] == "Create"
        assert item["object"]["type"] == "Note"
        assert item["object"]["content"] == "Great place"
        assert item["object"]["rating"] == 5
        assert item["object"]["latitude"] == 37.7749


class TestFollowersFollowing(AsyncTestCase):
    async def test_empty_followers(self):
        await self.client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw123456"},
        )
        resp = await self.client.get("/actor/alice/followers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalItems"] == 0

    async def test_empty_following(self):
        await self.client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw123456"},
        )
        resp = await self.client.get("/actor/alice/following")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalItems"] == 0


class TestFetchGuard(unittest.IsolatedAsyncioTestCase):
    """SSRF guard — server-side fetches must refuse dangerous targets."""

    async def test_rejects_non_http_schemes(self):
        from app.activitypub.fetchguard import check_fetch_url

        assert await check_fetch_url("file:///etc/passwd") is not None
        assert await check_fetch_url("ftp://example.com/x") is not None

    async def test_rejects_metadata_and_unspecified_addresses(self):
        from app.activitypub.fetchguard import check_fetch_url

        assert (
            await check_fetch_url("http://169.254.169.254/latest/meta-data") is not None
        )
        assert await check_fetch_url("http://0.0.0.0/") is not None
        assert await check_fetch_url("http://[::]/") is not None
        assert await check_fetch_url("http://[fe80::1]/") is not None

    async def test_public_host_requires_https(self):
        from app.activitypub.fetchguard import check_fetch_url

        assert await check_fetch_url("http://8.8.8.8/x") is not None
        assert await check_fetch_url("https://8.8.8.8/x") is None

    async def test_loopback_and_private_allowed_over_http(self):
        # Local dev federation (e.g. a second instance on localhost:8001)
        # has no TLS certificate.
        from app.activitypub.fetchguard import check_fetch_url

        assert await check_fetch_url("http://127.0.0.1:8001/actor/bob") is None
        assert await check_fetch_url("http://[::1]:8001/actor/bob") is None
        assert await check_fetch_url("http://localhost:8001/actor/bob") is None
        assert await check_fetch_url("http://192.168.1.10:8001/inbox") is None


class TestInbox(AsyncTestCase):
    async def test_inbox_rejects_unsigned(self):
        await self.client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw123456"},
        )
        resp = await self.client.post(
            "/actor/alice/inbox",
            content=json.dumps({"type": "Create", "actor": "https://remote/actor/bob"}),
            headers={"Content-Type": "application/activity+json"},
        )
        # Should be rejected (401) due to missing/invalid signature
        assert resp.status_code == 401

    async def test_shared_inbox_no_actors(self):
        resp = await self.client.post(
            "/inbox",
            content="{}",
            headers={"Content-Type": "application/activity+json"},
        )
        assert resp.status_code == 404

    async def test_undo_follow_removes_follower(self):
        """A signed Undo{Follow} must drop the sender from the target's followers."""
        await self.client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw123456"},
        )
        alice = await get_actor_by_username("alice")
        assert alice is not None

        # Remote actor bob with a real keypair, so the inbox can verify him.
        priv, pub = generate_keypair()
        bob = await create_actor(
            username="bob",
            display_name="Bob",
            summary="",
            private_key_pem=priv,
            public_key_pem=pub,
            actor_uri="https://remote.example/actor/bob",
            inbox_uri="https://remote.example/actor/bob/inbox",
            outbox_uri="https://remote.example/actor/bob/outbox",
            followers_uri="https://remote.example/actor/bob/followers",
            following_uri="https://remote.example/actor/bob/following",
        )
        assert bob is not None
        await follow_actor(bob["id"], alice["actor_uri"])
        await accept_follow(bob["id"], alice["actor_uri"])
        assert await get_followers(alice["id"]) == ["https://remote.example/actor/bob"]

        undo = {
            "id": "https://remote.example/actor/bob/undo/1",
            "type": "Undo",
            "actor": "https://remote.example/actor/bob",
            "object": {
                "id": "https://remote.example/actor/bob/follow/alice",
                "type": "Follow",
                "actor": "https://remote.example/actor/bob",
                "object": {"id": alice["actor_uri"], "type": "Person"},
            },
        }
        body = json.dumps(undo).encode()
        signed = sign_request(
            method="POST",
            url="http://testserver/actor/alice/inbox",
            body=body,
            key_id="https://remote.example/actor/bob#main-key",
            private_key_pem=priv,
        )
        resp = await self.client.post(
            "/actor/alice/inbox",
            content=body,
            headers={
                "Content-Type": "application/activity+json",
                "Host": "testserver",
                "Date": signed["Date"],
                "Digest": signed["Digest"],
                "Signature": signed["Signature"],
            },
        )
        assert resp.status_code == 200
        assert await get_followers(alice["id"]) == []

    async def _make_remote_bob(self):
        """A remote actor with a real keypair, so the inbox can verify him."""
        priv, pub = generate_keypair()
        bob = await create_actor(
            username="bob",
            display_name="Bob",
            summary="",
            private_key_pem=priv,
            public_key_pem=pub,
            actor_uri="https://remote.example/actor/bob",
            inbox_uri="https://remote.example/actor/bob/inbox",
            outbox_uri="https://remote.example/actor/bob/outbox",
            followers_uri="https://remote.example/actor/bob/followers",
            following_uri="https://remote.example/actor/bob/following",
            is_local=False,
        )
        return bob, priv

    async def _post_signed(
        self,
        priv: str,
        activity: dict,
        key_id: str = "https://remote.example/actor/bob#main-key",
    ):
        """Bootstrap alice and POST a signed activity (default: remote bob's key)."""
        await self.client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw123456"},
        )
        body = json.dumps(activity).encode()
        signed = sign_request(
            method="POST",
            url="http://testserver/actor/alice/inbox",
            body=body,
            key_id=key_id,
            private_key_pem=priv,
        )
        return await self.client.post(
            "/actor/alice/inbox",
            content=body,
            headers={
                "Content-Type": "application/activity+json",
                "Host": "testserver",
                "Date": signed["Date"],
                "Digest": signed["Digest"],
                "Signature": signed["Signature"],
            },
        )

    async def _post_signed_create(self, priv: str, note: dict):
        activity = {
            "id": "https://remote.example/actor/bob/create/1",
            "type": "Create",
            "actor": "https://remote.example/actor/bob",
            "object": note,
        }
        return await self._post_signed(priv, activity)

    async def test_create_stores_federated_review(self):
        from app.db import review_exists

        _, priv = await self._make_remote_bob()
        note = {
            "id": "https://remote.example/actor/bob/review/1",
            "type": "Note",
            "content": "Loved it",
            "rating": 5,
            "latitude": 37.7,
            "longitude": -122.4,
            "published": "2026-10-01T12:00:00Z",
        }
        resp = await self._post_signed_create(priv, note)
        assert resp.status_code == 200
        assert resp.json()["status"] == "created"
        assert await review_exists(note["id"])

    async def test_create_rejects_invalid_rating(self):
        """A federated rating outside 1-5 must be rejected with 400, not
        silently dropped by the DB CHECK while reporting "created"."""
        from app.db import review_exists

        _, priv = await self._make_remote_bob()
        note = {
            "id": "https://remote.example/actor/bob/review/bad",
            "type": "Note",
            "content": "x",
            "rating": 99,
            "latitude": 37.7,
            "longitude": -122.4,
        }
        resp = await self._post_signed_create(priv, note)
        assert resp.status_code == 400
        assert not await review_exists(note["id"])

    def _make_note(self, ap_id: str, content: str, rating: int) -> dict:
        return {
            "id": ap_id,
            "type": "Note",
            "content": content,
            "rating": rating,
            "latitude": 37.7,
            "longitude": -122.4,
            "placeName": "Cafe",
            "placeAddress": "1 Main St",
            "published": "2026-10-01T12:00:00Z",
        }

    async def test_update_applies_author_edit(self):
        """A signed Update from the original author edits the stored review."""
        bob, priv = await self._make_remote_bob()
        ap_id = "https://remote.example/actor/bob/review/1"
        resp = await self._post_signed_create(priv, self._make_note(ap_id, "Loved it", 5))
        assert resp.status_code == 200

        update = {
            "id": "https://remote.example/actor/bob/update/1",
            "type": "Update",
            "actor": "https://remote.example/actor/bob",
            "object": self._make_note(ap_id, "Actually it was fine", 3),
        }
        resp = await self._post_signed(priv, update)
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

        # The stored review carries the edit — still a single row.
        from app.db import review_exists

        assert await review_exists(ap_id)
        review = await get_review_by_id(await self._review_id_by_ap_id(ap_id))
        assert review is not None
        assert review["content"] == "Actually it was fine"
        assert review["rating"] == 3
        assert review["actor_id"] == bob["id"]

    async def _review_id_by_ap_id(self, ap_id: str) -> int:
        from app.db import get_db

        db = await get_db()
        row = await db.execute("SELECT id FROM reviews WHERE ap_id = ?", (ap_id,))
        result = await row.fetchone()
        assert result is not None
        return result["id"]

    async def test_update_rejected_for_non_author(self):
        """An Update signed by someone other than the author is refused."""
        bob, bob_priv = await self._make_remote_bob()
        ap_id = "https://remote.example/actor/bob/review/1"
        resp = await self._post_signed_create(bob_priv, self._make_note(ap_id, "Loved it", 5))
        assert resp.status_code == 200

        # carol has her own keypair — she is not the author.
        carol_priv, carol_pub = generate_keypair()
        await create_actor(
            username="carol",
            display_name="Carol",
            summary="",
            private_key_pem=carol_priv,
            public_key_pem=carol_pub,
            actor_uri="https://remote2.example/actor/carol",
            inbox_uri="https://remote2.example/actor/carol/inbox",
            outbox_uri="https://remote2.example/actor/carol/outbox",
            followers_uri="https://remote2.example/actor/carol/followers",
            following_uri="https://remote2.example/actor/carol/following",
            is_local=False,
        )
        update = {
            "id": "https://remote2.example/actor/carol/update/1",
            "type": "Update",
            "actor": "https://remote2.example/actor/carol",
            "object": self._make_note(ap_id, "hijacked", 1),
        }
        resp = await self._post_signed(
            carol_priv,
            update,
            key_id="https://remote2.example/actor/carol#main-key",
        )
        assert resp.status_code == 403

        review = await get_review_by_id(await self._review_id_by_ap_id(ap_id))
        assert review is not None
        assert review["content"] == "Loved it"
        assert review["rating"] == 5

    async def test_update_unknown_review_not_found(self):
        _, priv = await self._make_remote_bob()
        update = {
            "id": "https://remote.example/actor/bob/update/9",
            "type": "Update",
            "actor": "https://remote.example/actor/bob",
            "object": self._make_note(
                "https://remote.example/actor/bob/review/9", "x", 3
            ),
        }
        resp = await self._post_signed(priv, update)
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"

    async def test_create_second_review_at_same_place_is_duplicate(self):
        """One review per actor per place also holds for federated Creates:
        a second Create from the same sender at the same place (different
        ap_id) is ignored, while a different actor at the same place is fine."""
        from app.db import get_db, review_exists

        _, priv = await self._make_remote_bob()
        note1 = self._make_note("https://remote.example/actor/bob/review/1", "First", 5)
        resp = await self._post_signed_create(priv, note1)
        assert resp.json()["status"] == "created"

        # Same sender, same coordinates, new ap_id → duplicate, not stored.
        note2 = self._make_note("https://remote.example/actor/bob/review/2", "Second", 1)
        resp = await self._post_signed_create(priv, note2)
        assert resp.status_code == 200
        assert resp.json()["status"] == "duplicate"
        assert not await review_exists(note2["id"])

        # A different remote actor at the same place is not a duplicate.
        carol_priv, carol_pub = generate_keypair()
        await create_actor(
            username="carol",
            display_name="Carol",
            summary="",
            private_key_pem=carol_priv,
            public_key_pem=carol_pub,
            actor_uri="https://remote2.example/actor/carol",
            inbox_uri="https://remote2.example/actor/carol/inbox",
            outbox_uri="https://remote2.example/actor/carol/outbox",
            followers_uri="https://remote2.example/actor/carol/followers",
            following_uri="https://remote2.example/actor/carol/following",
            is_local=False,
        )
        note3 = self._make_note("https://remote2.example/actor/carol/review/1", "Carol", 4)
        activity = {
            "id": "https://remote2.example/actor/carol/create/1",
            "type": "Create",
            "actor": "https://remote2.example/actor/carol",
            "object": note3,
        }
        resp = await self._post_signed(
            carol_priv, activity, key_id="https://remote2.example/actor/carol#main-key"
        )
        assert resp.json()["status"] == "created"

        # Still exactly two reviews, both at the same coordinates.
        db = await get_db()
        row = await db.execute("SELECT COUNT(*) AS n FROM reviews")
        result = await row.fetchone()
        assert result is not None
        assert result["n"] == 2
