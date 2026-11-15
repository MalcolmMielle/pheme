"""Places — the place manager for this server.

Owns the server-wide place configuration (the runtime ``PLACE_DECIMALS``
bucket precision), the geocoding proxies (Nominatim search/reverse plus an
OSM-API nearest-POI lookup that gives commerces/hospitals priority over a
bare street address on reverse geocode), and the factory for
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
import re
import time
import xml.etree.ElementTree as ET
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.config import config
from app.places.place import Place

logger = logging.getLogger("pheme")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two coordinates (haversine)."""
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = p2 - p1
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _humanize_label(value: str) -> str:
    """'motorcycle_parking' → 'Motorcycle parking' — a display label for an
    unnamed place's OSM tag value. ``saddle`` → 'Pass' (a mountain pass)."""
    if value == "saddle":
        return "Pass"
    return value.replace("_", " ").strip().capitalize()


class Places:
    """Place manager: the bucket precision (runtime PLACE_DECIMALS param,
    passed to each Place it builds), the geocoding proxies (Nominatim +
    the OSM API), and the ``at()`` factory for Place objects.

    The Nominatim/OSM caches, throttle clocks and lock are per-instance
    state, so tests can build an isolated ``Places`` instead of sharing the
    singleton.
    """

    NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
    # Nominatim usage policy: at most 1 request/second — throttle upstream
    # calls and cache repeated lookups. Only 200 responses are cached;
    # upstream errors surface as 502 (never leaking Nominatim's status/body).
    NOMINATIM_MIN_INTERVAL = 1.0
    NOMINATIM_CACHE_TTL = 300.0

    #: OSM API map call — the POI source for the nearest-POI lookup that
    #: gives named POIs (commerces, hospitals, …) priority over a bare
    #: street address when reverse geocoding a clicked point. Same
    #: infrastructure as Nominatim (api.openstreetmap.org), so it is
    #: reachable wherever Nominatim is — no separate Overpass dependency.
    #: Throttled/cached like Nominatim, but failures return None and just
    #: fall back to the plain Nominatim result — never a 502.
    OSM_MAP_URL = "https://api.openstreetmap.org/api/0.6/map"
    OSM_MIN_INTERVAL = 1.0
    #: Which OSM places can be reviewed — the candidate filter. Comma-
    #: separated specs, each ``key`` or ``key=value`` (prefix ``!`` to
    #: exclude, e.g. ``!amenity=toilets``). The default covers POIs, roads,
    #: localities and peaks/passes (``natural=peak``/``natural=saddle``).
    #: Configurable via the REVIEWABLE_TAGS env var → config.reviewable_tags
    #: → the ``reviewable_tags`` constructor arg (this constant is the
    #: default). Keep in sync with the default in app/config.py.
    DEFAULT_REVIEWABLE_TAGS = (
        "shop,office,tourism,leisure,healthcare,emergency,craft,historic,"
        "man_made,amenity,place,highway,natural=peak,natural=saddle,"
        "!amenity=toilets,!amenity=bench,!amenity=waste_basket,"
        "!amenity=drinking_water,!amenity=sanitary_dump_station,"
        "!amenity=recycling,!amenity=charging_station,!amenity=vending_machine,"
        "!amenity=water_point,!amenity=compressed_air"
    )
    #: Search radius (meters) for places around a click — wide enough that a
    #: station forecourt or a nearby summit/pass (a peak icon's label can sit
    #: ~100 m from the node) yields candidates for the picker.
    POI_RADIUS_M = 150.0
    #: ``highway``/``railway``/``public_transport`` values that mark a transit
    #: stop (a place you wait at), not a road. Such candidates get a
    #: kind-qualified label ("Bus stop · …") so a stop named after a hamlet
    #: (e.g. "Pelleautier - Le Lozeron") is still recognizable as a stop.
    TRANSIT_STOP_VALUES = frozenset(
        {
            "bus_stop",
            "platform",
            "station",
            "stop",
            "terminal",
            "stop_position",
            "tram_stop",
            "halt",
        }
    )

    def __init__(
        self, decimals: int, base_url: str = "", reviewable_tags: str | None = None
    ) -> None:
        if not 1 <= decimals <= Place.MAX_DECIMALS:
            raise ValueError(
                f"decimals must be 1..{Place.MAX_DECIMALS} (got {decimals!r})"
            )
        self.decimals = decimals
        self._reviewable_specs = self._parse_reviewable_tags(
            reviewable_tags or self.DEFAULT_REVIEWABLE_TAGS
        )
        self._headers = {
            "User-Agent": f"Pheme/0.1 ({base_url})",
            "Accept-Language": "en",
        }
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._last_request = 0.0
        self._osm_last_request = 0.0
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
        return JSONResponse(await self._nominatim_data(path, params))

    async def _nominatim_data(self, path: str, params: dict[str, Any]) -> Any:
        """GET a Nominatim endpoint and return the parsed body — cached and
        throttled to 1 req/s. Upstream errors surface as 502 (never leaking
        Nominatim's status/body); only 200 responses are cached."""
        key = (path, tuple(sorted(params.items())))
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < self.NOMINATIM_CACHE_TTL:
            return cached[1]

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
        return data

    # ── nearest reviewable place (OSM API) + reverse geocode ────────────

    @staticmethod
    def _parse_reviewable_tags(spec: str) -> list[tuple[bool, str, str | None]]:
        """Parse a REVIEWABLE_TAGS value into (negated, key, value) specs."""
        out = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            negated = part.startswith("!")
            if negated:
                part = part[1:]
            key, _, value = part.partition("=")
            out.append((negated, key.strip(), value.strip() or None))
        return out

    def _reviewable_match(self, tags: dict[str, Any]) -> str | None:
        """The tag key by which this element passes the reviewable-places
        filter, or None when it doesn't. ``!``-negated specs exclude; the
        filter is fully controlled by REVIEWABLE_TAGS."""
        matched = None
        for negated, key, value in self._reviewable_specs:
            if key not in tags:
                continue
            v = str(tags[key])
            if value is not None and v != value:
                continue
            if negated:
                return None
            matched = matched or key
        return matched

    def _transit_kind(self, tags: dict[str, Any]) -> str | None:
        """The humanized transit-stop kind of an element ("Bus stop",
        "Platform", "Tram stop", …), or None when it isn't a transit stop."""
        for k in ("highway", "railway", "public_transport"):
            v = str(tags.get(k, ""))
            if v in self.TRANSIT_STOP_VALUES:
                return _humanize_label(v)
        return None

    async def pois_near(
        self, lat: float, lon: float, radius: float | None = None, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Reviewable places around a point, via the OSM API map bbox —
        nodes, ways and relations whose tags pass the REVIEWABLE_TAGS filter.
        Unnamed matches qualify too (except unnamed roads and other unnamed
        roadside features) — they get a synthesized label from the matched
        tag's value ("Playground", "Library", "Motorcycle parking", …),
        since map renderers show icons for them regardless of name; what is
        excluded is entirely up to the filter (the default keeps utilities
        like toilets out). Transit stops (``highway=bus_stop``, …) get a
        kind-qualified name ("Bus stop · Pelleautier - Le Lozeron") so a stop
        named after a hamlet is still recognizable as a stop. Roads
        (``highway`` ways) appear with their centroid as position, so
        selecting a road snaps to one canonical point.
        Returns up to ``limit`` entries as ``{"name", "type", "lat", "lon",
        "distance_m"}`` sorted by distance only, keeping only elements within
        ~1.5× the radius (the square bbox's corners reach √2·r; beyond that
        only far-away relation members appear in the map response). For
        ways/relations the position is the centroid (the snap point) but the
        distance is to the nearest member node."""
        r = self.POI_RADIUS_M if radius is None else radius
        elements = await self._osm_map_elements(lat, lon, r) or []
        pois = []
        for el in elements:
            tags = el.get("tags") or {}
            mtype = self._reviewable_match(tags)
            if mtype is None:
                continue
            raw_name = tags.get("name")
            kind = self._transit_kind(tags)
            if not raw_name:
                # Map renderers show icons for many places even when unnamed
                # (library, playground, parking, bus stop, …) — synthesize a
                # label from the matched tag's value ("Playground", …).
                # Unnamed roads/roadside features stay out (a road needs a
                # name to be a place).
                if mtype == "highway" and kind is None:
                    continue
                name = kind or _humanize_label(str(tags.get(mtype, "")))
            else:
                name = raw_name
            plat = el.get("lat")
            plon = el.get("lon")
            if plat is None or plon is None:
                continue
            d = el.get("min_dist_m")
            if d is None:
                d = _haversine_m(lat, lon, plat, plon)
            # The bbox is a square whose corners reach ~1.41·r; beyond
            # 1.5·r only far-away relation members (e.g. stops along a bus
            # route) sneak into the map response — drop them.
            if d > r * 1.5:
                continue
            pois.append(
                {
                    "name": name,
                    "type": mtype,
                    "lat": plat,
                    "lon": plon,
                    "distance_m": round(d, 1),
                    "_raw_name": raw_name,
                    "_kind": kind,
                }
            )
        pois.sort(key=lambda p: p["distance_m"])
        # One entry per road (or per same-named stop): a road split into
        # several way segments within the bbox is still one place — keep the
        # nearest segment's centroid as the canonical position so reviews of
        # the road share one bucket. Dedup on the raw name so a bus stop's
        # node and its platform (same name) collapse into one entry.
        seen_highways: set[str] = set()
        deduped = []
        for p in pois:
            if p["type"] == "highway":
                key = p["_raw_name"] or p["name"]
                if key in seen_highways:
                    continue
                seen_highways.add(key)
            kind = p.pop("_kind")
            raw = p.pop("_raw_name")
            if kind:
                # "Bus stop · Pelleautier - Le Lozeron" (or just "Bus stop"
                # when the stop is unnamed).
                p["name"] = f"{kind} · {raw}" if raw else kind
            deduped.append(p)
        return deduped[:limit]

    async def _osm_map_elements(
        self, lat: float, lon: float, radius: float
    ) -> list[dict[str, Any]] | None:
        """OSM elements carrying one of the REVIEWABLE_TAGS keys, in a bbox
        around a point, via the OSM API ``map`` call — the candidate source
        for reverse geocoding. Returns
        ``[{"tags", "lat", "lon"}]`` (ways/relations get the centroid of
        their member nodes present in the response), cached and throttled
        to ~1 req/s; None on any upstream problem."""
        m_per_deg = 111320.0
        dlat = radius / m_per_deg
        dlon = radius / (m_per_deg * cos(radians(lat)))
        bbox = f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}"
        key = ("osm-map", bbox)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < self.NOMINATIM_CACHE_TTL:
            return cached[1]

        async with self._lock:
            elapsed = time.monotonic() - self._osm_last_request
            wait = self.OSM_MIN_INTERVAL - elapsed
            if wait > 0:
                await self._sleep(wait)
            self._osm_last_request = time.monotonic()
            async with httpx.AsyncClient(timeout=8.0) as client:
                try:
                    resp = await client.get(
                        self.OSM_MAP_URL, params={"bbox": bbox}, headers=self._headers
                    )
                except httpx.RequestError as exc:
                    logger.warning("OSM map %s failed: %s", bbox, exc)
                    return None

        if resp.status_code != 200:
            logger.warning("OSM map %s returned %d", bbox, resp.status_code)
            return None
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            logger.warning("OSM map %s: bad XML: %s", bbox, exc)
            return None

        node_ll = {
            n.get("id"): (float(n.get("lat")), float(n.get("lon")))
            for n in root.findall("node")
        }
        scan_keys = sorted({k for _, k, _ in self._reviewable_specs})
        keys_re = re.compile(f"^({'|'.join(scan_keys)})$")
        out = []
        for el in root:
            if el.tag not in ("node", "way", "relation"):
                continue
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if not any(keys_re.match(k) for k in tags):
                continue
            if el.tag == "node":
                ll = node_ll.get(el.get("id"))
                min_d = _haversine_m(lat, lon, ll[0], ll[1]) if ll is not None else None
            else:
                # Way/relation: position = centroid of the member nodes we
                # have; distance = nearest member node.
                if el.tag == "way":
                    refs = [n.get("ref") for n in el.findall("nd")]
                else:
                    refs = [
                        m.get("ref")
                        for m in el.findall("member")
                        if m.get("type") == "node"
                    ]
                lls = [node_ll[r] for r in refs if r in node_ll]
                ll = (
                    (
                        sum(a for a, _ in lls) / len(lls),
                        sum(b for _, b in lls) / len(lls),
                    )
                    if lls
                    else None
                )
                min_d = (
                    min(_haversine_m(lat, lon, a, b) for a, b in lls) if lls else None
                )
            if ll is None or min_d is None:
                continue
            out.append({"tags": tags, "lat": ll[0], "lon": ll[1], "min_dist_m": min_d})
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[key] = (time.monotonic(), out)
        return out

    async def nearest_poi(
        self, lat: float, lon: float, radius: float | None = None
    ) -> dict[str, Any] | None:
        """The single best POI around a point — the first of ``pois_near``
        (closest first), or None when nothing is within ``radius`` (default
        ``POI_RADIUS_M``)."""
        pois = await self.pois_near(lat, lon, radius=radius, limit=1)
        return pois[0] if pois else None

    async def reverse_geocode(self, lat: float, lon: float) -> JSONResponse:
        """Reverse geocode a clicked point with POI priority. Nominatim alone
        returns the closest object, which is often the street/building under
        the click rather than the commerce on it. So:

        - the closest reviewable place (OSM API bbox, small radius — entries
          passing the REVIEWABLE_TAGS filter), is prepended to the display
          name:
          "McDonald's, Place de la Gare, …" instead of "Toilets, …" or
          "Place de la Gare, 2, …"; transit stops get their kind prepended
          ("Bus stop, Pelleautier - Le Lozeron, Route du Lozeron, …");
        - if Nominatim's closest object is itself an unnamed place of a
          reviewable kind (e.g. a parking, which often has no name in OSM)
          and the POI lookup finds nothing, its OSM type becomes the label:
          "Motorcycle parking, A1, Morges, …" — but objects excluded by the
          REVIEWABLE_TAGS filter (utilities like toilets, benches, … by
          default) get no label and never mask a nearby commerce;
        - if Nominatim itself fails (502), the POIs alone still answer;
          only when both fail does the request 502.

        The response always carries ``candidates`` — the distance-sorted list
        of reviewable places around the point — so the UI can offer the user
        a choice when
        several places share the clicked spot, plus ``address`` (the
        Nominatim display name without the prepended POI label).
        OSM API failures otherwise just fall back to the plain Nominatim
        result."""
        try:
            data = await self._nominatim_data(
                "/reverse", {"lat": lat, "lon": lon, "format": "json"}
            )
        except HTTPException:
            candidates = await self.pois_near(lat, lon)
            if candidates:
                top = candidates[0]
                return JSONResponse(
                    {
                        "display_name": top["name"],
                        "name": top["name"],
                        "address": top["name"],
                        "poi": top,
                        "candidates": candidates,
                        "lat": lat,
                        "lon": lon,
                    }
                )
            raise

        base_display = str(data.get("display_name") or "")
        candidates = await self.pois_near(lat, lon)
        tags = {str(data.get("class") or ""): str(data.get("type") or "")}
        label = candidates[0]["name"] if candidates else None
        if label and " · " in label:
            # Kind-qualified candidate ("Bus stop · X"): when the raw name is
            # already in the Nominatim display, prepend only the kind so the
            # name isn't repeated — "Bus stop, X, Route du Lozeron, …".
            kind, _, raw = label.partition(" · ")
            if raw.lower() in base_display.lower():
                label = kind
        reviewable_at_point = self._reviewable_match(tags) is not None
        if label is None and reviewable_at_point and data.get("type"):
            # Unnamed reviewable place exactly at the point (e.g. a parking) —
            # label it from its OSM type instead of the street name. Places
            # outside the REVIEWABLE_TAGS filter (toilets, …) get no label.
            label = _humanize_label(str(data["type"]))
        if label and label.lower() not in base_display.lower():
            data = {
                **data,
                "name": label,
                **({"poi": candidates[0]} if candidates else {}),
                "display_name": f"{label}, {base_display}" if base_display else label,
            }
        data["address"] = base_display or str(data.get("display_name") or "")
        data["candidates"] = candidates
        return JSONResponse(data)


#: The server's Places instance — bucket precision and reviewable-place
#: filter from config (PLACE_DECIMALS / REVIEWABLE_TAGS).
places = Places(
    decimals=config.place_decimals,
    base_url=config.base_url,
    reviewable_tags=config.reviewable_tags,
)
