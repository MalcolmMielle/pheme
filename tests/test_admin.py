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

    async def test_bootstrap_second_actor_is_not_admin(self):
        await self.client.post(
            "/api/bootstrap",
            data={"username": "admin", "display_name": "Admin", "password": "secret"},
        )
        await self.client.post(
            "/api/bootstrap",
            data={"username": "other", "display_name": "Other", "password": "secret"},
        )
        csrf = await get_csrf_token(self.client, "/login")
        resp = await self.client.post(
            "/login",
            data={"username": "other", "password": "secret", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        resp = await self.client.get("/api/me", headers=JSON_HEADERS)
        assert resp.json()["is_admin"] is False

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
            headers=JSON_HEADERS,
        )
        assert resp.status_code == 403  # CSRF middleware rejects before the route


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
