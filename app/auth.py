"""
Authentication — session-based user dependency.

Uses Starlette's SessionMiddleware so each request carries a signed
cookie with the logged-in user's actor id.
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.db import get_actor_by_id


async def get_current_user(request: Request):
    """FastAPI dependency — return the current actor row, or raise _LoginRequired.

    Suspended accounts are treated like logged-out: their session is
    cleared and every protected endpoint rejects them.
    """
    user_id = request.session.get("user_id")
    if user_id is None:
        raise _LoginRequired()
    actor = await get_actor_by_id(user_id)
    if actor is None or actor.get("is_suspended"):
        request.session.clear()
        raise _LoginRequired()
    return actor


async def get_current_admin(request: Request):
    """FastAPI dependency — current user, but only if they are an admin."""
    actor = await get_current_user(request)
    if not actor.get("is_admin"):
        raise HTTPException(403, "Admin access required")
    return actor


class _LoginRequired(Exception):
    pass


def login_required_handler(
    request: Request, exc: Exception
) -> JSONResponse | RedirectResponse:
    """Convert _LoginRequired into a redirect to /login.

    API/fetch callers (Accept: application/json, or an X-Requested-With
    header) get a 401 JSON response instead: a 303 would be followed by
    fetch() and surface an HTML login page inside the SPA.
    """
    accept = request.headers.get("accept", "")
    wants_json = (
        "application/json" in accept
        or request.headers.get("x-requested-with") == "XMLHttpRequest"
    )
    if wants_json:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return RedirectResponse(url="/login", status_code=303)
