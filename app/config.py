import os
from urllib.parse import urlsplit

DEFAULT_DATABASE_URL = "sqlite:///data/app.db"
DEFAULT_PUBLIC_ORIGIN = "http://localhost:8000"


def get_database_url() -> str:
    """Return the configured SQLAlchemy database URL."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_public_host() -> str:
    """Return the one Host header allowed for the configured public origin."""
    public_origin = os.getenv("PUBLIC_ORIGIN", DEFAULT_PUBLIC_ORIGIN)
    host = urlsplit(public_origin).hostname
    if host is None:
        raise ValueError("PUBLIC_ORIGIN must be an absolute URL")
    return host
