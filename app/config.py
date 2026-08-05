import os
from urllib.parse import urlsplit

DEFAULT_DATABASE_URL = "sqlite:///data/app.db"
DEFAULT_PUBLIC_ORIGIN = "http://localhost:8000"


def get_database_url() -> str:
    """Return the configured SQLAlchemy database URL."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def normalize_authority(authority: str) -> str:
    """Normalize a host[:port] authority or reject malformed input."""
    if not authority or authority != authority.strip() or authority.endswith(":"):
        raise ValueError("authority must contain a valid host and optional port")

    parsed = urlsplit(f"//{authority}")
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("authority must contain only a host and optional port")

    port = parsed.port  # Access validates the port syntax and range.
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{host}:{port}" if port is not None else host


def get_public_authority() -> str:
    """Return the one Host authority allowed for the public origin."""
    public_origin = os.getenv("PUBLIC_ORIGIN", DEFAULT_PUBLIC_ORIGIN)
    parsed = urlsplit(public_origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("PUBLIC_ORIGIN must be an HTTP(S) origin")
    return normalize_authority(parsed.netloc)
