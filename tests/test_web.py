"""Tests for web UI routes (register, login, logout, pages)."""

import os

import httpx

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

    async def test_logout_works_without_csrf_header(self):
        """POST /logout is CSRF-exempt (plain HTML forms can't send the
        header): it must succeed with just the session cookie and actually
        clear the session. Regression for 'logout button does nothing'."""
        await self.register_user()
        resp = await self.client.post(
            "/logout",
            data={},
            headers={"X-CSRFToken": "bogus"},  # ignored — /logout is exempt
            follow_redirects=False,
        )
        assert resp.status_code == 303
        resp = await self.client.get("/api/me")
        assert resp.status_code == 401

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
                "password": "correct123",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/login",
            data={
                "username": "loginuser",
                "password": "wrongpass",
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
                "password": "pw123456",
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
                "password": "pw123456",
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


class TestLoginWithStaleSessionCookie(AsyncTestCase):
    """Regression: browsers carry a session cookie from before the
    starlette-csrf middleware existed. The plain HTML login/register forms
    cannot send an X-CSRFToken header, so those endpoints must stay exempt —
    otherwise users get 403 and cannot log in at all."""

    async def _raw_client_with_session_cookie(self) -> httpx.AsyncClient:
        """A client (no CSRF request hook) holding only a session cookie."""
        from httpx import ASGITransport

        from app.main import app

        await self.register_user(username="stale", password="password123")
        session = self.client.cookies.get("session")
        assert session
        raw = httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        )
        raw.headers["Cookie"] = f"session={session}"
        return raw

    async def test_login_form_works_with_session_cookie_no_csrf_header(self):
        raw = await self._raw_client_with_session_cookie()
        try:
            resp = await raw.post(
                "/login",
                data={"username": "stale", "password": "password123"},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/"
        finally:
            await raw.aclose()

    async def test_register_form_works_with_session_cookie_no_csrf_header(self):
        raw = await self._raw_client_with_session_cookie()
        try:
            resp = await raw.post(
                "/register",
                data={
                    "username": "newbie",
                    "display_name": "New",
                    "password": "password123",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 303
        finally:
            await raw.aclose()

    async def test_authenticated_posts_still_require_csrf_header(self):
        """The exemption must not open the rest: a logged-in POST without a
        matching X-CSRFToken header is still rejected."""
        await self.register_user()
        resp = await self.client.post(
            "/api/reviews",
            data={
                "content": "x",
                "rating": "5",
                "latitude": "0",
                "longitude": "0",
            },
            headers={"X-CSRFToken": "bogus"},
        )
        assert resp.status_code == 403


class TestRegistrationValidation(AsyncTestCase):
    """RegisterForm (Pydantic) rejects bad input with a 400 + message."""

    async def _post(
        self, username: str, password: str = "password123"
    ) -> httpx.Response:
        return await self.client.post(
            "/register",
            data={"username": username, "display_name": "X", "password": password},
            follow_redirects=False,
        )

    async def test_username_pattern_rejected(self):
        resp = await self._post("Bad Name!")
        assert resp.status_code == 400
        assert "username" in resp.text

    async def test_reserved_username_rejected(self):
        resp = await self._post("login")
        assert resp.status_code == 400

    async def test_short_password_rejected(self):
        resp = await self._post("validname", password="short")
        assert resp.status_code == 400
        assert "password" in resp.text

    async def test_valid_registration_still_works(self):
        resp = await self._post("good_name")
        assert resp.status_code == 303


class TestRegistrationModes(AsyncTestCase):
    """REGISTRATION_MODE=closed refuses; =invite requires a valid code."""

    async def _set_mode(self, mode: str) -> None:
        from app.config import config

        config.registration_mode = mode

    async def test_closed_mode(self):
        await self._set_mode("closed")
        resp = await self.client.get("/register")
        assert resp.status_code == 200
        assert "closed" in resp.text.lower()
        resp = await self.client.post(
            "/register",
            data={
                "username": "closed1",
                "display_name": "X",
                "password": "password123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 403

    async def test_invite_mode_requires_code(self):
        await self._set_mode("invite")
        resp = await self.client.post(
            "/register",
            data={"username": "nocode", "display_name": "X", "password": "password123"},
            follow_redirects=False,
        )
        assert resp.status_code == 403
        assert "invite" in resp.text.lower()

    async def test_invite_code_prefilled_on_form(self):
        await self._set_mode("invite")
        resp = await self.client.get("/register", params={"code": "abc123"})
        assert resp.status_code == 200
        assert 'value="abc123"' in resp.text

    async def test_invite_flow_create_use_reuse(self):
        await self._set_mode("invite")
        # Bootstrap the admin (one-time, CSRF-exempt), then log in as them.
        await self.client.post(
            "/api/bootstrap",
            data={
                "username": "admin",
                "display_name": "Admin",
                "password": "adminpass123",
            },
        )
        resp = await self.client.post(
            "/login",
            data={"username": "admin", "password": "adminpass123"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        # Admin creates an invite code.
        resp = await self.client.post("/api/admin/invites", data={})
        assert resp.status_code == 200
        code = resp.json()["invite"]["code"]
        assert f"code={code}" in resp.json()["invite"]["register_url"]
        # Registering with the code works.
        resp = await self.client.post(
            "/register",
            data={
                "username": "invited",
                "display_name": "Invited",
                "password": "password123",
                "code": code,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        # The one-time code is now spent.
        resp = await self.client.post(
            "/register",
            data={
                "username": "second",
                "display_name": "S",
                "password": "password123",
                "code": code,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 403


class TestSessionCookieFlags(AsyncTestCase):
    async def test_session_cookie_has_max_age_httponly_samesite(self):
        resp = await self.client.post(
            "/register",
            data={"username": "cookie", "display_name": "C", "password": "password123"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        cookies = resp.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if c.startswith("session=")).lower()
        assert "max-age=2592000" in session_cookie  # default 30 days
        assert "httponly" in session_cookie
        assert "samesite=lax" in session_cookie
        # Test server runs on plain http — no Secure flag expected.
        assert "secure" not in session_cookie


class TestRateLimit(AsyncTestCase):
    async def test_login_rate_limited_after_5_per_minute(self):
        from app.main import app

        app.state.limiter.enabled = True
        try:
            for _ in range(5):
                resp = await self.client.post(
                    "/login", data={"username": "ghost", "password": "wrongpass"}
                )
                assert resp.status_code == 401
            resp = await self.client.post(
                "/login", data={"username": "ghost", "password": "wrongpass"}
            )
            assert resp.status_code == 429
        finally:
            app.state.limiter.enabled = False

    async def test_register_rate_limited_after_3_per_minute(self):
        from app.main import app

        app.state.limiter.enabled = True
        try:
            for i in range(3):
                resp = await self.client.post(
                    "/register",
                    data={
                        "username": f"rl{i}",
                        "display_name": "X",
                        "password": "short",  # 400, but still counted
                    },
                )
                assert resp.status_code == 400
            resp = await self.client.post(
                "/register",
                data={"username": "rl3", "display_name": "X", "password": "short"},
            )
            assert resp.status_code == 429
        finally:
            app.state.limiter.enabled = False
