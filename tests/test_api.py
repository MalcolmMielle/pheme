"""Tests for the JSON API endpoints."""

import unittest
from unittest.mock import patch

from app.db import (
    accept_follow,
    create_actor,
    follow_actor,
    get_actor_by_username,
)
from app.reviews import reviews
from app.routes.api import _resolve_actor_uri, _webfinger_schemes
from tests.base import AsyncTestCase, get_csrf_token

JSON_HEADERS = {"Accept": "application/json"}


class TestBootstrap(AsyncTestCase):
    async def test_bootstrap_creates_actor(self):
        # /api/bootstrap is exempt from CSRF (curl setup endpoint)
        resp = await self.client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["actor"]["preferredUsername"] == "admin"

    async def test_bootstrap_returns_existing(self):
        await self.client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        resp = await self.client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "exists"


class TestReviewsAPI(AsyncTestCase):
    async def test_get_reviews_empty(self):
        resp = await self.client.get("/api/reviews")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_unknown_api_path_returns_404_json_not_spa(self):
        """The SPA catch-all must not swallow unknown /api routes."""
        resp = await self.client.get("/api/does-not-exist")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["detail"] == "Not found"

    async def test_create_review_requires_auth(self):
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/reviews",
            data={
                "content": "Test",
                "rating": "5",
                "latitude": "37.0",
                "longitude": "-122.0",
                "csrf_token": csrf,
            },
        )
        # Should redirect to login (303) — auth check happens after CSRF
        assert resp.status_code in (303, 401, 403)

    async def test_create_review_rejects_bad_csrf_header(self):
        await self.register_user()  # logs in via /register
        resp = await self.client.post(
            "/api/reviews",
            data={
                "content": "No CSRF",
                "rating": "5",
                "latitude": "37.0",
                "longitude": "-122.0",
            },
            headers={"X-CSRFToken": "bogus"},
        )
        assert resp.status_code == 403

    async def test_create_and_list_review(self):
        await self.register_user()  # logs in via /register
        csrf = await get_csrf_token(self.client, "/register")

        resp = await self.client.post(
            "/api/reviews",
            data={
                "content": "Great coffee!",
                "rating": "5",
                "latitude": "37.7749",
                "longitude": "-122.4194",
                "place_name": "Coffee Shop",
                "place_address": "123 Main St",
                "csrf_token": csrf,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["review"]["content"] == "Great coffee!"
        assert data["review"]["rating"] == 5

        # List reviews
        resp = await self.client.get("/api/reviews")
        assert resp.status_code == 200
        reviews = resp.json()
        assert len(reviews) == 1
        assert reviews[0]["content"] == "Great coffee!"

    async def test_create_review_validates_payload(self):
        """JSON and form bodies alike go through CreateReviewPayload."""
        await self.register_user()  # logs in via /register

        # JSON body (the SPA's format), rating out of range
        resp = await self.client.post(
            "/api/reviews",
            json={"content": "x", "rating": 9, "latitude": 1.0, "longitude": 2.0},
        )
        assert resp.status_code == 422

        # JSON body, missing longitude
        resp = await self.client.post(
            "/api/reviews",
            json={"content": "x", "rating": 3, "latitude": 1.0},
        )
        assert resp.status_code == 422

        # Form body, empty content
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/reviews",
            data={
                "content": "",
                "rating": "3",
                "latitude": "1",
                "longitude": "2",
                "csrf_token": csrf,
            },
        )
        assert resp.status_code == 422

        # Valid JSON body still works (rating coerced, as the SPA sends it)
        resp = await self.client.post(
            "/api/reviews",
            json={"content": "Nice", "rating": 4, "latitude": 1.0, "longitude": 2.0},
        )
        assert resp.status_code == 200
        assert resp.json()["review"]["rating"] == 4

    async def test_create_review_with_bounds_filter(self):
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")

        # Create a review in SF
        await self.client.post(
            "/api/reviews",
            data={
                "content": "SF Review",
                "rating": "4",
                "latitude": "37.7749",
                "longitude": "-122.4194",
                "csrf_token": csrf,
            },
        )
        # Create a review in NYC
        await self.client.post(
            "/api/reviews",
            data={
                "content": "NYC Review",
                "rating": "3",
                "latitude": "40.7128",
                "longitude": "-74.0060",
                "csrf_token": csrf,
            },
        )

        # Filter by SF bounds
        resp = await self.client.get(
            "/api/reviews",
            params={
                "min_lat": "37.70",
                "max_lat": "37.85",
                "min_lng": "-122.50",
                "max_lng": "-122.35",
            },
        )
        assert resp.status_code == 200
        reviews = resp.json()
        assert len(reviews) == 1
        assert reviews[0]["content"] == "SF Review"

    async def test_review_ap_id_is_unique(self):
        """Two reviews at different places should get different ap_ids."""
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")

        for lat in ("37.0", "40.0"):
            resp = await self.client.post(
                "/api/reviews",
                data={
                    "content": "Same content",
                    "rating": "5",
                    "latitude": lat,
                    "longitude": "-122.0",
                    "csrf_token": csrf,
                },
            )
            assert resp.status_code == 200

        resp = await self.client.get("/api/reviews")
        reviews = resp.json()
        ap_ids = [r["ap_id"] for r in reviews]
        assert len(ap_ids) == len(set(ap_ids))  # all unique

    async def test_get_single_review(self):
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/reviews",
            data={
                "content": "Single review test",
                "rating": "4",
                "latitude": "37.0",
                "longitude": "-122.0",
                "csrf_token": csrf,
            },
        )
        review_id = resp.json()["review"]["id"]

        resp = await self.client.get(f"/api/reviews/{review_id}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "Single review test"

    async def test_get_single_review_not_found(self):
        resp = await self.client.get("/api/reviews/9999")
        assert resp.status_code == 404

    async def test_delete_review(self):
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/reviews",
            data={
                "content": "To be deleted",
                "rating": "3",
                "latitude": "37.0",
                "longitude": "-122.0",
                "csrf_token": csrf,
            },
        )
        review_id = resp.json()["review"]["id"]

        resp = await self.client.delete(f"/api/reviews/{review_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify it's gone
        resp = await self.client.get(f"/api/reviews/{review_id}")
        assert resp.status_code == 404

    async def test_delete_review_not_found(self):
        resp = await self.client.delete("/api/reviews/9999")
        assert resp.status_code in (303, 401, 403)  # auth required first

    async def test_delete_review_requires_auth(self):
        resp = await self.client.delete("/api/reviews/1")
        assert resp.status_code in (303, 401, 403)

    async def test_pagination(self):
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")
        # Create 5 reviews — each at a different place (one review per
        # actor per place is enforced, so vary the latitude).
        for i in range(5):
            await self.client.post(
                "/api/reviews",
                data={
                    "content": f"Review {i}",
                    "rating": "3",
                    "latitude": str(37.0 + i * 0.01),
                    "longitude": "-122.0",
                    "csrf_token": csrf,
                },
            )

        # Get first page (limit=2)
        resp = await self.client.get("/api/reviews", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        assert len(resp.json()) == 2
        assert resp.headers["X-Total-Count"] == "5"

        # Get second page
        resp = await self.client.get("/api/reviews", params={"limit": 2, "offset": 2})
        assert resp.status_code == 200
        assert len(resp.json()) == 2

        # Get last page (partial)
        resp = await self.client.get("/api/reviews", params={"limit": 2, "offset": 4})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_pagination_rejects_invalid_limit_and_offset(self):
        """limit/offset are validated: SQLite treats a negative LIMIT as
        "unlimited", so ?limit=-1 must not be accepted."""
        await self.register_user()
        for params in ({"limit": -1}, {"limit": 0}, {"limit": 1001}, {"offset": -1}):
            resp = await self.client.get("/api/reviews", params=params)
            assert resp.status_code == 422, params
        resp = await self.client.get("/api/reviews", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200

    async def test_geocode_rejects_invalid_limit(self):
        resp = await self.client.get("/api/geocode", params={"q": "x", "limit": 0})
        assert resp.status_code == 422
        resp = await self.client.get("/api/geocode", params={"q": "x", "limit": 51})
        assert resp.status_code == 422

    async def test_follow_invalid_target(self):
        """Following an unresolvable target should return 400."""
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/follow",
            data={"target": "nonexistent@nonexistent.invalid", "csrf_token": csrf},
        )
        assert resp.status_code == 400

    async def test_follow_requires_auth(self):
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/follow",
            data={"target": "https://example.com/actor/bob", "csrf_token": csrf},
        )
        assert resp.status_code in (303, 401, 403)

    async def test_follow_rejects_ssrf_targets(self):
        """Follow targets must not make the server fetch internal/metadata
        endpoints — the fetch guard refuses them with a 400 (and no outbound
        request is made)."""
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")
        for target in (
            "http://169.254.169.254/latest/meta-data",
            "http://0.0.0.0/",
            "http://8.8.8.8/actor/bob",  # public host over plain http
            "metadata@169.254.169.254",  # via WebFinger resolution
        ):
            resp = await self.client.post(
                "/api/follow",
                data={"target": target, "csrf_token": csrf},
            )
            assert resp.status_code == 400, target


class TestUpdateReview(AsyncTestCase):
    """PUT /api/reviews/{id} — edit an existing review (author only)."""

    async def _create_review(self, content: str = "Original", rating: int = 3) -> int:
        resp = await self.client.post(
            "/api/reviews",
            json={
                "content": content,
                "rating": rating,
                "latitude": 37.0,
                "longitude": -122.0,
                "place_name": "Cafe",
                "place_address": "1 Main St",
            },
        )
        assert resp.status_code == 200
        return resp.json()["review"]["id"]

    async def test_update_requires_auth(self):
        resp = await self.client.put(
            "/api/reviews/1",
            json={"content": "x", "rating": 5, "latitude": 1.0, "longitude": 2.0},
        )
        assert resp.status_code in (303, 401, 403)

    async def test_update_not_found(self):
        await self.register_user()
        resp = await self.client.put(
            "/api/reviews/9999",
            json={"content": "x", "rating": 5, "latitude": 1.0, "longitude": 2.0},
        )
        assert resp.status_code == 404

    async def test_update_forbidden_for_other_user(self):
        """Only the author may edit: a second account gets 403."""
        await self.register_user()  # testuser
        review_id = await self._create_review()
        # Registering a second user switches the session to that user.
        await self.register_user(username="otheruser", display_name="Other")
        resp = await self.client.put(
            f"/api/reviews/{review_id}",
            json={
                "content": "hijacked",
                "rating": 1,
                "latitude": 1.0,
                "longitude": 2.0,
            },
        )
        assert resp.status_code == 403
        # The review is unchanged.
        resp = await self.client.get(f"/api/reviews/{review_id}")
        assert resp.json()["content"] == "Original"

    async def test_update_review_success(self):
        await self.register_user()
        review_id = await self._create_review()

        resp = await self.client.put(
            f"/api/reviews/{review_id}",
            json={
                "content": "Edited — even better",
                "rating": 5,
                "latitude": 37.0,
                "longitude": -122.0,
                "place_name": "Cafe",
                "place_address": "1 Main St",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["review"]["id"] == review_id
        assert data["review"]["content"] == "Edited — even better"
        assert data["review"]["rating"] == 5

        # The change is persisted and visible via GET.
        resp = await self.client.get(f"/api/reviews/{review_id}")
        assert resp.json()["content"] == "Edited — even better"
        assert resp.json()["rating"] == 5

        # Still exactly one review — the edit must not create a duplicate.
        resp = await self.client.get("/api/reviews")
        assert len(resp.json()) == 1

    async def test_update_accepts_form_body(self):
        """Like POST, the PUT accepts form-encoded bodies (curl/browser)."""
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")
        review_id = await self._create_review()
        resp = await self.client.put(
            f"/api/reviews/{review_id}",
            data={
                "content": "Form edit",
                "rating": "2",
                "latitude": "37.0",
                "longitude": "-122.0",
                "csrf_token": csrf,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["review"]["content"] == "Form edit"
        assert resp.json()["review"]["rating"] == 2

    async def test_update_validates_payload(self):
        await self.register_user()
        review_id = await self._create_review()
        # Rating out of range
        resp = await self.client.put(
            f"/api/reviews/{review_id}",
            json={"content": "x", "rating": 9, "latitude": 1.0, "longitude": 2.0},
        )
        assert resp.status_code == 422
        # Missing longitude
        resp = await self.client.put(
            f"/api/reviews/{review_id}",
            json={"content": "x", "rating": 3, "latitude": 1.0},
        )
        assert resp.status_code == 422
        # Empty content
        resp = await self.client.put(
            f"/api/reviews/{review_id}",
            json={"content": "", "rating": 3, "latitude": 1.0, "longitude": 2.0},
        )
        assert resp.status_code == 422


class TestOneReviewPerPlace(AsyncTestCase):
    """One review per actor per place — enforced server-side on POST (and
    on PUT, so an edit can't be moved onto another own review's place).
    "Same place" = coordinates bucketed to 4 decimal places, like the map UI."""

    async def _post_review(
        self, lat: float, lng: float = -122.0, content: str = "Nice"
    ):
        return await self.client.post(
            "/api/reviews",
            json={"content": content, "rating": 4, "latitude": lat, "longitude": lng},
        )

    async def test_second_review_at_same_place_is_409(self):
        await self.register_user()
        resp = await self._post_review(37.0)
        assert resp.status_code == 200
        first_id = resp.json()["review"]["id"]

        resp = await self._post_review(37.0, content="Again!")
        assert resp.status_code == 409
        data = resp.json()
        assert data["review_id"] == first_id
        assert "already reviewed" in data["detail"]

        # Nothing was created — still exactly one review.
        resp = await self.client.get("/api/reviews")
        assert len(resp.json()) == 1

    async def test_same_place_bucket_counts_as_same_place(self):
        """Coordinates within the same 4-decimal bucket (~11 m) are the same
        place, matching the map UI's place grouping."""
        await self.register_user()
        assert (await self._post_review(37.0)).status_code == 200
        # 37.00001 rounds to the same 4-decimal bucket as 37.0
        resp = await self._post_review(37.00001)
        assert resp.status_code == 409

    async def test_different_place_is_allowed(self):
        await self.register_user()
        assert (await self._post_review(37.0)).status_code == 200
        assert (await self._post_review(37.01)).status_code == 200
        resp = await self.client.get("/api/reviews")
        assert len(resp.json()) == 2

    async def test_different_actor_same_place_is_allowed(self):
        """Federated/other actors can legitimately share coordinates — that
        is not a duplicate; only the same actor twice at one place is."""
        await self.register_user()  # testuser
        assert (await self._post_review(37.0)).status_code == 200
        await self.register_user(username="otheruser", display_name="Other")
        resp = await self._post_review(37.0)
        assert resp.status_code == 200
        resp = await self.client.get("/api/reviews")
        assert len(resp.json()) == 2

    async def test_update_cannot_move_onto_own_other_review(self):
        """PUT with coordinates of the author's other review → 409."""
        await self.register_user()
        resp = await self._post_review(37.0, content="Place A")
        id_a = resp.json()["review"]["id"]
        resp = await self._post_review(40.0, content="Place B")
        id_b = resp.json()["review"]["id"]

        # Moving review B onto place A is refused.
        resp = await self.client.put(
            f"/api/reviews/{id_b}",
            json={
                "content": "moved",
                "rating": 2,
                "latitude": 37.0,
                "longitude": -122.0,
            },
        )
        assert resp.status_code == 409
        assert resp.json()["review_id"] == id_a

        # Editing at its own place still works.
        resp = await self.client.put(
            f"/api/reviews/{id_b}",
            json={
                "content": "edited",
                "rating": 2,
                "latitude": 40.0,
                "longitude": -122.0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["review"]["content"] == "edited"


class TestWebFingerSchemes(unittest.TestCase):
    """Scheme selection for WebFinger: HTTPS for public hosts, HTTP first
    for local/private hosts (dev servers without TLS)."""

    def test_public_domain_https_only(self):
        assert _webfinger_schemes("example.com") == ["https"]
        assert _webfinger_schemes("example.com:8443") == ["https"]

    def test_public_ip_https_only(self):
        assert _webfinger_schemes("8.8.8.8") == ["https"]

    def test_localhost_http_first(self):
        assert _webfinger_schemes("localhost") == ["http", "https"]
        assert _webfinger_schemes("localhost:8000") == ["http", "https"]
        assert _webfinger_schemes("foo.localhost:8001") == ["http", "https"]

    def test_loopback_and_private_ips_http_first(self):
        assert _webfinger_schemes("127.0.0.1:8000") == ["http", "https"]
        assert _webfinger_schemes("192.168.1.10:8000") == ["http", "https"]


class _FakeResp:
    def __init__(self, status_code: int, data: dict | None = None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data


def _fake_client_class(get_impl):
    """Build a fake httpx.AsyncClient whose get() delegates to get_impl."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            return await get_impl(url, params)

    return FakeClient


class TestResolveActorUri(AsyncTestCase):
    async def test_direct_uri_passes_through(self):
        uri = await _resolve_actor_uri("http://localhost:8000/actor/bob")
        assert uri == "http://localhost:8000/actor/bob"

    async def test_acct_resolves_via_http_webfinger_on_localhost(self):
        """bob@localhost:8000 must resolve over plain http (dev server)."""
        requested = []

        async def fake_get(url, params=None):
            requested.append(url)
            return _FakeResp(
                200,
                {"links": [{"rel": "self", "href": "http://localhost:8000/actor/bob"}]},
            )

        with patch("app.routes.api.httpx.AsyncClient", _fake_client_class(fake_get)):
            uri = await _resolve_actor_uri("bob@localhost:8000")

        assert uri == "http://localhost:8000/actor/bob"
        assert requested == ["http://localhost:8000/.well-known/webfinger"]

    async def test_acct_falls_back_to_https_on_localhost(self):
        """If http fails on a local host, https is still tried."""
        requested = []

        async def fake_get(url, params=None):
            requested.append(url)
            if url.startswith("http://"):
                raise OSError("connection refused")
            return _FakeResp(
                200, {"links": [{"rel": "self", "href": "https://localhost/actor/bob"}]}
            )

        with patch("app.routes.api.httpx.AsyncClient", _fake_client_class(fake_get)):
            uri = await _resolve_actor_uri("acct:bob@localhost")

        assert uri == "https://localhost/actor/bob"
        assert requested == [
            "http://localhost/.well-known/webfinger",
            "https://localhost/.well-known/webfinger",
        ]

    async def test_acct_public_domain_uses_https_only(self):
        """Public hosts must never be downgraded to plain http."""
        requested = []

        async def fake_get(url, params=None):
            requested.append(url)
            return _FakeResp(404)

        with patch("app.routes.api.httpx.AsyncClient", _fake_client_class(fake_get)):
            uri = await _resolve_actor_uri("alice@example.com")

        assert uri is None
        assert requested == ["https://example.com/.well-known/webfinger"]


class TestMeFollowing(AsyncTestCase):
    """GET /api/me/following — the profile page's following list."""

    async def test_requires_auth(self):
        resp = await self.client.get("/api/me/following", headers=JSON_HEADERS)
        assert resp.status_code == 401

    async def test_empty_when_nothing_followed(self):
        await self.register_user()
        resp = await self.client.get("/api/me/following", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"following": []}

    async def test_lists_accepted_follows_with_actor_details(self):
        await self.register_user()
        actor = await get_actor_by_username("testuser")
        assert actor is not None
        remote = await create_actor(
            username="remotebob",
            display_name="Remote Bob",
            summary="",
            private_key_pem="",
            public_key_pem="",
            actor_uri="https://remote.example/actor/bob",
            inbox_uri="https://remote.example/actor/bob/inbox",
            outbox_uri="https://remote.example/actor/bob/outbox",
            followers_uri="https://remote.example/actor/bob/followers",
            following_uri="https://remote.example/actor/bob/following",
        )
        assert remote is not None
        await follow_actor(actor["id"], remote["actor_uri"])
        await accept_follow(actor["id"], remote["actor_uri"])

        resp = await self.client.get("/api/me/following", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {
            "following": [
                {
                    "actor_uri": "https://remote.example/actor/bob",
                    "username": "remotebob",
                    "display_name": "Remote Bob",
                }
            ]
        }

    async def test_pending_follow_not_listed(self):
        await self.register_user()
        actor = await get_actor_by_username("testuser")
        assert actor is not None
        await follow_actor(actor["id"], "https://remote.example/actor/bob")

        resp = await self.client.get("/api/me/following", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"following": []}

    async def test_falls_back_to_uri_segment_when_actor_not_cached(self):
        await self.register_user()
        actor = await get_actor_by_username("testuser")
        assert actor is not None
        await follow_actor(actor["id"], "https://uncached.example/users/carol")
        await accept_follow(actor["id"], "https://uncached.example/users/carol")

        resp = await self.client.get("/api/me/following", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {
            "following": [
                {
                    "actor_uri": "https://uncached.example/users/carol",
                    "username": "carol",
                    "display_name": "",
                }
            ]
        }


class TestUnfollow(AsyncTestCase):
    """POST /api/unfollow — remove a follow locally (Undo goes to the remote)."""

    async def _setup_follow(self):
        """Register a user and set up an accepted follow of a remote actor."""
        await self.register_user()
        actor = await get_actor_by_username("testuser")
        assert actor is not None
        remote = await create_actor(
            username="remotebob",
            display_name="Remote Bob",
            summary="",
            private_key_pem="",
            public_key_pem="",
            actor_uri="https://remote.example/actor/bob",
            inbox_uri="https://remote.example/actor/bob/inbox",
            outbox_uri="https://remote.example/actor/bob/outbox",
            followers_uri="https://remote.example/actor/bob/followers",
            following_uri="https://remote.example/actor/bob/following",
        )
        assert remote is not None
        await follow_actor(actor["id"], remote["actor_uri"])
        await accept_follow(actor["id"], remote["actor_uri"])
        return remote

    async def test_requires_auth(self):
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/unfollow",
            data={"target": "https://remote.example/actor/bob", "csrf_token": csrf},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 401

    async def test_invalid_target(self):
        """An unresolvable target should return 400."""
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/unfollow",
            data={"target": "nobody@nonexistent.invalid", "csrf_token": csrf},
        )
        assert resp.status_code == 400

    async def test_unfollow_removes_from_following(self):
        remote = await self._setup_follow()
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/unfollow",
            data={"target": remote["actor_uri"], "csrf_token": csrf},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unfollowed"
        assert data["was_following"] is True

        me_following = await self.client.get("/api/me/following", headers=JSON_HEADERS)
        assert me_following.json() == {"following": []}

    async def test_unfollow_not_followed_is_idempotent(self):
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/api/unfollow",
            data={"target": "http://localhost:9999/actor/nobody", "csrf_token": csrf},
        )
        assert resp.status_code == 200
        assert resp.json()["was_following"] is False


class TestReviewsScope(AsyncTestCase):
    """GET /api/reviews?scope=following — only own + followed actors' reviews."""

    async def _make_review(
        self, actor_id: int, ap_id: str, content: str, lat: float = 37.0
    ):
        await reviews.create(
            actor_id=actor_id,
            ap_id=ap_id,
            content=content,
            rating=4,
            latitude=lat,
            longitude=-122.0,
        )

    async def _setup(self):
        """testuser (logged in) follows remote bob; carol is not followed.

        Reviews: mine@37.0, bob's@40.0, carol's@37.0.
        """
        await self.register_user()
        me = await get_actor_by_username("testuser")
        assert me is not None
        bob = await create_actor(
            username="remotebob",
            display_name="Remote Bob",
            summary="",
            private_key_pem="",
            public_key_pem="",
            actor_uri="https://remote.example/actor/bob",
            inbox_uri="https://remote.example/actor/bob/inbox",
            outbox_uri="https://remote.example/actor/bob/outbox",
            followers_uri="https://remote.example/actor/bob/followers",
            following_uri="https://remote.example/actor/bob/following",
            is_local=False,
        )
        carol = await create_actor(
            username="remotecarol",
            display_name="Remote Carol",
            summary="",
            private_key_pem="",
            public_key_pem="",
            actor_uri="https://remote2.example/actor/carol",
            inbox_uri="https://remote2.example/actor/carol/inbox",
            outbox_uri="https://remote2.example/actor/carol/outbox",
            followers_uri="https://remote2.example/actor/carol/followers",
            following_uri="https://remote2.example/actor/carol/following",
            is_local=False,
        )
        assert bob is not None and carol is not None
        await follow_actor(me["id"], bob["actor_uri"])
        await accept_follow(me["id"], bob["actor_uri"])
        await self._make_review(
            me["id"], "http://testserver/actor/testuser/review/1", "mine"
        )
        await self._make_review(
            bob["id"], "https://remote.example/actor/bob/review/1", "bobs", lat=40.0
        )
        await self._make_review(
            carol["id"], "https://remote2.example/actor/carol/review/1", "carols"
        )

    async def test_scope_following_requires_auth(self):
        resp = await self.client.get(
            "/api/reviews?scope=following", headers=JSON_HEADERS
        )
        assert resp.status_code == 401

    async def test_scope_following_filters_to_own_and_followed(self):
        await self._setup()
        resp = await self.client.get(
            "/api/reviews?scope=following", headers=JSON_HEADERS
        )
        assert resp.status_code == 200
        contents = {r["content"] for r in resp.json()}
        assert contents == {"mine", "bobs"}
        assert resp.headers["X-Total-Count"] == "2"

    async def test_scope_all_returns_everything(self):
        await self._setup()
        resp = await self.client.get("/api/reviews", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()) == 3
        assert resp.headers["X-Total-Count"] == "3"

    async def test_scope_following_combined_with_bounds(self):
        await self._setup()
        # Bounds around lat 37 exclude bob's review (lat 40) and include
        # carol's — but carol is not followed, so only "mine" remains.
        resp = await self.client.get(
            "/api/reviews?scope=following&min_lat=36&max_lat=38&min_lng=-123&max_lng=-121",
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 200
        assert {r["content"] for r in resp.json()} == {"mine"}

    async def test_invalid_scope(self):
        await self.register_user()
        resp = await self.client.get("/api/reviews?scope=bogus", headers=JSON_HEADERS)
        assert resp.status_code == 400

    async def test_scope_local_returns_only_local_actors(self):
        """scope=local needs no login and excludes remote (federated) actors."""
        await self._setup()
        # Fresh client state: drop the session by using a new client.
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as anon:
            resp = await anon.get("/api/reviews?scope=local", headers=JSON_HEADERS)
        assert resp.status_code == 200
        # Only testuser is local in this setup (bob/carol are is_local=0).
        assert [r["content"] for r in resp.json()] == ["mine"]

    async def test_scope_local_with_no_local_actors(self):
        """An empty local actor set must match nothing, not everything."""
        resp = await self.client.get("/api/reviews?scope=local", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []
