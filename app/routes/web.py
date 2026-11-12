"""
Web UI routes — server-rendered HTML pages.

The map page itself is the React SPA in react-app/ (built to react-app/dist
and served by app/main.py); these routes cover the standalone review page
and the login/register/logout forms.
"""

import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.config import config
from app.db import (
    consume_invite,
    delete_actor,
    get_actor_by_username,
    get_valid_invite,
    hash_password,
    verify_password,
)
from app.reviews import reviews
from app.forms import RegisterForm, first_validation_error
from app.ratelimit import limiter
from app.routes.activitypub import create_local_actor
from app.routes.activitypub.helpers import sqlite_to_datetime

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Hashed once at startup; used to equalize login timing for unknown usernames
# so the response time doesn't reveal whether an account exists.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def _form_error(
    request: Request, template: str, context: dict, status: int
) -> HTMLResponse:
    """Re-render an auth form (login/register) with an error in the context."""
    return templates.TemplateResponse(
        request=request, name=template, context=context, status_code=status
    )


# ── review detail page ──────────────────────────────────────────────────


def _format_review_date(value: str) -> str:
    """Render the stored UTC timestamp ("2026-08-02 21:45:00") readably.

    Federated rows always use this format (the inbox converts the remote
    ISO-8601 ``published`` to it), but fall back to the raw value if the
    string ever differs.
    """
    try:
        dt = sqlite_to_datetime(value)
    except ValueError:
        return value
    return dt.strftime("%d %b %Y, %H:%M UTC")


@router.get("/review/{review_id}", response_class=HTMLResponse)
async def review_page(request: Request, review_id: int) -> HTMLResponse:
    """Single review detail page."""
    review = await reviews.by_id(review_id)
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


@router.get("/register", response_class=HTMLResponse, response_model=None)
async def register_form(
    request: Request, code: str = ""
) -> HTMLResponse | RedirectResponse:
    """Show the registration form (redirect to / if already logged in).

    ``code`` is a pre-filled invite code (``/register?code=...``).
    """
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={
            "registration_mode": config.registration_mode,
            "invite_code": code,
        },
    )


@router.post("/register", response_model=None)
@limiter.limit("3/minute")
async def register(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    code: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    """Create a new local actor with a password and log in.

    Honors REGISTRATION_MODE: "closed" refuses, "invite" requires a valid
    one-time invite code, "open" allows anyone.
    """
    mode = config.registration_mode
    if mode == "closed":
        return _form_error(
            request,
            "register.html",
            {
                "registration_mode": mode,
                "error": "Registration is closed on this server. "
                "Ask an admin for an account.",
            },
            403,
        )

    invite = None
    if mode == "invite":
        invite = await get_valid_invite(code)
        if invite is None:
            return _form_error(
                request,
                "register.html",
                {
                    "registration_mode": mode,
                    "error": "Invalid, used or expired invite code.",
                },
                403,
            )

    try:
        form = RegisterForm(
            username=username, display_name=display_name, password=password
        )
    except ValidationError as exc:
        return _form_error(
            request,
            "register.html",
            {"registration_mode": mode, "error": first_validation_error(exc)},
            400,
        )

    existing = await get_actor_by_username(form.username)
    if existing:
        return _form_error(
            request,
            "register.html",
            {"registration_mode": mode, "error": "Username already taken."},
            409,
        )

    actor = await create_local_actor(
        username=form.username,
        display_name=form.display_name,
        password_hash=hash_password(form.password),
    )

    if invite is not None and not await consume_invite(invite["id"], actor["id"]):
        # Lost a race on the one-time code — remove the account we just made.
        await delete_actor(actor["id"])
        return _form_error(
            request,
            "register.html",
            {
                "registration_mode": mode,
                "error": "Invite code was just used by someone else.",
            },
            403,
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
        return _form_error(
            request,
            "login.html",
            {"error": "Invalid username or password."},
            401,
        )

    if not verify_password(password, actor["password_hash"]):
        return _form_error(
            request,
            "login.html",
            {"error": "Invalid username or password."},
            401,
        )

    if actor.get("is_suspended"):
        return _form_error(
            request,
            "login.html",
            {"error": "This account has been suspended."},
            403,
        )

    request.session["user_id"] = actor["id"]
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear the session."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
