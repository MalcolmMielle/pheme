"""
Web UI routes — server-rendered HTML pages.

The map page itself is the React SPA in react-app/ (built to react-app/dist
and served by app/main.py); these routes cover the standalone review page
and the login/register/logout forms.
"""

import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.config import config
from app.db import (
    get_actor_by_username,
    get_review_by_id,
    hash_password,
    verify_password,
)
from app.forms import RegisterForm, first_validation_error
from app.ratelimit import limiter
from app.routes.activitypub import create_local_actor

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Hashed once at startup; used to equalize login timing for unknown usernames
# so the response time doesn't reveal whether an account exists.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


# ── review detail page ──────────────────────────────────────────────────


def _format_review_date(value: str) -> str:
    """Render the stored UTC timestamp ("2026-08-02 21:45:00") readably.

    Federated rows always use this format (the inbox converts the remote
    ISO-8601 ``published`` to it), but fall back to the raw value if the
    string ever differs.
    """
    try:
        dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return value
    return dt.strftime("%d %b %Y, %H:%M UTC")


@router.get("/review/{review_id}", response_class=HTMLResponse)
async def review_page(request: Request, review_id: int) -> HTMLResponse:
    """Single review detail page."""
    review = await get_review_by_id(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    # The author's server, derived from their actor URI ("user@server").
    actor_domain = urlparse(review["actor_uri"]).netloc
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "review": review,
            "review_date": _format_review_date(review["created_at"]),
            "base_url": config.base_url,
            "actor_domain": actor_domain,
        },
    )


# ── auth routes ────────────────────────────────────────────────────────


@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request) -> HTMLResponse:
    """Show the registration form."""
    return templates.TemplateResponse(request=request, name="register.html", context={})


@router.post("/register", response_model=None)
@limiter.limit("3/minute")
async def register(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    """Create a new local actor with a password and log in."""
    try:
        form = RegisterForm(
            username=username, display_name=display_name, password=password
        )
    except ValidationError as exc:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": first_validation_error(exc)},
            status_code=400,
        )

    existing = await get_actor_by_username(form.username)
    if existing:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Username already taken."},
            status_code=409,
        )

    actor = await create_local_actor(
        username=form.username,
        display_name=form.display_name,
        password_hash=hash_password(form.password),
    )

    request.session["user_id"] = actor["id"]
    return RedirectResponse(url="/", status_code=303)


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_form(request: Request) -> HTMLResponse | RedirectResponse:
    """Show the login form (redirect to / if already logged in)."""
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={})


@router.post("/login", response_model=None)
@limiter.limit("5/minute")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    """Verify credentials and create a session."""
    actor = await get_actor_by_username(username)
    if not actor or not actor.get("password_hash"):
        # Burn a bcrypt check anyway so the response time doesn't reveal
        # whether the username exists.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password."},
            status_code=401,
        )

    if not verify_password(password, actor["password_hash"]):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password."},
            status_code=401,
        )

    request.session["user_id"] = actor["id"]
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear the session."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
