"""
Actor helpers — build ActivityPub JSON representations and handle
follow / accept flows.
"""

from typing import Any

from app.models import Accept, Actor, Follow, OrderedCollection


def actor_to_ap(actor_row: dict[str, Any]) -> Actor:
    """Convert a database actor row to an ActivityPub Actor object."""
    return Actor(
        id=actor_row["actor_uri"],
        preferredUsername=actor_row["username"],
        name=actor_row["display_name"],
        summary=actor_row["summary"],
        inbox=actor_row["inbox_uri"],
        outbox=actor_row["outbox_uri"],
        followers=actor_row["followers_uri"],
        following=actor_row["following_uri"],
        publicKey={
            "id": f"{actor_row['actor_uri']}#main-key",
            "owner": actor_row["actor_uri"],
            "publicKeyPem": actor_row["public_key_pem"],
        },
    )


def build_follow_activity(
    follower_uri: str,
    target_actor_uri: str,
) -> Follow:
    """Build a Follow activity sent from follower to target."""
    return Follow(
        id=f"{follower_uri}/follow/{target_actor_uri.split('/')[-1]}",
        actor=follower_uri,
        object={"id": target_actor_uri, "type": "Person"},
        to=[target_actor_uri],
    )


def build_accept_activity(
    target_actor_uri: str,
    follow_activity: dict[str, Any],
) -> Accept:
    """Build an Accept activity in response to a Follow."""
    follow_id = follow_activity.get("id", "")
    return Accept(
        id=f"{target_actor_uri}/accept/{follow_id.split('/')[-1]}",
        actor=target_actor_uri,
        object=follow_activity,
        to=[follow_activity.get("actor", "")],
    )


def build_empty_collection(uri: str) -> OrderedCollection:
    """Return an empty OrderedCollection for a given URI."""
    return OrderedCollection(
        id=uri,
        totalItems=0,
        first=f"{uri}?page=1",
        last=f"{uri}?page=1",
    )
