"""
Async SQLite database layer.

Package layout:
  connection   — get_db, SCHEMA, connection management
  actors       — actor CRUD, password hashing
  reviews      — review CRUD, bounds queries, pagination
  follows      — follow/follower relationships

All public functions are re-exported here for backward compatibility:
    from app.db import create_actor, get_reviews, follow_actor, ...
"""

from app.db.actors import (
    create_actor,
    get_actor_by_id,
    get_actor_by_uri,
    get_actor_by_username,
    hash_password,
    list_local_actors,
    verify_password,
)
from app.db.connection import SCHEMA, get_db
from app.db.follows import (
    accept_follow,
    follow_actor,
    get_follower_inboxes,
    get_followers,
    get_following,
)
from app.db.reviews import (
    count_reviews,
    create_review,
    delete_review,
    get_review_by_id,
    get_reviews,
    get_reviews_by_actor,
    get_reviews_by_bounds,
    review_exists,
)

__all__ = [
    # connection
    "get_db",
    "SCHEMA",
    # actors
    "create_actor",
    "get_actor_by_id",
    "get_actor_by_uri",
    "get_actor_by_username",
    "list_local_actors",
    "hash_password",
    "verify_password",
    # reviews
    "create_review",
    "delete_review",
    "get_review_by_id",
    "get_reviews",
    "get_reviews_by_actor",
    "get_reviews_by_bounds",
    "review_exists",
    "count_reviews",
    # follows
    "follow_actor",
    "accept_follow",
    "get_followers",
    "get_follower_inboxes",
    "get_following",
]
