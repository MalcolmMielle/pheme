"""Tests for web UI routes (register, login, logout, pages)."""

from httpx import AsyncClient

from tests.conftest import get_csrf_token


class TestPages:
    async def test_index_page(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_login_page(self, client: AsyncClient):
        resp = await client.get("/login")
        assert resp.status_code == 200
        assert "Sign in" in resp.text

    async def test_register_page(self, client: AsyncClient):
        resp = await client.get("/register")
        assert resp.status_code == 200
        assert "Create an account" in resp.text

    async def test_review_page_not_found(self, client: AsyncClient):
        resp = await client.get("/review/9999")
        assert resp.status_code == 404


class TestAuth:
    async def test_register_creates_user(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/register")
        resp = await client.post(
            "/register",
            data={
                "username": "newuser",
                "display_name": "New User",
                "password": "password123",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    async def test_register_duplicate_username(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/register")
        data = {
            "username": "dup",
            "display_name": "First",
            "password": "password123",
            "csrf_token": csrf,
        }
        await client.post("/register", data=data, follow_redirects=False)
        resp = await client.post("/register", data=data, follow_redirects=False)
        assert resp.status_code == 409
        assert "already taken" in resp.text

    async def test_register_rejects_missing_csrf(self, client: AsyncClient):
        resp = await client.post(
            "/register",
            data={
                "username": "nocsrf",
                "display_name": "No CSRF",
                "password": "password123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 403

    async def test_login_success(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/register")
        await client.post(
            "/register",
            data={
                "username": "loginuser",
                "display_name": "Login User",
                "password": "mypassword",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        # Already logged in after register, so get CSRF from index page
        csrf = await get_csrf_token(client, "/")
        resp = await client.post(
            "/login",
            data={
                "username": "loginuser",
                "password": "mypassword",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    async def test_login_wrong_password(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/register")
        await client.post(
            "/register",
            data={
                "username": "loginuser",
                "display_name": "Login User",
                "password": "correct",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        csrf = await get_csrf_token(client, "/")
        resp = await client.post(
            "/login",
            data={
                "username": "loginuser",
                "password": "wrong",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert "Invalid username or password" in resp.text

    async def test_login_nonexistent_user(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/login")
        resp = await client.post(
            "/login",
            data={
                "username": "ghost",
                "password": "whatever",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 401

    async def test_login_redirects_if_already_logged_in(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/register")
        await client.post(
            "/register",
            data={
                "username": "already",
                "display_name": "Already",
                "password": "pw",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        resp = await client.get("/login", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    async def test_logout(self, client: AsyncClient):
        csrf = await get_csrf_token(client, "/register")
        await client.post(
            "/register",
            data={
                "username": "logoutuser",
                "display_name": "Logout",
                "password": "pw",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        # Get a fresh CSRF token from the index page (logged-in state)
        csrf = await get_csrf_token(client, "/")
        resp = await client.post(
            "/logout",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    async def test_protected_page_redirects_when_not_logged_in(
        self, client: AsyncClient
    ):
        """POST /api/reviews should redirect to /login when not authenticated."""
        csrf = await get_csrf_token(client, "/")
        resp = await client.post(
            "/api/reviews",
            data={
                "content": "test",
                "rating": "5",
                "latitude": "0",
                "longitude": "0",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
