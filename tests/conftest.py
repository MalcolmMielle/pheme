"""
Shared test fixtures.

Each test gets a fresh in-memory SQLite database and a clean app instance.
"""

import os
import re
import tempfile
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Use a temp directory for test databases
_tmpdir = tempfile.mkdtemp(prefix="fedreviews-test-")
os.environ["DATABASE_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["BASE_URL"] = "http://testserver"


async def get_csrf_token(client: AsyncClient, path: str = "/login") -> str:
    """Fetch a page and extract the CSRF token from the hidden form field."""
    resp = await client.get(path)
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    if not match:
        raise ValueError(f"No CSRF token found on {path}")
    return match.group(1)


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Return an async HTTP client connected to the FastAPI app."""
    import app.db.connection as conn_module

    if conn_module._db is not None:
        await conn_module._db.close()
        conn_module._db = None

    if os.path.exists(os.environ["DATABASE_PATH"]):
        os.remove(os.environ["DATABASE_PATH"])

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture
async def db():
    """Return a fresh database connection."""
    import app.db.connection as conn_module

    if conn_module._db is not None:
        await conn_module._db.close()
        conn_module._db = None

    if os.path.exists(os.environ["DATABASE_PATH"]):
        os.remove(os.environ["DATABASE_PATH"])

    conn = await conn_module.get_db()
    yield conn
    await conn.close()
    conn_module._db = None


@pytest_asyncio.fixture
async def registered_user(client: AsyncClient) -> dict:
    """Register a test user via the web form and return their credentials."""
    csrf = await get_csrf_token(client, "/register")
    resp = await client.post(
        "/register",
        data={
            "username": "testuser",
            "display_name": "Test User",
            "password": "testpass123",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return {"username": "testuser", "password": "testpass123"}


@pytest_asyncio.fixture
async def actor_in_db(db):
    """Create a test actor directly in the database and return the row."""
    from app.activitypub.signing import generate_keypair
    from app.db import create_actor, hash_password

    priv, pub = generate_keypair()
    base = "http://testserver/actor/testuser"
    actor = await create_actor(
        username="testuser",
        display_name="Test User",
        summary="A test user",
        private_key_pem=priv,
        public_key_pem=pub,
        actor_uri=base,
        inbox_uri=f"{base}/inbox",
        outbox_uri=f"{base}/outbox",
        followers_uri=f"{base}/followers",
        following_uri=f"{base}/following",
        password_hash=hash_password("testpass123"),
    )
    return actor
