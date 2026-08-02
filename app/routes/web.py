"""
Web UI routes — server-rendered HTML pages.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import config
from app.db import get_reviews, list_local_actors

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Main page — the map-based review browser."""
    reviews = await get_reviews(limit=200)
    actors = await list_local_actors()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "reviews": reviews,
            "actors": actors,
            "base_url": config.base_url,
        },
    )


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
