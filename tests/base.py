"""
Shared test helpers — the stdlib-unittest replacement for the old pytest
``conftest.py`` fixtures.
"""

import os
import re
import unittest

from httpx import ASGITransport, AsyncClient


async def get_csrf_token(client: AsyncClient, path: str = "/login") -> str:
    """Fetch a page and extract the CSRF token from the hidden form field."""
    resp = await client.get(path)
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    if not match:
        raise ValueError(f"No CSRF token found on {path}")
    return match.group(1)


class AsyncTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for async tests.

    Each test gets a fresh database and an HTTP client connected to the
    FastAPI app over ASGI — the old ``client`` and ``db`` fixtures.
    """

    client: AsyncClient

    async def asyncSetUp(self) -> None:
        # `python -m unittest discover` from the repo root imports every
        # package it walks — including `app.*` — before it reaches `tests/`,
        # so `app.config` can already be cached with production defaults by
        # the time a test runs. Env vars alone are too late for the cached
        # singleton, so re-point it at the test configuration as well.
        from app.config import config

        config.base_url = os.environ["BASE_URL"]
        config.database_path = os.environ["DATABASE_PATH"]
        config.secret_key = os.environ["SECRET_KEY"]

        import app.db.connection as conn_module

        if conn_module._db is not None:
            await conn_module._db.close()
            conn_module._db = None

        db_path = os.environ["DATABASE_PATH"]
        if os.path.exists(db_path):
            os.remove(db_path)

        from app.main import app

        transport = ASGITransport(app=app)
        self.client = AsyncClient(transport=transport, base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

        import app.db.connection as conn_module

        if conn_module._db is not None:
            await conn_module._db.close()
            conn_module._db = None

    async def register_user(
        self,
        username: str = "testuser",
        password: str = "testpass123",
        display_name: str = "Test User",
    ) -> dict[str, str]:
        """Register a user via the web form and return their credentials."""
        csrf = await get_csrf_token(self.client, "/register")
        resp = await self.client.post(
            "/register",
            data={
                "username": username,
                "display_name": display_name,
                "password": password,
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        return {"username": username, "password": password}
