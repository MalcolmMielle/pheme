"""
Federation delivery — send activities to remote servers' inboxes.

When a local actor publishes a Create activity (wrapping a Review),
this module fans out signed POSTs to every follower's inbox.

Flow:

  1. Look up the list of remote inbox URLs that follow this actor.
  2. For each inbox:
     a. Sign the POST body with the actor's private key.
     b. POST the JSON to the remote inbox.
     c. Log success / failure (we don't retry in MVP).
"""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.activitypub.signing import sign_request

logger = logging.getLogger("federated-reviews.delivery")


async def deliver_to_inbox(
    inbox_url: str,
    activity: dict[str, Any],
    actor_key_id: str,
    actor_private_key_pem: str,
) -> bool:
    """Deliver a single activity to one remote inbox.

    Returns ``True`` on success (HTTP 2xx/202), ``False`` on failure.
    """
    body = json.dumps(activity).encode()
    headers = sign_request(
        method="POST",
        url=inbox_url,
        body=body,
        key_id=actor_key_id,
        private_key_pem=actor_private_key_pem,
    )
    headers["Content-Type"] = "application/activity+json"

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(inbox_url, content=body, headers=headers)
            if 200 <= resp.status_code < 300 or resp.status_code == 202:
                logger.info("Delivered to %s → %d", inbox_url, resp.status_code)
                return True
            else:
                logger.warning(
                    "Delivery to %s failed: %d %s",
                    inbox_url,
                    resp.status_code,
                    resp.text[:200],
                )
                return False
        except httpx.RequestError as exc:
            logger.warning("Delivery to %s error: %s", inbox_url, exc)
            return False


async def fanout_activity(
    activity: dict[str, Any],
    actor_key_id: str,
    actor_private_key_pem: str,
    inbox_urls: list[str],
) -> dict[str, int]:
    """Deliver an activity to every inbox in ``inbox_urls``, in parallel.

    Returns ``{"ok": N, "fail": M}``.
    """
    results = await asyncio.gather(
        *(
            deliver_to_inbox(url, activity, actor_key_id, actor_private_key_pem)
            for url in inbox_urls
        )
    )
    ok = sum(1 for success in results if success)
    return {"ok": ok, "fail": len(results) - ok}
