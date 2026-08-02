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

from app.routes.activitypub import router as activitypub_router
from app.routes.api import router as api_router
from app.routes.web import router as web_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Federated Reviews", version="0.1.0")

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

    from app.config import config

    uvicorn.run("app.main:app", host=config.host, port=config.port, reload=True)


if __name__ == "__main__":
    main()
