"""Tests for web UI routes (register, login, logout, pages)."""

import os

from tests.base import AsyncTestCase, get_csrf_token

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPA_INDEX = os.path.join(REPO_ROOT, "react-app", "dist", "index.html")


class TestPages(AsyncTestCase):
    async def test_index_page(self):
        """`/` is the React SPA — served when built, 404 with a hint otherwise."""
        resp = await self.client.get("/")
        if os.path.isfile(SPA_INDEX):
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert '<div id="root">' in resp.text
        else:
            assert resp.status_code == 404
            assert "npm run build" in resp.text

    async def test_login_page(self):
        resp = await self.client.get("/login")
        assert resp.status_code == 200
        assert "Sign in" in resp.text

    async def test_register_page(self):
        resp = await self.client.get("/register")
        assert resp.status_code == 200
        assert "Create an account" in resp.text

    async def test_review_page_not_found(self):
        resp = await self.client.get("/review/9999")
        assert resp.status_code == 404


class TestAuth(AsyncTestCase):
    async def test_register_creates_user(self):
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
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

    async def test_register_duplicate_username(self):
        csrf = await get_csrf_token(self.client, "/register")
        data = {
            "username": "dup",
            "display_name": "First",
            "password": "password123",
            "csrf_token": csrf,
        }
        await self.client.post("/register", data=data, follow_redirects=False)
        resp = await self.client.post("/register", data=data, follow_redirects=False)
        assert resp.status_code == 409
        assert "already taken" in resp.text

    async def test_register_rejects_missing_csrf(self):
        resp = await self.client.post(
            "/register",
            data={
                "username": "nocsrf",
                "display_name": "No CSRF",
                "password": "password123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 403

    async def test_login_success(self):
        csrf = await get_csrf_token(self.client, "/register")
        await self.client.post(
            "/register",
            data={
                "username": "loginuser",
                "display_name": "Login User",
                "password": "mypassword",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        # Already logged in after register, so get CSRF from the register page
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
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

    async def test_login_wrong_password(self):
        csrf = await get_csrf_token(self.client, "/register")
        await self.client.post(
            "/register",
            data={
                "username": "loginuser",
                "display_name": "Login User",
                "password": "correct",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
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

    async def test_login_nonexistent_user(self):
        csrf = await get_csrf_token(self.client, "/login")
        resp = await self.client.post(
            "/login",
            data={
                "username": "ghost",
                "password": "whatever",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 401

    async def test_login_redirects_if_already_logged_in(self):
        csrf = await get_csrf_token(self.client, "/register")
        await self.client.post(
            "/register",
            data={
                "username": "already",
                "display_name": "Already",
                "password": "pw",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        resp = await self.client.get("/login", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    async def test_logout(self):
        csrf = await get_csrf_token(self.client, "/register")
        await self.client.post(
            "/register",
            data={
                "username": "logoutuser",
                "display_name": "Logout",
                "password": "pw",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        # Get a fresh CSRF token from the register page (always renders a form)
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/logout",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    async def test_protected_page_redirects_when_not_logged_in(self):
        """POST /api/reviews should redirect to /login when not authenticated."""
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
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
