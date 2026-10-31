"""
FastAPI application — entry point.

Wires together:
  • routes/activitypub  — WebFinger, Actor, Inbox, Outbox, Followers
  • routes/web          — server-rendered pages (auth forms, review detail)
  • routes/api          — review CRUD, geocode proxy, follow, /api/me
  • react-app/dist      — the React SPA (map page) + SPA catch-all
"""

import logging
import os
import re
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware
from starlette_csrf.middleware import CSRFMiddleware

from app.auth import _LoginRequired, login_required_handler
from app.config import config
from app.db import close_db, init_db
from app.ratelimit import limiter
from app.routes.activitypub import router as activitypub_router
from app.routes.api import router as api_router
from app.routes.web import router as web_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Own the database connection: open at startup, close on shutdown."""
    await init_db()
    yield
    await close_db()


app = FastAPI(title="Federated Reviews", version="0.1.0", lifespan=lifespan)

# ── middleware ──────────────────────────────────────────────────────────

app.add_middleware(
    SessionMiddleware,
    secret_key=config.secret_key,
    max_age=config.session_max_age,
    same_site="lax",
    # Mark the session cookie Secure when the server is served over HTTPS,
    # so it is never sent over plain HTTP.
    https_only=config.base_url.startswith("https://"),
)

# CSRF protection via the starlette-csrf library (double-submit cookie):
# every unsafe request that carries the session cookie must present an
# x-csrftoken header matching the signed csrftoken cookie. Exempt:
# ActivityPub inboxes (HTTP-Signature auth), the one-time bootstrap endpoint,
# and the plain-HTML-form endpoints /login, /register, /logout — forms cannot
# send headers, and browsers may carry a stale session cookie from before
# this middleware existed, which must not lock users out. These endpoints
# only create/destroy a session (no data changes), and the session cookie is
# SameSite=Lax, so cross-site posts carry no session cookie anyway. The
# csrftoken cookie is not HttpOnly so the SPA can read it and send the header.
app.add_middleware(
    CSRFMiddleware,
    secret=config.secret_key,
    sensitive_cookies={"session"},
    exempt_urls=[
        re.compile(r"^/inbox$"),
        re.compile(r"^/actor/[^/]+/inbox$"),
        re.compile(r"^/api/bootstrap$"),
        re.compile(r"^/login$"),
        re.compile(r"^/register$"),
        re.compile(r"^/logout$"),
    ],
    cookie_secure=config.base_url.startswith("https://"),
    cookie_samesite="lax",
    cookie_httponly=False,
)

# Rate limiter (slowapi) — auth routes opt in with @limiter.limit(...)
app.state.limiter = limiter


async def _rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    """429 handler — delegates to slowapi's handler (typed for Exception)."""
    return _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))


app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded)

# ── exception handlers ─────────────────────────────────────────────────

app.add_exception_handler(_LoginRequired, login_required_handler)

# ── static files ────────────────────────────────────────────────────────

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(_REPO_ROOT, "app", "static")),
    name="static",
)

# ── routers ─────────────────────────────────────────────────────────────

app.include_router(activitypub_router)
app.include_router(web_router)
app.include_router(api_router)

# ── React SPA (react-app/dist) ──────────────────────────────────────────
# Registered LAST so the catch-all can never shadow the API, ActivityPub,
# auth or /static routes above.

_DIST_DIR = os.path.join(_REPO_ROOT, "react-app", "dist")
_ASSETS_DIR = os.path.join(_DIST_DIR, "assets")
_INDEX_HTML = os.path.join(_DIST_DIR, "index.html")

if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="react-assets")


@app.get("/{full_path:path}", response_class=FileResponse)
async def spa_catchall(full_path: str):
    """SPA catch-all — serve the React app for any otherwise-unmatched GET.

    API / ActivityPub paths must 404 as JSON, not return the app shell —
    clients need to distinguish "route does not exist" from the SPA.
    """
    if full_path.startswith(("api/", "actor/", ".well-known/", "inbox")):
        raise HTTPException(status_code=404, detail="Not found")
    if os.path.isfile(_INDEX_HTML):
        return FileResponse(_INDEX_HTML)
    raise HTTPException(
        status_code=404,
        detail="React app not built — run `npm run build` in react-app/",
    )


# ── entry point ─────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for `fedreviews` CLI command."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        reload=config.reload,
    )


if __name__ == "__main__":
    main()
