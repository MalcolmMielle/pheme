"""
Shared test helpers — the stdlib-unittest replacement for the old pytest
``conftest.py`` fixtures.
"""

import asyncio
import os
import unittest

import httpx
from httpx import ASGITransport, AsyncClient


async def get_csrf_token(client: AsyncClient, path: str = "/login") -> str:
    """Fetch a page (which sets the ``csrftoken`` cookie) and return its value.

    CSRF protection is starlette-csrf's double-submit cookie: the token lives
    in the ``csrftoken`` cookie and must be sent back as the ``X-CSRFToken``
    header. The request hook installed in ``AsyncTestCase`` attaches the
    header automatically; this helper returns the raw value for tests that
    want to reference it explicitly.
    """
    await client.get(path)
    token = client.cookies.get("csrftoken")
    if not token:
        raise ValueError(f"No csrftoken cookie after GET {path}")
    return token


class AsyncTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for async tests.

    Each test gets a fresh database and an HTTP client connected to the
    FastAPI app over ASGI — the old ``client`` and ``db`` fixtures.
    """

    client: AsyncClient

    async def asyncSetUp(self) -> None:
        # IsolatedAsyncioTestCase runs the loop in debug mode, which logs a
        # warning for every callback slower than 0.1s (bcrypt hashing, the
        # first app import) — noise in a test run. Run the loop in normal
        # mode, like the application itself does.
        asyncio.get_running_loop().set_debug(False)

        # `python -m unittest discover` from the repo root imports every
        # package it walks — including `app.*` — before it reaches `tests/`,
        # so `app.config` can already be cached with production defaults by
        # the time a test runs. Env vars alone are too late for the cached
        # singleton, so re-point it at the test configuration as well.
        from app.config import config

        config.base_url = os.environ["BASE_URL"]
        config.database_path = os.environ["DATABASE_PATH"]
        config.secret_key = os.environ["SECRET_KEY"]

        # Fresh database per test. httpx's ASGITransport does not run the
        # app lifespan, so tests drive init_db()/close_db() themselves —
        # and must close the old connection first, since an aiosqlite
        # connection is bound to the event loop that created it.
        from app.db import close_db, init_db

        await close_db()

        db_path = os.environ["DATABASE_PATH"]
        if os.path.exists(db_path):
            os.remove(db_path)
        await init_db()

        from app.main import app

        # Rate limiting is off by default in tests (all requests share one
        # test IP); the rate-limit test re-enables it explicitly.
        app.state.limiter.enabled = False

        transport = ASGITransport(app=app)
        self.client = AsyncClient(transport=transport, base_url="http://testserver")

        async def _add_csrf_header(request: httpx.Request) -> None:
            # Mimic the browser + SPA: send the double-submit X-CSRFToken
            # header whenever the csrftoken cookie is present — unless the
            # test set the header explicitly (to test a bad token).
            token = self.client.cookies.get("csrftoken")
            if token and "X-CSRFToken" not in request.headers:
                request.headers["X-CSRFToken"] = token

        self.client.event_hooks["request"].append(_add_csrf_header)

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

        from app.db import close_db

        await close_db()

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
