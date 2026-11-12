"""The places package — place identity, Place objects, and geocoding.

One class per file:
  errors.py   — AlreadyReviewed
  place.py    — Place: one place on the map, loaded from the DB
  places.py   — Places: the manager (bucketing config, Nominatim proxy,
                Place factory) + the ``places`` singleton

Import from the package root: ``from app.places import Place, Places,
AlreadyReviewed, places``.
"""

from app.places.errors import AlreadyReviewed
from app.places.place import Place
from app.places.places import Places, places

__all__ = ["AlreadyReviewed", "Place", "Places", "places"]
