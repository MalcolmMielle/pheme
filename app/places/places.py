"""Places — the place manager for this server.

Owns the server-wide place configuration (the runtime ``PLACE_DECIMALS``
bucket precision), the Nominatim geocoding proxy, and the factory for
``Place`` objects: ``p = await places.at(lat, lng)`` builds the place object
for a clicked coordinate pair, loaded with its reviews from the DB via
``Place.reviews_at()`` (the load lives here, in ``at``, so
app/places/place.py never needs to import this module).

A place is a coordinate bucket: latitude/longitude rounded to ``decimals``
decimal places (~11 m per step at 4) — the runtime ``PLACE_DECIMALS`` env
var (app.config), exposed to the SPA via /api/meta, mirroring the map UI's
``placeKey`` (react-app/src/places.ts). The bucket key, the SQL fragment
(``Place.same_place_sql``) and equality (``Place.__eq__``) all live on
``Place``; rounding is half away from zero, matching SQLite's ROUND().
"""

import asyncio
import logging
import time
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.config import config
from app.places.place import Place

logger = logging.getLogger("pheme")


class Places:
    """Place manager: the bucket precision (runtime PLACE_DECIMALS param,
    passed to each Place it builds), the Nominatim geocoding proxy, and the
    ``at()`` factory for Place objects.

    The Nominatim cache, throttle clock and lock are per-instance state, so
    tests can build an isolated ``Places`` instead of sharing the singleton.
    """

    NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
    # Nominatim usage policy: at most 1 request/second — throttle upstream
    # calls and cache repeated lookups. Only 200 responses are cached;
    # upstream errors surface as 502 (never leaking Nominatim's status/body).
    NOMINATIM_MIN_INTERVAL = 1.0
    NOMINATIM_CACHE_TTL = 300.0

    def __init__(self, decimals: int, base_url: str = "") -> None:
        if not 1 <= decimals <= Place.MAX_DECIMALS:
            raise ValueError(
                f"decimals must be 1..{Place.MAX_DECIMALS} (got {decimals!r})"
            )
        self.decimals = decimals
        self._headers = {
            "User-Agent": f"Pheme/0.1 ({base_url})",
            "Accept-Language": "en",
        }
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        # Indirection so tests can patch the wait without touching the loop.
        self._sleep = asyncio.sleep

    # ── Place factory ───────────────────────────────────────────────────

    async def at(self, lat: float, lng: float) -> Place:
        """The Place object for a coordinate pair (e.g. a clicked spot on the
        map), loaded with its reviews from the DB. The manager passes its
        configured bucket precision straight into the Place."""
        p = Place(self.decimals, lat, lng)
        p.reviews = await p.reviews_at()
        return p

    # ── geocoding (Nominatim proxy) ─────────────────────────────────────

    async def nominatim_get(self, path: str, params: dict[str, Any]) -> JSONResponse:
        """GET a Nominatim endpoint, cached and throttled to 1 req/s."""
        key = (path, tuple(sorted(params.items())))
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < self.NOMINATIM_CACHE_TTL:
            return JSONResponse(cached[1])

        async with self._lock:
            wait = self.NOMINATIM_MIN_INTERVAL - (time.monotonic() - self._last_request)
            if wait > 0:
                await self._sleep(wait)
            self._last_request = time.monotonic()
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.get(
                        f"{self.NOMINATIM_BASE}{path}",
                        params=params,
                        headers=self._headers,
                    )
                except httpx.RequestError as exc:
                    logger.warning("Nominatim %s failed: %s", path, exc)
                    raise HTTPException(502, "Geocoding service unavailable") from exc

        if resp.status_code != 200:
            logger.warning("Nominatim %s returned %d", path, resp.status_code)
            raise HTTPException(502, "Geocoding service unavailable")

        data = resp.json()
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[key] = (time.monotonic(), data)
        return JSONResponse(data)


#: The server's Places instance — bucket precision from config (PLACE_DECIMALS).
places = Places(decimals=config.place_decimals, base_url=config.base_url)
