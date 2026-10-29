"""Tests for the JSON API endpoints."""

from httpx import AsyncClient

from tests.conftest import get_csrf_token


class TestBootstrap:
    async def test_bootstrap_creates_actor(self, client: AsyncClient):
        # /api/bootstrap is exempt from CSRF (curl setup endpoint)
        resp = await client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["actor"]["preferredUsername"] == "admin"

    async def test_bootstrap_returns_existing(self, client: AsyncClient):
        await client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        resp = await client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "exists"


class TestReviewsAPI:
    async def test_get_reviews_empty(self, client: AsyncClient):
        resp = await client.get("/api/reviews")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_review_requires_auth(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/register")
        resp = await client.post(
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

    async def test_create_review_rejects_missing_csrf(
        self, client: AsyncClient, registered_user: dict
    ):
        # registered_user fixture already logs in
        resp = await client.post(
            "/api/reviews",
            data={
                "content": "No CSRF",
                "rating": "5",
                "latitude": "37.0",
                "longitude": "-122.0",
            },
        )
        assert resp.status_code == 403

    async def test_create_and_list_review(
        self, client: AsyncClient, registered_user: dict
    ):
        # registered_user fixture already logs in via /register
        csrf = await get_csrf_token(client, "/register")

        resp = await client.post(
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
        resp = await client.get("/api/reviews")
        assert resp.status_code == 200
        reviews = resp.json()
        assert len(reviews) == 1
        assert reviews[0]["content"] == "Great coffee!"

    async def test_create_review_with_bounds_filter(
        self, client: AsyncClient, registered_user: dict
    ):
        csrf = await get_csrf_token(client, "/register")

        # Create a review in SF
        await client.post(
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
        await client.post(
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
        resp = await client.get(
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

    async def test_review_ap_id_is_unique(
        self, client: AsyncClient, registered_user: dict
    ):
        """Two reviews with the same content should get different ap_ids."""
        csrf = await get_csrf_token(client, "/register")

        for _ in range(2):
            resp = await client.post(
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

        resp = await client.get("/api/reviews")
        reviews = resp.json()
        ap_ids = [r["ap_id"] for r in reviews]
        assert len(ap_ids) == len(set(ap_ids))  # all unique

    async def test_get_single_review(
        self, client: AsyncClient, registered_user: dict
    ):
        csrf = await get_csrf_token(client, "/register")
        resp = await client.post(
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

        resp = await client.get(f"/api/reviews/{review_id}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "Single review test"

    async def test_get_single_review_not_found(self, client: AsyncClient):
        resp = await client.get("/api/reviews/9999")
        assert resp.status_code == 404

    async def test_delete_review(
        self, client: AsyncClient, registered_user: dict
    ):
        csrf = await get_csrf_token(client, "/register")
        resp = await client.post(
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

        resp = await client.delete(f"/api/reviews/{review_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify it's gone
        resp = await client.get(f"/api/reviews/{review_id}")
        assert resp.status_code == 404

    async def test_delete_review_not_found(self, client: AsyncClient):
        resp = await client.delete("/api/reviews/9999")
        assert resp.status_code in (303, 401, 403)  # auth required first

    async def test_delete_review_requires_auth(self, client: AsyncClient):
        resp = await client.delete("/api/reviews/1")
        assert resp.status_code in (303, 401, 403)

    async def test_pagination(
        self, client: AsyncClient, registered_user: dict
    ):
        csrf = await get_csrf_token(client, "/register")
        # Create 5 reviews
        for i in range(5):
            await client.post(
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
        resp = await client.get("/api/reviews", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        assert len(resp.json()) == 2
        assert resp.headers["X-Total-Count"] == "5"

        # Get second page
        resp = await client.get("/api/reviews", params={"limit": 2, "offset": 2})
        assert resp.status_code == 200
        assert len(resp.json()) == 2

        # Get last page (partial)
        resp = await client.get("/api/reviews", params={"limit": 2, "offset": 4})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_follow_invalid_target(
        self, client: AsyncClient, registered_user: dict
    ):
        """Following an unresolvable target should return 400."""
        csrf = await get_csrf_token(client, "/register")
        resp = await client.post(
            "/api/follow",
            data={"target": "nonexistent@nonexistent.invalid", "csrf_token": csrf},
        )
        assert resp.status_code == 400

    async def test_follow_requires_auth(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/register")
        resp = await client.post(
            "/api/follow",
            data={"target": "https://example.com/actor/bob", "csrf_token": csrf},
        )
        assert resp.status_code in (303, 401, 403)
