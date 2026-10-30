"""Application configuration — read from environment or defaults."""

import logging
import os
import secrets
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Load .env file before reading any environment variables
load_dotenv()

logger = logging.getLogger("federated-reviews.config")


def _get_secret_key() -> str:
    """Return the configured secret key, or generate a random one with a warning."""
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    key = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY environment variable is not set — generated a random key. "
        "Sessions will be invalidated on every restart. "
        "Set SECRET_KEY in production."
    )
    return key


@dataclass
class Config:
    """Server-wide configuration."""

    # The public base URL of this server (e.g. "https://reviews.example.com").
    # ActivityPub IDs are all derived from this.
    base_url: str = field(
        default_factory=lambda: os.getenv("BASE_URL", "http://localhost:8000")
    )

    # Host/port for the uvicorn server.
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))

    # Path to the SQLite database file.
    database_path: str = field(
        default_factory=lambda: os.getenv("DATABASE_PATH", "data/reviews.db")
    )

    # Secret key for session signing — generated randomly if SECRET_KEY is not set.
    secret_key: str = field(default_factory=_get_secret_key)

    # Enable uvicorn auto-reload (development only — off unless asked for).
    reload: bool = field(
        default_factory=lambda: (
            os.getenv("RELOAD", "false").lower() in ("1", "true", "yes")
        )
    )

    # Domain extracted from base_url — used for WebFinger.
    # Includes the port for non-standard ports (e.g. "localhost:8000").
    @property
    def domain(self) -> str:
        return self.base_url.split("://", 1)[1].split("/")[0]


config = Config()
