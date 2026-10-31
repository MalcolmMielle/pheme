"""Pydantic models for auth form validation.

Used by the public registration form (``routes/web.py``) and the admin
account-creation endpoint (``routes/api.py``) — all input validation lives in
these models, not in hand-written checks inside the handlers.
"""

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import config

# Usernames end up in ActivityPub URIs (/actor/<username>), so they must be
# lowercase, URL-safe and reasonably short.
USERNAME_PATTERN = r"^[a-z0-9_]{1,30}$"

# Names that collide with top-level routes of this server.
RESERVED_USERNAMES = frozenset(
    {
        "login",
        "register",
        "logout",
        "review",
        "static",
        "api",
        "actor",
        "inbox",
        "outbox",
        "followers",
        "following",
        "assets",
        "well-known",
    }
)


class RegisterForm(BaseModel):
    """Registration / admin-create form fields, validated by Pydantic."""

    username: str = Field(pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(max_length=128)

    @field_validator("username")
    @classmethod
    def username_not_reserved(cls, value: str) -> str:
        if value in RESERVED_USERNAMES:
            raise ValueError("this username is reserved")
        return value

    @field_validator("display_name", mode="before")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, value: str) -> str:
        if len(value) < config.password_min_length:
            raise ValueError(
                f"password must be at least {config.password_min_length} characters"
            )
        return value


def first_validation_error(exc: ValidationError) -> str:
    """Human-readable message for the first error of a ValidationError."""
    err = exc.errors()[0]
    field = err["loc"][0] if err["loc"] else "field"
    return f"{field}: {err['msg']}"
