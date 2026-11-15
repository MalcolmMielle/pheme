"""Tests for app.places — Places (the manager: runtime PLACE_DECIMALS
bucketing, Nominatim proxy, Place factory) and Place (a single place loaded
from the DB, with add/update/review_by on it)."""

import json
import os
import time
import unittest
from typing import Any
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.config import Config, config
from app.db import create_actor
from app.reviews import reviews
from app.places import AlreadyReviewed, Place, Places, places
from tests.base import AsyncTestCase


class TestPlaceDecimalsConfig(unittest.TestCase):
    """PLACE_DECIMALS is a runtime parameter of the app (env var → config)."""

    def test_default_is_4(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLACE_DECIMALS", None)
            assert Config().place_decimals == 4

    def test_env_override(self):
        with patch.dict(os.environ, {"PLACE_DECIMALS": "6"}):
            assert Config().place_decimals == 6

    def test_invalid_values_rejected(self):
        for bad in ("0", "9", "-1"):
            with patch.dict(os.environ, {"PLACE_DECIMALS": bad}):
                with self.assertRaises(ValueError):
                    Config()

    def test_singleton_uses_config(self):
        assert places.decimals == config.place_decimals


class TestReviewableTagsConfig(unittest.TestCase):
    """REVIEWABLE_TAGS is a runtime parameter (env var → config → Places):
    the filter of which OSM places can be reviewed."""

    def test_default_is_the_full_place_key_list(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REVIEWABLE_TAGS", None)
            assert Config().reviewable_tags == Places.DEFAULT_REVIEWABLE_TAGS
            assert "shop" in Config().reviewable_tags
            assert "highway" in Config().reviewable_tags
            # The default excludes utility amenities via !-specs.
            assert "!amenity=toilets" in Config().reviewable_tags
            assert "!amenity=bench" in Config().reviewable_tags
            # …and includes peaks and passes.
            assert "natural=peak" in Config().reviewable_tags
            assert "natural=saddle" in Config().reviewable_tags

    def test_env_override(self):
        with patch.dict(os.environ, {"REVIEWABLE_TAGS": "shop,amenity=restaurant"}):
            assert Config().reviewable_tags == "shop,amenity=restaurant"

    def test_singleton_uses_config(self):
        assert places._reviewable_specs == Places._parse_reviewable_tags(
            config.reviewable_tags
        )

    def test_spec_parsing(self):
        specs = Places._parse_reviewable_tags("shop, amenity=restaurant, !highway")
        assert specs == [
            (False, "shop", None),
            (False, "amenity", "restaurant"),
            (True, "highway", None),
        ]

    def test_filter_controls_candidates(self):
        """With REVIEWABLE_TAGS=shop only shops pass; amenity nodes don't."""
        p = Places(decimals=4, reviewable_tags="shop")
        assert p._reviewable_match({"shop": "supermarket"}) == "shop"
        assert p._reviewable_match({"amenity": "restaurant"}) is None
        assert p._reviewable_match({"amenity": "toilets"}) is None
        # Negation excludes even when another spec matches.
        p2 = Places(decimals=4, reviewable_tags="amenity,!amenity=toilets")
        assert p2._reviewable_match({"amenity": "cafe"}) == "amenity"
        assert p2._reviewable_match({"amenity": "toilets"}) is None
        # No hardcoded exclusion: an explicitly listed spec matches, even a
        # utility one — opting back in is purely the env var's business.
        p3 = Places(decimals=4, reviewable_tags="amenity=toilets")
        assert p3._reviewable_match({"amenity": "toilets"}) == "amenity"
        # …while the default filter keeps utilities out.
        default = Places(decimals=4)
        assert default._reviewable_match({"amenity": "toilets"}) is None
        assert default._reviewable_match({"amenity": "bench"}) is None
        assert default._reviewable_match({"amenity": "townhall"}) == "amenity"
        assert default._reviewable_match({"leisure": "park"}) == "leisure"
        # Peaks and passes are reviewable by default; other natural features
        # (trees, woods, …) are not.
        assert default._reviewable_match({"natural": "peak"}) == "natural"
        assert default._reviewable_match({"natural": "saddle"}) == "natural"
        assert default._reviewable_match({"natural": "tree"}) is None


class TestPlaceIdentity(unittest.TestCase):
    """Place.place_key / same_place_sql / __eq__ — bucket identity lives on
    Place (the manager only carries the precision config)."""

    def setUp(self):
        self.p = Places(decimals=4, base_url="http://testserver")

    def test_rejects_out_of_range_decimals(self):
        for bad in (0, 9, -1):
            with self.assertRaises(ValueError):
                Places(decimals=bad)
            with self.assertRaises(ValueError):
                Place(bad, 37.0, -122.0)

    def test_key_format_matches_map_ui(self):
        # Same "lat,lng" decimal format as react-app/src/places.ts placeKey.
        assert Place(4, 37.7749, -122.4194).place_key() == "37.7749,-122.4194"
        assert Place(4, 37.0, -122.0).key == "37.0000,-122.0000"

    def test_bucketing_rounds_to_decimals(self):
        # 37.00001 falls in the same ~11 m bucket as 37.0
        assert Place(4, 37.00001, -122.0).key == Place(4, 37.0, -122.0).key
        # ...but 37.001 is a different bucket
        assert Place(4, 37.001, -122.0).key != Place(4, 37.0, -122.0).key

    def test_rounding_half_away_from_zero_like_sqlite(self):
        # Ties round away from zero, matching SQLite ROUND() used in queries.
        assert Place(4, 37.00005, 0.0).key.startswith("37.0001")
        assert Place(4, -122.00005, 0.0).key.startswith("-122.0001")

    def test_place_equality_is_bucket_equality(self):
        # Place.__eq__: same bucket → equal, even with different raw coords.
        assert Place(4, 37.0, -122.0) == Place(4, 37.00004, -122.00004)
        assert Place(4, 37.0, -122.0) != Place(4, 37.001, -122.0)
        assert Place(4, 37.0, -122.0) != Place(4, 37.0, -122.001)
        # Comparing against a non-Place is False, not an error.
        assert (Place(4, 37.0, -122.0) == 42) is False
        assert Place(4, 37.0, -122.0) != "37.0000,-122.0000"

    def test_place_hash_matches_bucket(self):
        a = Place(4, 37.0, -122.0)
        b = Place(4, 37.00004, -122.00004)
        c = Place(4, 37.001, -122.0)
        assert hash(a) == hash(b)
        assert len({a, b, c}) == 2  # a and b collapse, c is distinct

    def test_same_place_sql_fragment(self):
        frag = Place(4, 0.0, 0.0).same_place_sql("r.latitude", "r.longitude")
        assert frag == (
            "ROUND(r.latitude, 4) = ROUND(?, 4) AND ROUND(r.longitude, 4) = ROUND(?, 4)"
        )

    def test_custom_decimals_change_bucketing(self):
        """The runtime parameter actually drives the bucket precision —
        a Places manager configured with 3 passes that into its Places."""
        coarse = Places(decimals=3, base_url="http://testserver")
        assert Place(coarse.decimals, 37.0, -122.0).key == "37.000,-122.000"
        # At 3 decimals, 37.0004 and 37.00049 are the same place...
        assert Place(3, 37.0004, -122.0) == Place(3, 37.00049, -122.0)
        # ...while at 4 decimals they are not.
        assert Place(4, 37.0004, -122.0) != Place(4, 37.00049, -122.0)
        # Different precisions never compare equal (keys carry the format).
        assert Place(3, 37.0, -122.0) != Place(4, 37.0, -122.0)
        assert "ROUND(r.latitude, 3)" in Place(3, 0.0, 0.0).same_place_sql(
            "r.latitude", "r.longitude"
        )


class _FakeResp:
    def __init__(self, status_code: int, data=None, text: str | None = None):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = text if text is not None else json.dumps(self._data)

    def json(self):
        return self._data


def _fake_client(get_impl):
    """Build a fake httpx.AsyncClient whose get() delegates to get_impl."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            return await get_impl(url, params)

    return FakeClient


def _fake_client_get(get_impl):
    """Fake httpx.AsyncClient: get() delegates to get_impl; post() fails the
    test — the OSM API is the only POI source now (no Overpass)."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            return await get_impl(url, params)

        async def post(self, *args, **kwargs):
            raise AssertionError("POST must not be used — no Overpass anymore")

    return FakeClient


def _elements_xml(elements):
    """Serialize overpass-style element dicts as an OSM XML map document
    (each element becomes a node at its lat/lon, or its center)."""
    parts = ["<osm>"]
    for i, el in enumerate(elements):
        center = el.get("center") or {}
        lat = el.get("lat", center.get("lat", 0.0))
        lon = el.get("lon", center.get("lon", 0.0))
        tags = "".join(
            f'<tag k="{k}" v="{v}"/>' for k, v in (el.get("tags") or {}).items()
        )
        parts.append(f'<node id="{i}" lat="{lat}" lon="{lon}">{tags}</node>')
    parts.append("</osm>")
    return "".join(parts)


class TestNominatimProxy(AsyncTestCase):
    """Places.nominatim_get — cache, throttle and error mapping, on a fresh
    per-test Places instance (no shared singleton state)."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.places = Places(decimals=4, base_url="http://testserver")

    async def _get(self, path, params, get_impl):
        with patch("app.places.places.httpx.AsyncClient", _fake_client(get_impl)):
            return await self.places.nominatim_get(path, params)

    async def test_caches_successful_responses(self):
        calls: list[str] = []

        async def get_impl(url, params):
            calls.append(url)
            return _FakeResp(200, [{"display_name": "Cafe"}])

        params = {"q": "cafe", "format": "json"}
        r1 = await self._get("/search", params, get_impl)
        r2 = await self._get("/search", params, get_impl)

        assert len(calls) == 1  # second call served from the cache
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.body == r2.body
        assert json.loads(bytes(r1.body)) == [{"display_name": "Cafe"}]

    async def test_cache_key_includes_params(self):
        calls: list[dict[str, Any]] = []

        async def get_impl(url, params):
            calls.append(params)
            return _FakeResp(200, [])

        await self._get("/search", {"q": "a"}, get_impl)
        await self._get("/search", {"q": "b"}, get_impl)
        assert len(calls) == 2

    async def test_cache_expires_after_ttl(self):
        calls: list[str] = []

        async def get_impl(url, params):
            calls.append(url)
            return _FakeResp(200, [])

        params = {"q": "cafe"}
        await self._get("/search", params, get_impl)
        assert len(calls) == 1
        # Backdate the cache entry beyond the TTL — next call hits upstream.
        key = ("/search", tuple(sorted(params.items())))
        ts, data = self.places._cache[key]
        self.places._cache[key] = (ts - Places.NOMINATIM_CACHE_TTL - 1, data)
        await self._get("/search", params, get_impl)
        assert len(calls) == 2

    async def test_throttles_to_one_request_per_second(self):
        sleeps: list[float] = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        async def get_impl(url, params):
            return _FakeResp(200, [])

        # Pretend a request just went out — the next one must wait ~1 s.
        self.places._last_request = time.monotonic()
        with patch.object(self.places, "_sleep", fake_sleep):
            await self._get("/search", {"q": "x"}, get_impl)
        assert len(sleeps) == 1
        assert 0.9 <= sleeps[0] <= Places.NOMINATIM_MIN_INTERVAL

    async def test_no_wait_when_interval_elapsed(self):
        sleeps: list[float] = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        async def get_impl(url, params):
            return _FakeResp(200, [])

        self.places._last_request = time.monotonic() - 10.0
        with patch.object(self.places, "_sleep", fake_sleep):
            await self._get("/search", {"q": "x"}, get_impl)
        assert sleeps == []

    async def test_upstream_request_error_maps_to_502(self):
        async def get_impl(url, params):
            raise httpx.RequestError("connection refused")

        with self.assertRaises(HTTPException) as cm:
            await self._get("/search", {"q": "x"}, get_impl)
        assert cm.exception.status_code == 502

    async def test_upstream_non_200_maps_to_502_and_is_not_cached(self):
        calls: list[str] = []

        async def get_impl(url, params):
            calls.append(url)
            return _FakeResp(503)

        for _ in range(2):
            with self.assertRaises(HTTPException) as cm:
                await self._get("/search", {"q": "x"}, get_impl)
            assert cm.exception.status_code == 502
        assert len(calls) == 2  # errors are never cached

    async def test_fresh_instance_has_clean_state(self):
        """Each Places instance starts with an empty cache and throttle clock
        (tests build their own instance per test — no shared reset needed)."""
        assert self.places._cache == {}
        assert self.places._last_request == 0.0


class TestReverseGeocodePoiPriority(AsyncTestCase):
    """Places.reverse_geocode — Nominatim reverse + OSM-API POIs: a named
    commerce/hospital wins over the bare street address under the click,
    and the response carries the distance-sorted candidate list for the picker."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.places = Places(decimals=4, base_url="http://testserver")

    async def _reverse(
        self, nominatim_data, osm_elements=None, osm_status=200, osm_error=False
    ):
        gets: list[str] = []

        async def get_impl(url, params):
            gets.append(url)
            if "nominatim" in url:
                return _FakeResp(200, nominatim_data)
            if osm_error:
                raise httpx.RequestError("boom")
            if osm_status != 200:
                return _FakeResp(osm_status)
            return _FakeResp(200, text=_elements_xml(osm_elements or []))

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            resp = await self.places.reverse_geocode(37.0, -122.0)
        return resp, gets

    @staticmethod
    def _osm_gets(gets):
        return [u for u in gets if "api.openstreetmap.org" in u]

    async def test_poi_name_prepended_over_street(self):
        nom = {
            "display_name": "Main Street, 12, Springfield",
            "class": "highway",
            "type": "residential",
        }
        osm = [
            {
                "type": "node",
                "lat": 37.00001,
                "lon": -122.0,
                "tags": {"name": "Cafe Foo", "amenity": "cafe"},
            }
        ]
        resp, gets = await self._reverse(nom, osm)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == "Cafe Foo, Main Street, 12, Springfield"
        assert body["name"] == "Cafe Foo"
        assert body["poi"]["type"] == "amenity"
        assert len(self._osm_gets(gets)) == 1  # one OSM bbox call

    async def test_named_poi_result_not_duplicated(self):
        """Clicking exactly on a named POI: its name is not prepended again,
        and the response still carries the candidates list for the UI."""
        nom = {
            "display_name": "Cafe Foo, Main Street, Springfield",
            "name": "Cafe Foo",
            "class": "amenity",
            "type": "cafe",
        }
        resp, gets = await self._reverse(nom, [])
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == "Cafe Foo, Main Street, Springfield"
        assert body["address"] == "Cafe Foo, Main Street, Springfield"
        assert body["candidates"] == []
        assert len(self._osm_gets(gets)) == 1  # candidates always fetched

    async def test_candidates_list_sorted_by_distance_for_the_picker(self):
        """Several places around one click (e.g. a station forecourt): the
        response carries all that pass the filter, sorted by distance only,
        and the closest one becomes the display name."""
        nom = {
            "display_name": "Place de la Gare, Morges",
            "class": "highway",
            "type": "pedestrian",
        }
        osm = [
            {
                "type": "node",
                "lat": 37.00002,
                "lon": -122.0,
                "tags": {"amenity": "parking"},
            },
            {
                "type": "node",
                "lat": 37.00004,
                "lon": -122.0,
                "tags": {"name": "McDonald's", "amenity": "fast_food"},
            },
            {
                "type": "node",
                "lat": 37.0001,
                "lon": -122.0,
                "tags": {"name": "Coop", "shop": "supermarket"},
            },
        ]
        resp, _ = await self._reverse(nom, osm)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == "Parking, Place de la Gare, Morges"
        assert body["address"] == "Place de la Gare, Morges"
        names = [c["name"] for c in body["candidates"]]
        # Pure distance sort: parking 2 m, McDonald's 4 m, Coop 11 m.
        assert names == ["Parking", "McDonald's", "Coop"]
        assert body["candidates"][0]["type"] == "amenity"
        assert body["candidates"][2]["type"] == "shop"
        assert "rank" not in body["candidates"][0]

    async def test_no_duplicate_when_display_already_contains_poi_name(self):
        nom = {
            "display_name": "Cafe Foo, 1 Main Street, Springfield",
            "class": "building",
            "type": "yes",
        }
        osm = [
            {
                "type": "node",
                "lat": 37.0,
                "lon": -122.0,
                "tags": {"name": "Cafe Foo", "shop": "coffee"},
            }
        ]
        resp, _ = await self._reverse(nom, osm)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == "Cafe Foo, 1 Main Street, Springfield"

    async def test_osm_failure_falls_back_to_plain_nominatim(self):
        nom = {"display_name": "Main Street, 12, Springfield", "class": "highway"}
        resp, _ = await self._reverse(nom, osm_error=True)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == "Main Street, 12, Springfield"
        assert "poi" not in body
        # A non-200 from the OSM API falls back the same way (not cached).
        resp2, gets2 = await self._reverse(nom, osm_status=500)
        assert "poi" not in json.loads(bytes(resp2.body))
        assert len(self._osm_gets(gets2)) == 1

    async def test_nominatim_error_still_502(self):
        async def get_impl(url, params):
            if "nominatim" in url:
                raise httpx.RequestError("down")
            return _FakeResp(200, text=_elements_xml([]))

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            with self.assertRaises(HTTPException) as cm:
                await self.places.reverse_geocode(37.0, -122.0)
        assert cm.exception.status_code == 502

    async def test_unnamed_poi_at_point_gets_type_label(self):
        """Nominatim's closest object is an unnamed POI (e.g. a parking with
        no name in OSM) and the POI lookup finds nothing — label it from its
        OSM type instead of showing the bare street/motorway."""
        nom = {
            "display_name": "A1, Morges, District de Morges, Vaud, Switzerland",
            "class": "amenity",
            "type": "motorcycle_parking",
            "name": "",
        }
        resp, _ = await self._reverse(nom, [])
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == (
            "Motorcycle parking, A1, Morges, District de Morges, Vaud, Switzerland"
        )
        assert body["name"] == "Motorcycle parking"
        # Label came from Nominatim's type, not the POI list.
        assert "poi" not in body

    async def test_unnamed_parking_from_osm(self):
        """Parkings without a name still qualify — label synthesized from the
        amenity (most parkings in OSM have no name)."""
        nom = {
            "display_name": "Sentier de Saint-Roch, Morges",
            "class": "highway",
            "type": "path",
        }
        osm = [
            {
                "type": "node",
                "lat": 37.00001,
                "lon": -122.0,
                "tags": {"amenity": "parking"},
            }
        ]
        resp, _ = await self._reverse(nom, osm)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == "Parking, Sentier de Saint-Roch, Morges"
        assert body["poi"]["name"] == "Parking"

    async def test_commerce_in_list_when_toilets_at_the_point(self):
        """The click lands on/near toilets: toilets are not reviewable, so the
        McDonald's node a few meters away is the label."""
        nom = {
            "display_name": "Place de la Gare, Morges",
            "class": "amenity",
            "type": "toilets",
            "name": "",
        }
        osm = [
            {
                "type": "node",
                "lat": 37.00004,
                "lon": -122.0,
                "tags": {"name": "McDonald's", "amenity": "fast_food"},
            }
        ]
        resp, _ = await self._reverse(nom, osm)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == "McDonald's, Place de la Gare, Morges"
        assert body["name"] == "McDonald's"

    async def test_toilets_never_labelled_when_osm_down(self):
        """Utility POIs (toilets, benches, …) get no synthesized label — with
        the OSM API down the plain street name shows, not 'Toilets'."""
        nom = {
            "display_name": "Place de la Gare, Morges",
            "class": "amenity",
            "type": "toilets",
            "name": "",
        }
        resp, _ = await self._reverse(nom, osm_error=True)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == "Place de la Gare, Morges"
        assert not body.get("name")

    async def test_bus_stop_click_is_marked_as_a_bus_stop(self):
        """Clicking a bus stop named after a hamlet: the display name gets
        the kind prepended — "Bus stop, Pelleautier - Le Lozeron, …" (the
        raw name is already in the Nominatim display, so it is not
        repeated) — and the candidate list carries the qualified name."""
        nom = {
            "display_name": (
                "Pelleautier - Le Lozeron, Route du Lozeron, Pelleautier, Gap"
            ),
            "class": "highway",
            "type": "tertiary",
        }
        osm = [
            {
                "type": "node",
                "lat": 37.00001,
                "lon": -122.0,
                "tags": {
                    "highway": "bus_stop",
                    "name": "Pelleautier - Le Lozeron",
                    "public_transport": "stop_position",
                },
            }
        ]
        resp, _ = await self._reverse(nom, osm)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == (
            "Bus stop, Pelleautier - Le Lozeron, Route du Lozeron, Pelleautier, Gap"
        )
        assert body["name"] == "Bus stop"
        assert body["candidates"][0]["name"] == "Bus stop · Pelleautier - Le Lozeron"
        assert body["candidates"][0]["type"] == "highway"

    async def test_closest_named_poi_name_dropped_from_address(self):
        """Nominatim's closest object is a different named POI (the school
        building under the restaurant click): its name is dropped from the
        display and the address — "Indian Zayeka, 8, Rue de la Mouline, …",
        not "Indian Zayeka, Life School Lausanne, 8, …". Roads keep their
        name (the road IS the address)."""
        nom = {
            "display_name": (
                "Life School Lausanne, 8, Rue de la Mouline, Chavannes-près-Renens"
            ),
            "name": "Life School Lausanne",
            "class": "amenity",
            "type": "school",
        }
        osm = [
            {
                "type": "node",
                "lat": 37.00001,
                "lon": -122.0,
                "tags": {"amenity": "restaurant", "name": "Indian Zayeka"},
            }
        ]
        resp, _ = await self._reverse(nom, osm)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == (
            "Indian Zayeka, 8, Rue de la Mouline, Chavannes-près-Renens"
        )
        assert body["name"] == "Indian Zayeka"
        assert body["address"] == "8, Rue de la Mouline, Chavannes-près-Renens"

    async def test_road_name_kept_in_address_when_prepending_poi(self):
        """A road as Nominatim's closest object keeps its name in the
        address — the road IS the address."""
        nom = {
            "display_name": "Route du Lozeron, Pelleautier, Gap",
            "name": "Route du Lozeron",
            "class": "highway",
            "type": "tertiary",
        }
        osm = [
            {
                "type": "node",
                "lat": 37.00001,
                "lon": -122.0,
                "tags": {"amenity": "restaurant", "name": "Indian Zayeka"},
            }
        ]
        resp, _ = await self._reverse(nom, osm)
        body = json.loads(bytes(resp.body))
        assert body["display_name"] == (
            "Indian Zayeka, Route du Lozeron, Pelleautier, Gap"
        )
        assert body["address"] == "Route du Lozeron, Pelleautier, Gap"

    async def test_candidates_sorted_by_distance_only(self):
        """No category ranking anymore: the closest reviewable place wins,
        even if it's a parking and a shop is nearby."""
        osm = [
            {
                "type": "node",
                "lat": 37.00002,
                "lon": -122.0,
                "tags": {"amenity": "parking"},
            },
            {
                "type": "way",
                "center": {"lat": 37.0002, "lon": -122.0},
                "tags": {"name": "Coop", "shop": "supermarket"},
            },
        ]

        async def get_impl(url, params):
            return _FakeResp(200, text=_elements_xml(osm))

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            poi = await self.places.nearest_poi(37.0, -122.0)
        assert poi is not None
        assert poi["name"] == "Parking"
        assert poi["type"] == "amenity"

    async def test_nominatim_502_but_poi_answers(self):
        """Nominatim down/rate-limited: an OSM-API POI alone still gives the
        user a name (200), instead of a bare 502."""
        osm = [
            {
                "type": "node",
                "lat": 37.00001,
                "lon": -122.0,
                "tags": {"name": "Cafe Foo", "amenity": "cafe"},
            }
        ]

        async def get_impl(url, params):
            if "nominatim" in url:
                raise httpx.RequestError("rate limited")
            return _FakeResp(200, text=_elements_xml(osm))

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            resp = await self.places.reverse_geocode(37.0, -122.0)
        body = json.loads(bytes(resp.body))
        assert resp.status_code == 200
        assert body["display_name"] == "Cafe Foo"
        assert body["name"] == "Cafe Foo"

    async def test_nominatim_502_and_osm_down_still_502(self):
        async def get_impl(url, params):
            raise httpx.RequestError("down")

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            with self.assertRaises(HTTPException) as cm:
                await self.places.reverse_geocode(37.0, -122.0)
        assert cm.exception.status_code == 502

    async def test_nearest_poi_picks_closest_and_reports_type(self):
        osm = [
            {
                "type": "node",
                "lat": 37.001,
                "lon": -122.0,
                "tags": {"name": "Far Shop", "shop": "supermarket"},
            },
            {
                "type": "node",
                "lat": 37.00005,
                "lon": -122.0,
                "tags": {"name": "Near Hospital", "amenity": "hospital"},
            },
        ]
        gets: list[str] = []

        async def get_impl(url, params):
            gets.append(url)
            return _FakeResp(200, text=_elements_xml(osm))

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            poi = await self.places.nearest_poi(37.0, -122.0)
            # Same point again → served from the cache, no second call.
            poi2 = await self.places.nearest_poi(37.0, -122.0)
        assert poi is not None and poi2 is not None
        assert poi["name"] == "Near Hospital"
        assert poi["type"] == "amenity"
        assert poi["distance_m"] < 10
        assert poi2 == poi
        assert len(gets) == 1

    async def test_nearest_poi_handles_way_centers(self):
        """Ways come back with a centroid — still usable."""
        osm = [
            {
                "type": "way",
                "center": {"lat": 37.0001, "lon": -122.0},
                "tags": {"name": "Big Mall", "shop": "mall"},
            }
        ]

        async def get_impl(url, params):
            return _FakeResp(200, text=_elements_xml(osm))

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            poi = await self.places.nearest_poi(37.0, -122.0)
        assert poi is not None
        assert poi["name"] == "Big Mall"
        assert poi["type"] == "shop"

    async def test_nearest_poi_none_when_nothing_named_nearby(self):
        async def get_impl(url, params):
            return _FakeResp(200, text=_elements_xml([]))

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            assert await self.places.nearest_poi(37.0, -122.0) is None


class TestOsmPoiSource(AsyncTestCase):
    """The OSM API map bbox is the POI source: one throttled, cached call per
    area; failures return None and are never cached."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.places = Places(decimals=4, base_url="http://testserver")

    async def test_bbox_call_is_cached(self):
        calls: list[tuple[str, Any]] = []

        async def get_impl(url, params):
            calls.append((url, params))
            return _FakeResp(200, text=_elements_xml([]))

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            assert await self.places.pois_near(37.0, -122.0) == []
            assert await self.places.pois_near(37.0, -122.0) == []
        assert len(calls) == 1
        assert "api.openstreetmap.org" in calls[0][0]
        assert "bbox" in calls[0][1]

    async def test_osm_error_returns_empty_and_is_not_cached(self):
        calls: list[str] = []

        async def get_impl(url, params):
            calls.append(url)
            raise httpx.RequestError("down")

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            assert await self.places.pois_near(37.0, -122.0) == []
            assert await self.places.pois_near(37.0, -122.0) == []
        assert len(calls) == 2  # failures are not cached

    async def test_pois_parsed_from_osm_xml(self):
        """Nodes, ways (centroid of member nodes), unnamed parkings and named
        roads all come through, sorted by distance; same-named road segments
        collapse into one entry."""
        xml = (
            "<osm>"
            '<node id="1" lat="37.00004" lon="-122.0">'
            '<tag k="amenity" v="fast_food"/><tag k="name" v="McDonald&apos;s"/></node>'
            '<node id="2" lat="37.0001" lon="-122.0">'
            '<tag k="amenity" v="parking"/></node>'
            '<way id="9"><nd ref="1"/><nd ref="2"/>'
            '<tag k="shop" v="supermarket"/><tag k="name" v="Coop"/></way>'
            '<way id="10"><nd ref="1"/><nd ref="2"/>'
            '<tag k="highway" v="residential"/>'
            '<tag k="name" v="Route de Neffes"/></way>'
            # A second segment of the same road — must be deduped to one entry.
            '<way id="11"><nd ref="2"/><nd ref="1"/>'
            '<tag k="highway" v="residential"/>'
            '<tag k="name" v="Route de Neffes"/></way>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            pois = await self.places.pois_near(37.0, -122.0)
        # Distance only: McDo node 4.4 m, Coop way and road way 4.4 m (ways
        # get the centroid as position, nearest member node as distance),
        # parking node 11.1 m; same-named road segments collapse into one.
        assert [p["name"] for p in pois] == [
            "McDonald's",
            "Coop",
            "Route de Neffes",
            "Parking",
        ]
        road = pois[2]
        assert road["type"] == "highway"
        assert "rank" not in road

    async def test_townhall_in_list_and_way_distance_uses_nearest_node(self):
        """Regression: at Pelleautier the town hall (amenity=townhall, ~1 m)
        must be in the candidate list; a school *way* is measured to its
        nearest member node, not its centroid."""
        xml = (
            "<osm>"
            '<node id="1" lat="37.00001" lon="-122.0">'
            '<tag k="amenity" v="townhall"/>'
            '<tag k="name" v="Mairie de Pelleautier"/></node>'
            '<node id="2" lat="37.00002" lon="-122.0">'
            '<tag k="amenity" v="parking"/></node>'
            '<node id="3" lat="37.00005" lon="-122.0"/>'
            '<node id="4" lat="37.001" lon="-122.0"/>'
            '<way id="9"><nd ref="3"/><nd ref="4"/>'
            '<tag k="amenity" v="school"/><tag k="name" v="École primaire"/></way>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            pois = await self.places.pois_near(37.0, -122.0, limit=10)
        by_name = {p["name"]: p for p in pois}
        # Town hall: in the list, ~1 m away, sorted by distance first.
        assert by_name["Mairie de Pelleautier"]["distance_m"] < 2
        assert by_name["Mairie de Pelleautier"]["type"] == "amenity"
        assert [p["name"] for p in pois] == [
            "Mairie de Pelleautier",
            "Parking",
            "École primaire",
        ]
        # School way: distance to the NEAREST member node (~5.5 m), not to
        # the centroid (~60 m); the centroid stays the snap position.
        school = by_name["École primaire"]
        assert school["distance_m"] < 10
        assert school["lat"] == (37.00005 + 37.001) / 2

    async def test_unnamed_amenity_icons_get_synthesized_labels(self):
        """Map icons for unnamed amenities (library, toy library, …) appear
        with a label synthesized from the amenity value; utility amenities
        (toilets, benches, …) stay out under the default REVIEWABLE_TAGS."""
        xml = (
            "<osm>"
            '<node id="1" lat="37.00001" lon="-122.0">'
            '<tag k="amenity" v="library"/></node>'
            '<node id="2" lat="37.00002" lon="-122.0">'
            '<tag k="amenity" v="toy_library"/></node>'
            '<node id="3" lat="37.00003" lon="-122.0">'
            '<tag k="amenity" v="toilets"/></node>'
            '<node id="4" lat="37.00004" lon="-122.0">'
            '<tag k="amenity" v="townhall"/><tag k="name" v="Mairie"/></node>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            pois = await self.places.pois_near(37.0, -122.0)
        names = [p["name"] for p in pois]
        assert names == ["Library", "Toy library", "Mairie"]  # by distance
        assert all(p["type"] == "amenity" for p in pois)
        assert "Toilets" not in names

    async def test_unnamed_leisure_ways_get_synthesized_labels(self):
        """Parks/playgrounds are often unnamed ways (the park at Pelleautier):
        they appear as "Playground"/"Pitch" via the leisure value — while an
        unnamed highway way stays out (a road needs a name to be a place)."""
        xml = (
            "<osm>"
            '<node id="1" lat="37.00001" lon="-122.0"/>'
            '<node id="2" lat="37.00001" lon="-122.00002"/>'
            '<node id="3" lat="37.00002" lon="-122.00002"/>'
            '<node id="4" lat="37.00002" lon="-122.0"/>'
            '<node id="5" lat="37.00003" lon="-122.0"/>'
            '<node id="6" lat="37.00003" lon="-122.00001"/>'
            '<node id="7" lat="37.00004" lon="-122.0"/>'
            '<node id="8" lat="37.00004" lon="-122.00001"/>'
            '<way id="20"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/>'
            '<tag k="leisure" v="playground"/></way>'
            '<way id="21"><nd ref="5"/><nd ref="6"/>'
            '<tag k="leisure" v="pitch"/></way>'
            '<way id="22"><nd ref="7"/><nd ref="8"/>'
            '<tag k="highway" v="footway"/></way>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            pois = await self.places.pois_near(37.0, -122.0)
        by_name = {p["name"]: p for p in pois}
        assert by_name["Playground"]["type"] == "leisure"
        assert by_name["Pitch"]["type"] == "leisure"
        # Way position = centroid (the snap point), distance = nearest node.
        assert by_name["Playground"]["lat"] == (37.00001 + 37.00002) / 2
        assert by_name["Playground"]["distance_m"] < 3
        # Unnamed roads never appear.
        assert all(p["type"] != "highway" for p in pois)
        # Distance sort only: playground ~1.5 m before pitch ~3.3 m.
        assert [p["name"] for p in pois] == ["Playground", "Pitch"]

    async def test_transit_stops_get_kind_qualified_labels(self):
        """A bus stop named after a hamlet ("Pelleautier - Le Lozeron") is
        labeled "Bus stop · …" — recognizable as a stop, not a hamlet. Its
        same-named platform collapses into the same entry (dedup on the raw
        name); an unnamed stop appears as "Bus stop"; unnamed roadside
        features (give_way, …) stay out."""
        xml = (
            "<osm>"
            '<node id="1" lat="37.00001" lon="-122.0">'
            '<tag k="highway" v="bus_stop"/>'
            '<tag k="name" v="Pelleautier - Le Lozeron"/>'
            '<tag k="public_transport" v="stop_position"/></node>'
            '<node id="2" lat="37.00002" lon="-122.0">'
            '<tag k="highway" v="platform"/>'
            '<tag k="name" v="Pelleautier - Le Lozeron"/></node>'
            '<node id="3" lat="37.00003" lon="-122.0">'
            '<tag k="highway" v="bus_stop"/></node>'
            '<node id="4" lat="37.00004" lon="-122.0">'
            '<tag k="highway" v="give_way"/></node>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            pois = await self.places.pois_near(37.0, -122.0)
        names = [p["name"] for p in pois]
        assert names == ["Bus stop · Pelleautier - Le Lozeron", "Bus stop"]
        assert pois[0]["type"] == "highway"
        assert pois[0]["distance_m"] < 2  # the stop node, not the platform
        assert all(p["name"] != "Give way" for p in pois)

    async def test_peaks_and_passes_are_candidates(self):
        """``natural=peak``/``natural=saddle`` are in the default filter: a
        named peak keeps its name, an unnamed pass is labeled "Pass" (not
        "Saddle"), and other natural features (trees, …) stay out."""
        xml = (
            "<osm>"
            '<node id="1" lat="37.00001" lon="-122.0">'
            '<tag k="natural" v="peak"/><tag k="name" v="Mont Test"/>'
            '<tag k="ele" v="2508"/></node>'
            '<node id="2" lat="37.00002" lon="-122.0">'
            '<tag k="natural" v="saddle"/></node>'
            '<node id="3" lat="37.00003" lon="-122.0">'
            '<tag k="natural" v="tree"/></node>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            pois = await self.places.pois_near(37.0, -122.0)
        assert [p["name"] for p in pois] == ["Mont Test", "Pass"]
        assert all(p["type"] == "natural" for p in pois)

    async def test_radius_covers_nearby_peak_but_drops_far_relation_members(self):
        """A peak ~100 m away is within the default radius and shows up; a
        same-named stop 300+ m away (a relation member dragged into the map
        response) is beyond 1.5·r and dropped."""
        # 0.00087° lat ≈ 96.6 m; 0.003° lat ≈ 334 m.
        xml = (
            "<osm>"
            '<node id="1" lat="37.00087" lon="-122.0">'
            '<tag k="natural" v="peak"/><tag k="name" v="First"/>'
            '<tag k="ele" v="2440"/></node>'
            '<node id="2" lat="37.003" lon="-122.0">'
            '<tag k="highway" v="bus_stop"/><tag k="name" v="Far stop"/></node>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            pois = await self.places.pois_near(37.0, -122.0)
        assert [p["name"] for p in pois] == ["First"]
        assert 90 < pois[0]["distance_m"] < 105  # ~96.6 m, not dropped

    async def test_named_road_alone_is_the_top_candidate(self):
        """Clicking mid-road with no POI nearby: the road is the place, at
        its canonical (centroid) position — so every review of the same road
        lands in the same bucket."""
        xml = (
            "<osm>"
            '<node id="1" lat="37.0" lon="-122.0"/>'
            '<node id="2" lat="37.001" lon="-122.0"/>'
            '<way id="10"><nd ref="1"/><nd ref="2"/>'
            '<tag k="highway" v="residential"/>'
            '<tag k="name" v="Route de Neffes"/></way>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            pois = await self.places.pois_near(37.0, -122.0)
        assert len(pois) == 1
        assert pois[0]["name"] == "Route de Neffes"
        assert pois[0]["type"] == "highway"
        # Centroid of the two member nodes — the canonical road position.
        assert pois[0]["lat"] == 37.0005
        assert pois[0]["lon"] == -122.0


class TestPlaceObject(AsyncTestCase):
    """places.at(lat, lng) builds a Place object holding the place's DB data,
    with review_by / add_review / update_review on it."""

    async def _make_actor(self, username: str) -> dict:
        actor = await create_actor(
            username=username,
            display_name=username.title(),
            summary="",
            private_key_pem="",
            public_key_pem="",
            actor_uri=f"http://testserver/actor/{username}",
            inbox_uri=f"http://testserver/actor/{username}/inbox",
            outbox_uri=f"http://testserver/actor/{username}/outbox",
            followers_uri=f"http://testserver/actor/{username}/followers",
            following_uri=f"http://testserver/actor/{username}/following",
        )
        assert actor is not None
        return actor

    async def _make_review(
        self, actor_id: int, ap_id: str, lat: float, lng: float, **kwargs
    ):
        return await reviews.create(
            actor_id=actor_id,
            ap_id=ap_id,
            content=kwargs.get("content", "x"),
            rating=kwargs.get("rating", 3),
            latitude=lat,
            longitude=lng,
            place_name=kwargs.get("place_name", ""),
            place_address=kwargs.get("place_address", ""),
        )

    async def test_at_loads_reviews_from_db(self):
        alice = await self._make_actor("alice")
        bob = await self._make_actor("bob")
        await self._make_review(
            alice["id"],
            "http://testserver/actor/alice/review/1",
            37.0,
            -122.0,
            content="alice",
            rating=5,
            place_name="Cafe",
            place_address="1 Main St",
        )
        # Same bucket, slightly different raw coordinates
        await self._make_review(
            bob["id"],
            "http://testserver/actor/bob/review/1",
            37.00004,
            -122.00004,
            content="bob",
            rating=3,
            place_name="Cafe",
        )

        p = await places.at(37.0, -122.0)
        assert p.key == "37.0000,-122.0000"
        assert p.lat == 37.0 and p.lng == -122.0
        assert {r["content"] for r in p.reviews} == {"alice", "bob"}
        alice_r = p.review_by(alice["id"])
        bob_r = p.review_by(bob["id"])
        assert alice_r is not None and bob_r is not None
        assert alice_r["content"] == "alice"
        assert bob_r["content"] == "bob"
        # Derived info mirrors the map UI's place grouping.
        assert p.name == "Cafe"
        assert p.address == "1 Main St"
        assert p.avg_rating == 4.0

    async def test_at_empty_place(self):
        p = await places.at(10.0, 20.0)
        assert p.reviews == []
        assert p.name == "" and p.address == "" and p.avg_rating is None
        assert p.review_by(999) is None

    async def test_at_snaps_to_nearest_reviewable_place(self):
        """at() lands on the nearest OSM candidate's coordinates: search-result
        coordinates and a raw map click near the same POI then share one
        bucket (one place, no duplicate reviews). When the OSM lookup fails,
        it falls back to the raw coordinates."""
        xml = (
            "<osm>"
            '<node id="1" lat="37.00008" lon="-122.00006">'
            '<tag k="amenity" v="restaurant"/>'
            '<tag k="name" v="Indian Zayeka"/></node>'
            "</osm>"
        )

        async def get_impl(url, params):
            return _FakeResp(200, text=xml)

        async def failing_impl(url, params):
            raise httpx.RequestError("boom")

        manager = Places(decimals=4, base_url="http://testserver")
        with patch("app.places.places.httpx.AsyncClient", _fake_client_get(get_impl)):
            p = await manager.at(37.0, -122.0)
        # Snapped to the restaurant node (~10 m away), not the raw click —
        # a different bucket than the raw coordinates would give.
        assert (p.lat, p.lng) == (37.00008, -122.00006)
        assert p.key == "37.0001,-122.0001"

        # OSM API down: fall back to the raw coordinates (fresh manager — the
        # first one's bbox cache still holds the candidate).
        down = Places(decimals=4, base_url="http://testserver")
        with patch(
            "app.places.places.httpx.AsyncClient", _fake_client_get(failing_impl)
        ):
            p2 = await down.at(37.0, -122.0)
        assert (p2.lat, p2.lng) == (37.0, -122.0)
        assert p2.key == "37.0000,-122.0000"

    async def test_at_same_bucket_compares_equal(self):
        """Place.__eq__ on loaded objects: two clicks in the same bucket are
        the same place."""
        alice = await self._make_actor("alice")
        await self._make_review(
            alice["id"], "http://testserver/actor/alice/review/1", 37.00002, -122.0
        )
        p1 = await places.at(37.0, -122.0)
        p2 = await places.at(37.00004, -122.0)
        assert p1 == p2
        assert p1 != await places.at(37.001, -122.0)

    async def test_at_ignores_other_buckets(self):
        alice = await self._make_actor("alice")
        await self._make_review(
            alice["id"], "http://testserver/actor/alice/review/1", 37.0, -122.0
        )
        assert (await places.at(37.001, -122.0)).reviews == []
        assert (await places.at(37.0, -122.0)).reviews != []

    async def test_reviews_at_reloads_from_db(self):
        """Place.reviews_at() is the place-scoped DB query — it reflects new
        rows written after the object was built."""
        alice = await self._make_actor("alice")
        bob = await self._make_actor("bob")
        await self._make_review(
            alice["id"], "http://testserver/actor/alice/review/1", 37.0, -122.0
        )
        p = await places.at(37.0, -122.0)
        assert len(p.reviews) == 1

        # A review written straight to the DB after the load...
        await self._make_review(
            bob["id"], "http://testserver/actor/bob/review/1", 37.00002, -122.0
        )
        assert len(p.reviews) == 1  # ...not yet in the object
        fresh = await p.reviews_at()  # ...until re-queried
        assert len(fresh) == 2
        assert {r["actor_id"] for r in fresh} == {alice["id"], bob["id"]}

    async def test_add_review_creates_and_syncs_object(self):
        alice = await self._make_actor("alice")
        p = await places.at(37.0, -122.0)
        review = await p.add_review(alice, content="Great", rating=5, place_name="Cafe")
        assert review["content"] == "Great"
        assert review["latitude"] == 37.0 and review["longitude"] == -122.0
        assert review["ap_id"].startswith("http://testserver/actor/alice/review/")
        # The object holds the new review, and it is in the DB.
        mine = p.review_by(alice["id"])
        assert mine is not None
        assert mine["id"] == review["id"]
        assert len((await places.at(37.0, -122.0)).reviews) == 1

    async def test_add_review_enforces_one_per_actor_per_place(self):
        alice = await self._make_actor("alice")
        p = await places.at(37.0, -122.0)
        first = await p.add_review(alice, content="First", rating=4)
        with self.assertRaises(AlreadyReviewed) as cm:
            await p.add_review(alice, content="Second", rating=1)
        assert cm.exception.review["id"] == first["id"]
        # Still exactly one review at the place.
        assert len((await places.at(37.0, -122.0)).reviews) == 1

    async def test_add_review_allows_other_actors_same_place(self):
        """Sharing coordinates across actors is not a duplicate."""
        alice = await self._make_actor("alice")
        bob = await self._make_actor("bob")
        p = await places.at(37.0, -122.0)
        await p.add_review(alice, content="Alice", rating=5)
        review = await p.add_review(bob, content="Bob", rating=3)
        assert review["actor_id"] == bob["id"]
        assert len(p.reviews) == 2

    async def test_update_review(self):
        alice = await self._make_actor("alice")
        p = await places.at(37.0, -122.0)
        review = await p.add_review(alice, content="Old", rating=2)

        # A fresh place object (as the PUT route builds it) updates the review.
        p2 = await places.at(37.0, -122.0)
        updated = await p2.update_review(
            review["id"], content="New", rating=5, place_name="Cafe"
        )
        assert updated is not None
        assert updated["content"] == "New" and updated["rating"] == 5
        # Kept at the place's coordinates.
        assert updated["latitude"] == 37.0 and updated["longitude"] == -122.0
        # The object's review list is synced.
        mine = p2.review_by(alice["id"])
        assert mine is not None
        assert mine["content"] == "New"
        # Unknown ID → None.
        assert await p2.update_review(9999, content="x", rating=1) is None


class TestMetaExposesPlaceDecimals(AsyncTestCase):
    """The SPA reads the runtime place precision from /api/meta."""

    async def test_meta_includes_place_decimals(self):
        resp = await self.client.get("/api/meta")
        assert resp.status_code == 200
        data = resp.json()
        assert data["place_decimals"] == config.place_decimals == 4
        assert data["registration_mode"] == "open"
