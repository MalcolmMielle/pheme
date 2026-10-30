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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import _LoginRequired, login_required_handler
from app.config import config
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
    """SPA catch-all — serve the React app for any otherwise-unmatched GET."""
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
