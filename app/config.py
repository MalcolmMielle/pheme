"""Application configuration — read from environment or defaults."""

import os
from dataclasses import dataclass, field


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

    # Domain extracted from base_url — used for WebFinger.
    # Includes the port for non-standard ports (e.g. "localhost:8000").
    @property
    def domain(self) -> str:
        return self.base_url.split("://", 1)[1].split("/")[0]

    # Unique identifier for this server node.
    @property
    def node_id(self) -> str:
        return f"{self.base_url}/actor/server"


config = Config()
