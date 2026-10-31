"""Tests for admin accounts — the first account created is the first admin."""

from tests.base import AsyncTestCase, get_csrf_token

JSON_HEADERS = {"Accept": "application/json"}


class AdminTestCase(AsyncTestCase):
    """Helpers to create/log in as an admin and as a regular user."""

    async def login(self, username: str, password: str) -> None:
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/login",
            data={"username": username, "password": password, "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)

    async def make_admin(self, username: str = "admin", password: str = "adminpass123"):
        """Register the first account — it automatically becomes the admin."""
        await self.register_user(
            username=username, password=password, display_name="Admin"
        )
        resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        self.assertTrue(resp.json()["is_admin"])

    async def csrf(self) -> str:
        """CSRF token for the current session (register form works logged-in)."""
        return await get_csrf_token(self.client, "/register")


class TestFirstAccountIsAdmin(AsyncTestCase):
    async def test_first_registered_account_becomes_admin(self):
        await self.register_user(username="first", password="pw123456")
        resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["username"] == "first"
        assert resp.json()["is_admin"] is True

    async def test_second_registered_account_is_not_admin(self):
        await self.register_user(username="first", password="pw123456")
        # Registering again switches the session to the new account
        await self.register_user(username="second", password="pw123456")
        resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        assert resp.json()["username"] == "second"
        assert resp.json()["is_admin"] is False

    async def test_bootstrap_creates_first_admin(self):
        await self.client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        csrf = await get_csrf_token(self.client, "/login")
        resp = await self.client.post(
            "/login",
            data={"username": "admin", "password": "secret", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        assert resp.json()["is_admin"] is True

    async def test_bootstrap_is_one_time(self):
        """Once any local account exists, /api/bootstrap refuses to create
        more — it must not be an unauthenticated account-creation backdoor."""
        await self.client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        resp = await self.client.post(
            "/api/bootstrap",
            data={"username": "other", "display_name": "Other", "password": "secret"},
        )
        assert resp.status_code == 403

    async def test_next_account_becomes_admin_when_server_has_none(self):
        """Legacy databases (accounts but no admin) — the next account
        created becomes the first admin."""
        await self.register_user(username="legacy", password="pw123456")
        from app.db import get_actor_by_username, set_actor_admin

        legacy = await get_actor_by_username("legacy")
        assert legacy is not None
        await set_actor_admin(legacy["id"], False)  # simulate pre-feature DB

        await self.register_user(username="newfirst", password="pw123456")
        resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        assert resp.json()["username"] == "newfirst"
        assert resp.json()["is_admin"] is True

    async def test_admin_setup_endpoint_removed(self):
        """The one-time /api/admin/setup endpoint no longer exists — the
        first account created is the admin, via /register or /api/bootstrap."""
        # JSON body so the CSRF middleware (form posts only) lets it through
        # to routing, where no route matches.
        resp = await self.client.post(
            "/api/admin/setup",
            json={"username": "root", "display_name": "Root", "password": "pw123456"},
            headers=JSON_HEADERS,
        )
        assert resp.status_code in (404, 405)


class TestAdminAccess(AdminTestCase):
    async def test_me_reports_is_admin_false_for_regular_user(self):
        await self.make_admin()  # first account — admin
        await self.register_user(username="regular")  # second — not admin
        resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is False

    async def test_admin_endpoints_require_login(self):
        for method, path in [
            ("get", "/api/admin/users"),
            ("post", "/api/admin/users"),
            ("post", "/api/admin/users/1/promote"),
            ("post", "/api/admin/users/1/demote"),
        ]:
            resp = await getattr(self.client, method)(path, headers=JSON_HEADERS)
            assert resp.status_code == 401, path

    async def test_admin_endpoints_forbidden_for_non_admin(self):
        await self.make_admin()
        await self.register_user(username="regular")  # logged in as non-admin
        csrf = await self.csrf()

        resp = await self.client.get("/api/admin/users", headers=JSON_HEADERS)
        assert resp.status_code == 403

        resp = await self.client.post(
            "/api/admin/users",
            data={
                "username": "x",
                "display_name": "X",
                "password": "pw123456",
                "csrf_token": csrf,
            },
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 403

        resp = await self.client.post(
            "/api/admin/users/1/promote",
            data={"csrf_token": csrf},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 403

    async def test_admin_posts_require_csrf(self):
        await self.make_admin()
        resp = await self.client.post(
            "/api/admin/users",
            data={"username": "x", "display_name": "X", "password": "pw123456"},
            headers={**JSON_HEADERS, "X-CSRFToken": "bogus"},
        )
        assert resp.status_code == 403  # CSRF middleware rejects before the route

    async def test_stale_csrf_cookie_recovers_after_refresh(self):
        """A csrftoken cookie signed with an old SECRET_KEY (e.g. after a
        restart without a fixed key) 403s. Once the client drops it, the
        server issues a fresh cookie and the same action succeeds — this is
        the flow the SPA's fetchWithCsrf retry implements."""
        import httpx
        from httpx import ASGITransport
        from itsdangerous.url_safe import URLSafeSerializer

        from app.main import app

        await self.make_admin()
        session = self.client.cookies.get("session")
        assert session
        raw = httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        )
        try:
            # Stale csrftoken cookie, echoed back as the header.
            stale = URLSafeSerializer("old-secret", "csrftoken").dumps("x" * 40)
            resp = await raw.post(
                "/api/admin/users",
                data={"username": "x1", "display_name": "X", "password": "pw123456"},
                headers={
                    "Cookie": f"session={session}; csrftoken={stale}",
                    "X-CSRFToken": stale,
                    **JSON_HEADERS,
                },
            )
            assert resp.status_code == 403

            # Drop the stale cookie; any GET makes the server issue a fresh one.
            await raw.get("/api/meta", headers={"Cookie": f"session={session}"})
            fresh = raw.cookies.get("csrftoken")
            assert fresh and fresh != stale
            resp = await raw.post(
                "/api/admin/users",
                data={"username": "x2", "display_name": "X", "password": "pw123456"},
                headers={
                    "Cookie": f"session={session}; csrftoken={fresh}",
                    "X-CSRFToken": fresh,
                    **JSON_HEADERS,
                },
            )
            assert resp.status_code == 200
        finally:
            await raw.aclose()


class TestAdminUserManagement(AdminTestCase):
    async def test_list_users(self):
        await self.make_admin()
        await self.register_user(username="bob", display_name="Bob")

        # register_user left the session as bob — log back in as admin
        await self.login("admin", "adminpass123")
        resp = await self.client.get("/api/admin/users", headers=JSON_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["admin_count"] == 1
        by_name = {u["username"]: u for u in data["users"]}
        assert by_name["admin"]["is_admin"] is True
        assert by_name["bob"]["is_admin"] is False
        # No secrets leak into the admin listing
        assert "password_hash" not in by_name["admin"]
        assert "private_key_pem" not in by_name["admin"]

    async def test_create_user_and_create_admin_account(self):
        await self.make_admin()
        csrf = await self.csrf()

        # Regular account
        resp = await self.client.post(
            "/api/admin/users",
            data={
                "username": "carol",
                "display_name": "Carol",
                "password": "pw123456",
                "csrf_token": csrf,
            },
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["is_admin"] is False

        # Admin account directly
        resp = await self.client.post(
            "/api/admin/users",
            data={
                "username": "dave",
                "display_name": "Dave",
                "password": "pw123456",
                "is_admin": "true",
                "csrf_token": csrf,
            },
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["is_admin"] is True

        # The new admin account can actually log in with admin rights
        await self.login("dave", "pw123456")
        resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        assert resp.json()["is_admin"] is True

    async def test_create_user_duplicate_username(self):
        await self.make_admin()
        csrf = await self.csrf()
        resp = await self.client.post(
            "/api/admin/users",
            data={
                "username": "admin",
                "display_name": "Dup",
                "password": "pw123456",
                "csrf_token": csrf,
            },
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 409

    async def test_promote_and_demote(self):
        await self.make_admin()
        csrf = await self.csrf()
        resp = await self.client.post(
            "/api/admin/users",
            data={
                "username": "erin",
                "display_name": "Erin",
                "password": "pw123456",
                "csrf_token": csrf,
            },
            headers=JSON_HEADERS,
        )
        user_id = resp.json()["user"]["id"]

        resp = await self.client.post(
            f"/api/admin/users/{user_id}/promote",
            data={"csrf_token": csrf},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["is_admin"] is True

        # Promoted user can use admin endpoints
        await self.login("erin", "pw123456")
        resp = await self.client.get("/api/admin/users", headers=JSON_HEADERS)
        assert resp.status_code == 200

        await self.login("admin", "adminpass123")
        csrf = await self.csrf()
        resp = await self.client.post(
            f"/api/admin/users/{user_id}/demote",
            data={"csrf_token": csrf},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["is_admin"] is False

        # Demoted user loses admin access
        await self.login("erin", "pw123456")
        resp = await self.client.get("/api/admin/users", headers=JSON_HEADERS)
        assert resp.status_code == 403

    async def test_cannot_demote_self(self):
        await self.make_admin()
        csrf = await self.csrf()
        me_resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        me = me_resp.json()
        resp = await self.client.post(
            f"/api/admin/users/{me['id']}/demote",
            data={"csrf_token": csrf},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 403

    async def test_promote_unknown_user_404(self):
        await self.make_admin()
        csrf = await self.csrf()
        resp = await self.client.post(
            "/api/admin/users/999/promote",
            data={"csrf_token": csrf},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 404

    async def test_admin_create_validates_input(self):
        await self.make_admin()
        resp = await self.client.post(
            "/api/admin/users",
            data={"username": "BAD!", "display_name": "X", "password": "password123"},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 422
        resp = await self.client.post(
            "/api/admin/users",
            data={"username": "okname", "display_name": "X", "password": "short"},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 422


class TestInvites(AdminTestCase):
    async def test_create_and_list_invites(self):
        await self.make_admin()
        resp = await self.client.post(
            "/api/admin/invites", data={}, headers=JSON_HEADERS
        )
        assert resp.status_code == 200
        invite = resp.json()["invite"]
        assert invite["code"]
        assert invite["register_url"].endswith(f"?code={invite['code']}")
        assert invite["used_by"] is None

        resp = await self.client.post(
            "/api/admin/invites",
            data={"expires_in_days": "7"},
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["invite"]["expires_at"] is not None

        resp = await self.client.get("/api/admin/invites", headers=JSON_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["registration_mode"] == "open"
        assert len(data["invites"]) == 2

    async def test_revoke_invite(self):
        await self.make_admin()
        resp = await self.client.post(
            "/api/admin/invites", data={}, headers=JSON_HEADERS
        )
        invite_id = resp.json()["invite"]["id"]
        resp = await self.client.delete(
            f"/api/admin/invites/{invite_id}", headers=JSON_HEADERS
        )
        assert resp.status_code == 200
        # Already gone — 404 on a second revoke.
        resp = await self.client.delete(
            f"/api/admin/invites/{invite_id}", headers=JSON_HEADERS
        )
        assert resp.status_code == 404

    async def test_invite_endpoints_require_admin(self):
        resp = await self.client.get("/api/admin/invites", headers=JSON_HEADERS)
        assert resp.status_code == 401
        await self.make_admin()
        await self.register_user(username="regular")  # session now non-admin
        resp = await self.client.post(
            "/api/admin/invites", data={}, headers=JSON_HEADERS
        )
        assert resp.status_code == 403
        resp = await self.client.get("/api/admin/invites", headers=JSON_HEADERS)
        assert resp.status_code == 403


class TestModeration(AdminTestCase):
    async def _create_user(self, username: str = "victim") -> int:
        await self.make_admin()
        resp = await self.client.post(
            "/api/admin/users",
            data={
                "username": username,
                "display_name": username.title(),
                "password": "password123",
            },
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 200
        return resp.json()["user"]["id"]

    async def test_suspend_blocks_login_and_invalidates_session(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        uid = await self._create_user()
        victim = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        )
        try:
            resp = await victim.post(
                "/login",
                data={"username": "victim", "password": "password123"},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            resp = await victim.get("/api/me", headers=JSON_HEADERS)
            assert resp.status_code == 200

            # Admin suspends the account.
            resp = await self.client.post(
                f"/api/admin/users/{uid}/suspend", data={}, headers=JSON_HEADERS
            )
            assert resp.status_code == 200
            assert resp.json()["user"]["is_suspended"] is True

            # The existing session is invalidated...
            resp = await victim.get("/api/me", headers=JSON_HEADERS)
            assert resp.status_code == 401
            # ...and login is blocked.
            resp = await victim.post(
                "/login",
                data={"username": "victim", "password": "password123"},
                follow_redirects=False,
            )
            assert resp.status_code == 403
            assert "suspended" in resp.text.lower()

            # Unsuspend restores access.
            resp = await self.client.post(
                f"/api/admin/users/{uid}/unsuspend", data={}, headers=JSON_HEADERS
            )
            assert resp.status_code == 200
            resp = await victim.post(
                "/login",
                data={"username": "victim", "password": "password123"},
                follow_redirects=False,
            )
            assert resp.status_code == 303
        finally:
            await victim.aclose()

    async def test_delete_user_removes_account_and_reviews(self):
        from app.db import create_review, get_actor_by_id, get_reviews

        uid = await self._create_user()
        await create_review(
            actor_id=uid,
            ap_id="http://testserver/review/del-1",
            content="spam",
            rating=1,
            latitude=0.0,
            longitude=0.0,
        )
        assert len(await get_reviews()) == 1

        resp = await self.client.delete(f"/api/admin/users/{uid}", headers=JSON_HEADERS)
        assert resp.status_code == 200
        assert await get_actor_by_id(uid) is None
        assert len(await get_reviews()) == 0

    async def test_cannot_moderate_self_or_last_admin(self):
        await self.make_admin()
        me = (await self.client.get("/api/me", headers=JSON_HEADERS)).json()
        resp = await self.client.delete(
            f"/api/admin/users/{me['id']}", headers=JSON_HEADERS
        )
        assert resp.status_code == 403
        resp = await self.client.post(
            f"/api/admin/users/{me['id']}/suspend", data={}, headers=JSON_HEADERS
        )
        assert resp.status_code == 403

    async def test_moderation_endpoints_require_admin(self):
        uid = await self._create_user()
        await self.register_user(username="regular")  # session now non-admin
        for method, path in [
            ("post", f"/api/admin/users/{uid}/suspend"),
            ("post", f"/api/admin/users/{uid}/unsuspend"),
            ("delete", f"/api/admin/users/{uid}"),
        ]:
            resp = await getattr(self.client, method)(path, headers=JSON_HEADERS)
            assert resp.status_code == 403, path
