"""Tests for the JSON API endpoints."""

from tests.base import AsyncTestCase, get_csrf_token


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

    async def test_create_review_rejects_missing_csrf(self):
        await self.register_user()  # logs in via /register
        resp = await self.client.post(
            "/api/reviews",
            data={
                "content": "No CSRF",
                "rating": "5",
                "latitude": "37.0",
                "longitude": "-122.0",
            },
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
        """Two reviews with the same content should get different ap_ids."""
        await self.register_user()
        csrf = await get_csrf_token(self.client, "/register")

        for _ in range(2):
            resp = await self.client.post(
                "/api/reviews",
                data={
                    "content": "Same content",
                    "rating": "5",
                    "latitude": "37.0",
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
        # Create 5 reviews
        for i in range(5):
            await self.client.post(
                "/api/reviews",
                data={
                    "content": f"Review {i}",
                    "rating": "3",
                    "latitude": "37.0",
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
