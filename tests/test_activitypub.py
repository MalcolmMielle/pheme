"""Tests for ActivityPub endpoints (WebFinger, Actor, Outbox, etc.)."""

import json

from app.activitypub.signing import generate_keypair, sign_request
from app.db import (
    accept_follow,
    create_actor,
    follow_actor,
    get_actor_by_username,
    get_followers,
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
