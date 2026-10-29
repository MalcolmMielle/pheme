"""Tests for ActivityPub endpoints (WebFinger, Actor, Outbox, etc.)."""

import json

from httpx import AsyncClient

from tests.conftest import get_csrf_token


class TestWebFinger:
    async def test_webfinger_valid(self, client: AsyncClient):
        # Bootstrap an actor first
        await client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw"},
        )
        resp = await client.get(
            "/.well-known/webfinger",
            params={"resource": "acct:alice@testserver"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject"] == "acct:alice@testserver"
        assert data["links"][0]["href"] == "http://testserver/actor/alice"

    async def test_webfinger_unknown_user(self, client: AsyncClient):
        resp = await client.get(
            "/.well-known/webfinger",
            params={"resource": "acct:nobody@testserver"},
        )
        assert resp.status_code == 404

    async def test_webfinger_rejects_non_acct(self, client: AsyncClient):
        resp = await client.get(
            "/.well-known/webfinger",
            params={"resource": "https://example.com"},
        )
        assert resp.status_code == 400


class TestActor:
    async def test_get_actor(self, client: AsyncClient):
        await client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw"},
        )
        resp = await client.get(
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

    async def test_get_actor_not_found(self, client: AsyncClient):
        resp = await client.get("/actor/nobody")
        assert resp.status_code == 404


class TestOutbox:
    async def test_outbox_empty(self, client: AsyncClient):
        await client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw"},
        )
        resp = await client.get("/actor/alice/outbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "OrderedCollection"
        assert data["totalItems"] == 0
        assert data["orderedItems"] == []

    async def test_outbox_contains_reviews(
        self, client: AsyncClient
    ):
        # Register and log in
        csrf = await get_csrf_token(client, "/register")
        await client.post(
            "/register",
            data={
                "username": "alice",
                "display_name": "Alice",
                "password": "pw",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        # Already logged in after register, so login is a no-op but let's
        # verify the session is active by getting CSRF from the register page
        csrf = await get_csrf_token(client, "/register")
        await client.post(
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
        resp = await client.get("/actor/alice/outbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalItems"] == 1
        item = data["orderedItems"][0]
        assert item["type"] == "Create"
        assert item["object"]["type"] == "Note"
        assert item["object"]["content"] == "Great place"
        assert item["object"]["rating"] == 5
        assert item["object"]["latitude"] == 37.7749


class TestFollowersFollowing:
    async def test_empty_followers(self, client: AsyncClient):
        await client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw"},
        )
        resp = await client.get("/actor/alice/followers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalItems"] == 0

    async def test_empty_following(self, client: AsyncClient):
        await client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw"},
        )
        resp = await client.get("/actor/alice/following")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalItems"] == 0


class TestInbox:
    async def test_inbox_rejects_unsigned(self, client: AsyncClient):
        await client.post(
            "/api/bootstrap",
            data={"username": "alice", "display_name": "Alice", "password": "pw"},
        )
        resp = await client.post(
            "/actor/alice/inbox",
            content=json.dumps({"type": "Create", "actor": "https://remote/actor/bob"}),
            headers={"Content-Type": "application/activity+json"},
        )
        # Should be rejected (401) due to missing/invalid signature
        assert resp.status_code == 401

    async def test_shared_inbox_no_actors(self, client: AsyncClient):
        resp = await client.post(
            "/inbox",
            content="{}",
            headers={"Content-Type": "application/activity+json"},
        )
        assert resp.status_code == 404
