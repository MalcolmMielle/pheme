"""
Async SQLite database layer.

Package layout:
  connection   — init_db/close_db/get_db, SCHEMA, connection management
  actors       — actor CRUD, password hashing
  reviews      — review CRUD, bounds queries, pagination
  follows      — follow/follower relationships
  invites      — one-time invite codes for the "invite" registration mode

All public functions are re-exported here for backward compatibility:
    from app.db import create_actor, get_reviews, follow_actor, ...
"""

from app.db.actors import (
    count_admins,
    create_actor,
    delete_actor,
    get_actor_by_id,
    get_actor_by_uri,
    get_actor_by_username,
    hash_password,
    list_local_actors,
    set_actor_admin,
    set_actor_suspended,
    verify_password,
)
from app.db.connection import SCHEMA, close_db, get_db, init_db
from app.db.follows import (
    accept_follow,
    follow_actor,
    get_follower_inboxes,
    get_followers,
    get_following,
    get_following_actors,
    unfollow_actor,
)
from app.db.invites import (
    consume_invite,
    create_invite,
    delete_invite,
    get_valid_invite,
    list_invites,
)
from app.db.reviews import (
    count_reviews,
    count_reviews_by_bounds,
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
    "init_db",
    "close_db",
    "get_db",
    "SCHEMA",
    # actors
    "create_actor",
    "get_actor_by_id",
    "get_actor_by_uri",
    "get_actor_by_username",
    "list_local_actors",
    "set_actor_admin",
    "set_actor_suspended",
    "count_admins",
    "delete_actor",
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
    "count_reviews_by_bounds",
    # follows
    "follow_actor",
    "accept_follow",
    "get_followers",
    "get_follower_inboxes",
    "get_following",
    "get_following_actors",
    "unfollow_actor",
    # invites
    "create_invite",
    "get_valid_invite",
    "consume_invite",
    "list_invites",
    "delete_invite",
]
