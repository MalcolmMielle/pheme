"""Tests for the JSON API endpoints."""

from httpx import AsyncClient


async def _login(client: AsyncClient, username: str, password: str) -> None:
    """Log in via the web form and store the session cookie."""
    resp = await client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303


class TestBootstrap:
    async def test_bootstrap_creates_actor(self, client: AsyncClient):
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
        resp = await client.post(
            "/api/reviews",
            data={
                "content": "Test",
                "rating": "5",
                "latitude": "37.0",
                "longitude": "-122.0",
            },
        )
        # Should redirect to login (303) or return error
        assert resp.status_code in (303, 401, 403, 422)

    async def test_create_and_list_review(
        self, client: AsyncClient, registered_user: dict
    ):
        await _login(client, registered_user["username"], registered_user["password"])

        resp = await client.post(
            "/api/reviews",
            data={
                "content": "Great coffee!",
                "rating": "5",
                "latitude": "37.7749",
                "longitude": "-122.4194",
                "place_name": "Coffee Shop",
                "place_address": "123 Main St",
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
        await _login(client, registered_user["username"], registered_user["password"])

        # Create a review in SF
        await client.post(
            "/api/reviews",
            data={
                "content": "SF Review",
                "rating": "4",
                "latitude": "37.7749",
                "longitude": "-122.4194",
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
        await _login(client, registered_user["username"], registered_user["password"])

        for _ in range(2):
            resp = await client.post(
                "/api/reviews",
                data={
                    "content": "Same content",
                    "rating": "5",
                    "latitude": "37.0",
                    "longitude": "-122.0",
                },
            )
            assert resp.status_code == 200

        resp = await client.get("/api/reviews")
        reviews = resp.json()
        ap_ids = [r["ap_id"] for r in reviews]
        assert len(ap_ids) == len(set(ap_ids))  # all unique
