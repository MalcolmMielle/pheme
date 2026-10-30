"""
CSRF protection middleware.

Pure ASGI middleware that validates a ``csrf_token`` form field against
the token stored in the session.  ActivityPub inbox endpoints are exempt
(they use HTTP Signatures instead).

Usage in ``main.py`` (add *before* SessionMiddleware so it runs after):

    app.add_middleware(CSRFMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=config.secret_key)
"""

import secrets
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CSRFMiddleware:
    """Validate CSRF tokens on form-encoded POST requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        session: dict = scope.setdefault("session", {})

        # Ensure a CSRF token exists in the session
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)

        # Only validate on POST requests
        if scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        # Skip ActivityPub inbox endpoints (they use HTTP Signatures)
        # and the one-time bootstrap endpoint (called via curl)
        path: str = scope.get("path", "")
        is_inbox = path == "/inbox" or (
            path.startswith("/actor/") and path.endswith("/inbox")
        )
        if is_inbox or path == "/api/bootstrap":
            await self.app(scope, receive, send)
            return

        # Only check form-encoded POSTs
        content_type = ""
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-type":
                content_type = value.decode("latin-1")
                break

        if "application/x-www-form-urlencoded" not in content_type:
            await self.app(scope, receive, send)
            return

        # Read the full body
        body = b""
        while True:
            message: Message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break

        # Parse and validate CSRF token
        form_data = parse_qs(body.decode("utf-8"))
        submitted_token = form_data.get("csrf_token", [""])[0]
        session_token = session.get("csrf_token", "")

        if not submitted_token or submitted_token != session_token:
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"CSRF token validation failed",
                }
            )
            return

        # Pass the cached body downstream
        body_sent = False

        async def receive_cached() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, receive_cached, send)
