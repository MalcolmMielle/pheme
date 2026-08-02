"""
Bootstrap script — create the first local actor and seed some example reviews.

Run once before starting the server:

    uv run bootstrap

Or programmatically:

    curl -X POST http://localhost:8000/api/bootstrap \\
         -d "username=alice&display_name=Alice"
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bootstrap")


async def _bootstrap() -> None:
    """Create a default actor and seed demo reviews."""
    from app.activitypub.signing import generate_keypair
    from app.config import config
    from app.db import (
        create_actor,
        create_review,
        get_actor_by_username,
        get_db,
        hash_password,
    )

    # ── Create default actor ────────────────────────────────────────────
    username = "alice"
    display_name = "Alice Reviewer"
    password = "alice"  # change after first login!
    existing = await get_actor_by_username(username)
    if existing:
        logger.info("Actor '%s' already exists — skipping.", username)
    else:
        priv, pub = generate_keypair()
        base = f"{config.base_url}/actor/{username}"
        actor = await create_actor(
            username=username,
            display_name=display_name,
            summary="Avid local reviewer",
            private_key_pem=priv,
            public_key_pem=pub,
            actor_uri=base,
            inbox_uri=f"{base}/inbox",
            outbox_uri=f"{base}/outbox",
            followers_uri=f"{base}/followers",
            following_uri=f"{base}/following",
            password_hash=hash_password(password),
        )
        logger.info("Created actor '%s' (%s).", username, actor["actor_uri"])
        logger.info("  → Login:  %s  /  %s", username, password)

    # ── Seed demo reviews around San Francisco ─────────────────────────
    actor_row = await get_actor_by_username(username)
    if not actor_row:
        logger.error("No actor found — cannot seed reviews.")
        return
    actor_id = actor_row["id"]
    base_uri = actor_row["actor_uri"]

    demo_reviews = [
        {
            "content": "Best sourdough in the city. The line is worth it — "
            "grab a loaf and walk to Dolores Park!",
            "rating": 5,
            "lat": 37.7650,
            "lng": -122.4233,
            "place": "Tartine Bakery",
            "address": "600 Guerrero St, San Francisco, CA 94110",
        },
        {
            "content": "Iconic landmark. Go at sunrise to avoid crowds and "
            "get incredible photos of the bridge and city skyline.",
            "rating": 5,
            "lat": 37.8199,
            "lng": -122.4783,
            "place": "Golden Gate Bridge Viewpoint",
            "address": "Golden Gate Bridge, San Francisco, CA",
        },
        {
            "content": "Great coffee and pastries. The hipster vibe is real "
            "but the pour-over is excellent. Limited seating.",
            "rating": 4,
            "lat": 37.7605,
            "lng": -122.4217,
            "place": "Four Barrel Coffee",
            "address": "375 Valencia St, San Francisco, CA 94103",
        },
        {
            "content": "Beautiful park with amazing views. Perfect for a "
            "weekend picnic. The Japanese Tea Garden is a must-see.",
            "rating": 5,
            "lat": 37.7694,
            "lng": -122.4862,
            "place": "Golden Gate Park",
            "address": "Golden Gate Park, San Francisco, CA",
        },
        {
            "content": "Overpriced and overcrowded. The chowder is fine but "
            "you can get better at half the price elsewhere.",
            "rating": 2,
            "lat": 37.8083,
            "lng": -122.4100,
            "place": "Fisherman's Wharf",
            "address": "Fisherman's Wharf, San Francisco, CA 94133",
        },
        {
            "content": "Incredible dim sum. Go early on weekends — the line "
            "gets crazy by 10am. Don't miss the xiao long bao.",
            "rating": 5,
            "lat": 37.7955,
            "lng": -122.4077,
            "place": "Dragon Beaux",
            "address": "5700 Geary Blvd, San Francisco, CA 94121",
        },
        {
            "content": "Stunning views of the bay and Alcatraz. Steep walk "
            "but totally worth it. Bring a jacket — it gets windy!",
            "rating": 4,
            "lat": 37.8024,
            "lng": -122.4058,
            "place": "Coit Tower",
            "address": "1 Telegraph Hill Blvd, San Francisco, CA 94133",
        },
        {
            "content": "Lush, tranquil garden tucked in the hills. A hidden "
            "gem — the bonsai collection is world-class.",
            "rating": 5,
            "lat": 37.7701,
            "lng": -122.4702,
            "place": "Japanese Tea Garden",
            "address": "75 Hagiwara Tea Garden Dr, San Francisco, CA 94118",
        },
    ]

    count = 0
    for i, r in enumerate(demo_reviews):
        ap_id = f"{base_uri}/review/demo-{i}"
        # Check if we've already seeded
        from app.db import review_exists

        if await review_exists(ap_id):
            continue
        await create_review(
            actor_id=actor_id,
            ap_id=ap_id,
            content=r["content"],
            rating=r["rating"],
            latitude=r["lat"],
            longitude=r["lng"],
            place_name=r["place"],
            place_address=r["address"],
        )
        count += 1

    logger.info(
        "Seeded %d demo review(s). Server is ready — run `uv run fedreviews`!",
        count,
    )

    db = await get_db()
    await db.close()


def main() -> None:
    """Entry point for `bootstrap` CLI command."""
    asyncio.run(_bootstrap())


if __name__ == "__main__":
    main()
