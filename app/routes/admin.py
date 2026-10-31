"""Admin JSON API — account moderation and invite codes (admin session only)."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.auth import get_current_admin
from app.config import config
from app.db import (
    count_admins,
    create_invite,
    delete_actor,
    delete_invite,
    get_actor_by_id,
    get_actor_by_username,
    hash_password,
    list_invites,
    list_local_actors,
    set_actor_admin,
    set_actor_suspended,
)
from app.forms import RegisterForm, first_validation_error
from app.routes.activitypub import create_local_actor

logger = logging.getLogger("pheme")

router = APIRouter()


def _public_user(actor: dict[str, Any]) -> dict[str, Any]:
    """Actor row reduced to the fields the admin UI needs (no keys/hashes)."""
    return {
        "id": actor["id"],
        "username": actor["username"],
        "display_name": actor["display_name"],
        "is_admin": bool(actor.get("is_admin")),
        "is_suspended": bool(actor.get("is_suspended")),
        "created_at": actor["created_at"],
    }


@router.get("/api/admin/users")
async def api_admin_list_users(
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """List all local accounts with their admin flag (admin only)."""
    users = [_public_user(a) for a in await list_local_actors()]
    return JSONResponse({"users": users, "admin_count": await count_admins()})


@router.post("/api/admin/users")
async def api_admin_create_user(
    admin: dict = Depends(get_current_admin),
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    is_admin: bool = Form(False),
) -> JSONResponse:
    """Create a new local account, optionally as an admin (admin only)."""
    try:
        form = RegisterForm(
            username=username, display_name=display_name, password=password
        )
    except ValidationError as exc:
        raise HTTPException(422, first_validation_error(exc)) from exc

    existing = await get_actor_by_username(form.username)
    if existing:
        raise HTTPException(409, "Username already taken")

    actor = await create_local_actor(
        username=form.username,
        display_name=form.display_name,
        password_hash=hash_password(form.password),
        is_admin=is_admin,
    )
    logger.info(
        "Admin '%s' created account '%s' (is_admin=%s)",
        admin["username"],
        username,
        is_admin,
    )
    return JSONResponse({"status": "created", "user": _public_user(actor)})


@router.post("/api/admin/users/{user_id}/promote")
async def api_admin_promote(
    user_id: int,
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Grant admin to a local account (admin only)."""
    target = await get_actor_by_id(user_id)
    if not target or not target.get("is_local"):
        raise HTTPException(404, "User not found")
    await set_actor_admin(user_id, True)
    logger.info(
        "Admin '%s' promoted '%s' to admin", admin["username"], target["username"]
    )
    promoted = target | {"is_admin": 1}
    return JSONResponse({"status": "promoted", "user": _public_user(promoted)})


@router.post("/api/admin/users/{user_id}/demote")
async def api_admin_demote(
    user_id: int,
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Revoke admin from a local account (admin only).

    An admin cannot demote themselves — that would risk locking the
    server out of admin access entirely.
    """
    if user_id == admin["id"]:
        raise HTTPException(403, "You cannot demote yourself")
    target = await get_actor_by_id(user_id)
    if not target or not target.get("is_local"):
        raise HTTPException(404, "User not found")
    await set_actor_admin(user_id, False)
    logger.info("Admin '%s' demoted '%s'", admin["username"], target["username"])
    demoted = target | {"is_admin": 0}
    return JSONResponse({"status": "demoted", "user": _public_user(demoted)})


async def _moderation_target(user_id: int, admin: dict) -> dict:
    """Fetch the target local actor for a moderation action, with guards."""
    if user_id == admin["id"]:
        raise HTTPException(403, "You cannot moderate your own account")
    target = await get_actor_by_id(user_id)
    if not target or not target.get("is_local"):
        raise HTTPException(404, "User not found")
    if target.get("is_admin") and await count_admins() <= 1:
        raise HTTPException(403, "Cannot remove the last admin")
    return target


@router.post("/api/admin/users/{user_id}/suspend")
async def api_admin_suspend(
    user_id: int,
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Suspend a local account (admin only) — sessions are invalidated and
    login is blocked until unsuspended."""
    target = await _moderation_target(user_id, admin)
    await set_actor_suspended(user_id, True)
    logger.info("Admin '%s' suspended '%s'", admin["username"], target["username"])
    suspended = target | {"is_suspended": 1}
    return JSONResponse({"status": "suspended", "user": _public_user(suspended)})


@router.post("/api/admin/users/{user_id}/unsuspend")
async def api_admin_unsuspend(
    user_id: int,
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Lift a suspension (admin only)."""
    target = await get_actor_by_id(user_id)
    if not target or not target.get("is_local"):
        raise HTTPException(404, "User not found")
    await set_actor_suspended(user_id, False)
    logger.info("Admin '%s' unsuspended '%s'", admin["username"], target["username"])
    unsuspended = target | {"is_suspended": 0}
    return JSONResponse({"status": "unsuspended", "user": _public_user(unsuspended)})


@router.delete("/api/admin/users/{user_id}")
async def api_admin_delete_user(
    user_id: int,
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Delete a local account and all its local content (admin only)."""
    target = await _moderation_target(user_id, admin)
    await delete_actor(user_id)
    logger.info("Admin '%s' deleted '%s'", admin["username"], target["username"])
    return JSONResponse({"status": "deleted", "user_id": user_id})


# ── invite codes (registration mode "invite") ───────────────────────────


def _public_invite(invite: dict[str, Any]) -> dict[str, Any]:
    """Invite row reduced to what the admin UI needs, plus a shareable URL."""
    return {
        "id": invite["id"],
        "code": invite["code"],
        "created_by": invite.get("created_by_username"),
        "used_by": invite.get("used_by_username"),
        "used_at": invite["used_at"],
        "created_at": invite["created_at"],
        "expires_at": invite["expires_at"],
        "register_url": f"{config.base_url}/register?code={invite['code']}",
    }


@router.get("/api/admin/invites")
async def api_admin_list_invites(
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """List all invite codes (admin only)."""
    invites = await list_invites()
    return JSONResponse(
        {
            "invites": [_public_invite(i) for i in invites],
            "registration_mode": config.registration_mode,
        }
    )


@router.post("/api/admin/invites")
async def api_admin_create_invite(
    expires_in_days: int | None = Form(None),
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Create a one-time invite code (admin only), optionally expiring."""
    invite = await create_invite(admin["id"], expires_in_days)
    logger.info(
        "Admin '%s' created an invite code (expires_in_days=%s)",
        admin["username"],
        expires_in_days,
    )
    return JSONResponse({"status": "created", "invite": _public_invite(invite)})


@router.delete("/api/admin/invites/{invite_id}")
async def api_admin_delete_invite(
    invite_id: int,
    admin: dict = Depends(get_current_admin),
) -> JSONResponse:
    """Revoke an unused invite code (admin only)."""
    if not await delete_invite(invite_id):
        raise HTTPException(404, "Invite not found or already used")
    logger.info("Admin '%s' revoked invite #%s", admin["username"], invite_id)
    return JSONResponse({"status": "deleted"})
