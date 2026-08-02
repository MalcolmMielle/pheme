"""
Authentication — session-based user dependency.

Uses Starlette's SessionMiddleware so each request carries a signed
cookie with the logged-in user's actor id.
"""

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.db import get_actor_by_id


async def get_current_user(request: Request):
    """FastAPI dependency — return the current actor row, or redirect to /login."""
    user_id = request.session.get("user_id")
    if user_id is None:
        raise _LoginRequired()
    actor = await get_actor_by_id(user_id)
    if actor is None:
        request.session.clear()
        raise _LoginRequired()
    return actor


class _LoginRequired(Exception):
    pass


def login_required_handler(request: Request, _exc: _LoginRequired):
    """Convert _LoginRequired into a redirect to /login."""
    return RedirectResponse(url="/login", status_code=303)
