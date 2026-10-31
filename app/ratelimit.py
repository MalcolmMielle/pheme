"""Rate limiter shared by the app and the auth routes.

Uses slowapi (wraps the `limits` library) with per-client-IP keys. Mounted in
``main.py`` via ``app.state.limiter``; tests disable it with
``limiter.enabled = False``.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
