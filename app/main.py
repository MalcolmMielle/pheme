"""
FastAPI application — entry point.

Wires together:
  • routes/activitypub  — WebFinger, Actor, Inbox, Outbox, Followers
  • routes/web          — map-based review browser UI
  • routes/api          — review CRUD and bootstrap
"""

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import config
from app.auth import _LoginRequired, login_required_handler
from app.middleware import CSRFMiddleware
from app.routes.activitypub import router as activitypub_router
from app.routes.api import router as api_router
from app.routes.web import router as web_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Federated Reviews", version="0.1.0")

# ── middleware ──────────────────────────────────────────────────────────
# Order matters: CSRFMiddleware must be added BEFORE SessionMiddleware
# so that Session runs first (outermost) and populates scope["session"].

app.add_middleware(CSRFMiddleware)
app.add_middleware(SessionMiddleware, secret_key=config.secret_key)

# ── exception handlers ─────────────────────────────────────────────────

app.add_exception_handler(_LoginRequired, login_required_handler)

# ── static files ────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ── routers ─────────────────────────────────────────────────────────────

app.include_router(activitypub_router)
app.include_router(web_router)
app.include_router(api_router)


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
