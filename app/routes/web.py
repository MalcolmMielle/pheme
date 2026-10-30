"""
Web UI routes — server-rendered HTML pages.

The map page itself is the React SPA in react-app/ (built to react-app/dist
and served by app/main.py); these routes cover the standalone review page
and the login/register/logout forms.
"""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import config
from app.db import (
    get_actor_by_username,
    get_reviews,
    hash_password,
    verify_password,
)
from app.routes.activitypub import create_local_actor

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── review detail page ──────────────────────────────────────────────────


@router.get("/review/{review_id}", response_class=HTMLResponse)
async def review_page(request: Request, review_id: int) -> HTMLResponse:
    """Single review detail page."""
    reviews = await get_reviews(limit=500)
    review = next((r for r in reviews if r["id"] == review_id), None)
    if not review:
        raise HTTPException(404, "Review not found")
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={"review": review, "base_url": config.base_url},
    )


# ── auth routes ────────────────────────────────────────────────────────


@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request) -> HTMLResponse:
    """Show the registration form."""
    return templates.TemplateResponse(request=request, name="register.html", context={})


@router.post("/register", response_model=None)
async def register(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    """Create a new local actor with a password and log in."""
    existing = await get_actor_by_username(username)
    if existing:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Username already taken."},
            status_code=409,
        )

    actor = await create_local_actor(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
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
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    """Verify credentials and create a session."""
    actor = await get_actor_by_username(username)
    if not actor or not actor.get("password_hash"):
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
