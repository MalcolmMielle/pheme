"""Invite codes for the "invite" registration mode.

Codes are generated with ``secrets`` (stdlib secure random) and stored
unique in the database; consumption is an atomic ``UPDATE ... WHERE
used_by IS NULL`` so a code can only ever be used once.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.connection import get_db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def create_invite(
    created_by: int, expires_in_days: int | None = None
) -> dict[str, Any]:
    """Create a new one-time invite code, optionally with an expiry."""
    code = secrets.token_urlsafe(24)
    expires_at = None
    if expires_in_days is not None:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        ).strftime("%Y-%m-%d %H:%M:%S")
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO invite_codes (code, created_by, expires_at) VALUES (?, ?, ?)",
        (code, created_by, expires_at),
    )
    await db.commit()
    row = await db.execute(
        "SELECT * FROM invite_codes WHERE id = ?", (cursor.lastrowid,)
    )
    return dict(await row.fetchone())  # type: ignore[arg-type]


async def get_valid_invite(code: str) -> dict[str, Any] | None:
    """Return the invite row if *code* exists, is unused and unexpired."""
    if not code:
        return None
    db = await get_db()
    row = await db.execute("SELECT * FROM invite_codes WHERE code = ?", (code,))
    result = await row.fetchone()
    if not result:
        return None
    invite = dict(result)
    if invite["used_by"] is not None:
        return None
    if invite["expires_at"] and invite["expires_at"] <= _now():
        return None
    return invite


async def consume_invite(invite_id: int, used_by: int) -> bool:
    """Atomically mark an invite as used. Returns False if already used."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE invite_codes SET used_by = ?, used_at = datetime('now') "
        "WHERE id = ? AND used_by IS NULL",
        (used_by, invite_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def list_invites() -> list[dict[str, Any]]:
    """All invite codes with the usernames of creator / user, newest first."""
    db = await get_db()
    rows = await db.execute(
        "SELECT i.*, a.username AS created_by_username, u.username AS used_by_username "
        "FROM invite_codes i "
        "LEFT JOIN actors a ON a.id = i.created_by "
        "LEFT JOIN actors u ON u.id = i.used_by "
        "ORDER BY i.created_at DESC, i.id DESC"
    )
    return [dict(r) for r in await rows.fetchall()]


async def delete_invite(invite_id: int) -> bool:
    """Delete an unused invite. Returns False if not found or already used."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM invite_codes WHERE id = ? AND used_by IS NULL", (invite_id,)
    )
    await db.commit()
    return cursor.rowcount > 0
