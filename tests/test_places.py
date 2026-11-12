"""Tests for app.places — Places (the manager: runtime PLACE_DECIMALS
bucketing, Nominatim proxy, Place factory) and Place (a single place loaded
from the DB, with add/update/review_by on it)."""

import json
import os
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.config import Config, config
from app.db import create_actor, create_review
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
    def __init__(self, status_code: int, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}

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
        calls = []

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
        calls = []

        async def get_impl(url, params):
            calls.append(params)
            return _FakeResp(200, [])

        await self._get("/search", {"q": "a"}, get_impl)
        await self._get("/search", {"q": "b"}, get_impl)
        assert len(calls) == 2

    async def test_cache_expires_after_ttl(self):
        calls = []

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
        sleeps = []

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
        sleeps = []

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
        calls = []

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
        return await create_review(
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
