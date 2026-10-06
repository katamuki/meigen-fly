import os
from urllib.parse import urlsplit

DEFAULT_DATABASE_URL = "sqlite:///data/app.db"
DEFAULT_PUBLIC_ORIGIN = "http://localhost:8000"
DEFAULT_LIKE_RATE_LIMIT_REQUESTS = 10
DEFAULT_LIKE_RATE_LIMIT_WINDOW_SECONDS = 10.0
DEFAULT_SEARCH_RATE_LIMIT_REQUESTS = 30
DEFAULT_SEARCH_RATE_LIMIT_WINDOW_SECONDS = 10.0


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


def get_public_origin() -> str:
    """Return the normalized HTTP(S) origin used by public requests."""
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
    return f"{parsed.scheme}://{normalize_authority(parsed.netloc)}"


def get_public_authority() -> str:
    """Return the one Host authority allowed for the public origin."""
    return urlsplit(get_public_origin()).netloc


def get_cf_access_team_domain() -> str | None:
    """Return the Cloudflare Access team origin without a trailing slash."""
    value = os.getenv("CF_ACCESS_TEAM_DOMAIN", "").strip()
    if not value:
        return None
    value = value.rstrip("/")
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    suffix = ".cloudflareaccess.com"
    team = hostname.removesuffix(suffix)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != hostname
        or not team
        or not hostname.endswith(suffix)
        or team.startswith("-")
        or team.endswith("-")
        or not all(
            character.isascii() and (character.isalnum() or character == "-")
            for character in team
        )
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "CF_ACCESS_TEAM_DOMAIN must be https://<team>.cloudflareaccess.com"
        )
    return f"https://{hostname}"


def get_cf_access_aud() -> str | None:
    """Return the Cloudflare Access application audience."""
    return os.getenv("CF_ACCESS_AUD", "").strip() or None


def get_cf_zone_id() -> str | None:
    """Return the Cloudflare zone used for cache purges."""
    return os.getenv("CF_ZONE_ID", "").strip() or None


def get_cf_api_token() -> str | None:
    """Return the Cloudflare API token used for cache purges."""
    return os.getenv("CF_API_TOKEN", "").strip() or None


def get_secret_key() -> str | None:
    """Return the secret used to sign admin CSRF tokens."""
    return os.getenv("SECRET_KEY", "") or None


def get_admin_dev_email() -> str | None:
    """Return the optional local-only administrator email."""
    return os.getenv("ADMIN_DEV_EMAIL", "").strip() or None


def _rate_limit(
    prefix: str, default_requests: int, default_window_seconds: float
) -> tuple[int, float]:
    """Read one in-process rate limit from its pair of environment variables."""
    requests = int(os.getenv(f"{prefix}_RATE_LIMIT_REQUESTS", default_requests))
    window_seconds = float(
        os.getenv(f"{prefix}_RATE_LIMIT_WINDOW_SECONDS", default_window_seconds)
    )
    if requests < 1 or window_seconds <= 0:
        raise ValueError(f"{prefix.lower()} rate limit values must be positive")
    return requests, window_seconds


def get_like_rate_limit() -> tuple[int, float]:
    """Return the small, likes-only in-process rate limit."""
    return _rate_limit(
        "LIKE",
        DEFAULT_LIKE_RATE_LIMIT_REQUESTS,
        DEFAULT_LIKE_RATE_LIMIT_WINDOW_SECONDS,
    )


def get_search_rate_limit() -> tuple[int, float]:
    """Return the search-only in-process rate limit (ADR 015)."""
    return _rate_limit(
        "SEARCH",
        DEFAULT_SEARCH_RATE_LIMIT_REQUESTS,
        DEFAULT_SEARCH_RATE_LIMIT_WINDOW_SECONDS,
    )


def get_backup_r2_endpoint() -> str | None:
    """Return the R2 origin without a trailing slash."""
    return os.getenv("BACKUP_R2_ENDPOINT", "").strip().rstrip("/") or None


def get_backup_r2_bucket() -> str | None:
    """Return the backup destination bucket."""
    return os.getenv("BACKUP_R2_BUCKET", "").strip() or None


def get_backup_r2_prefix() -> str:
    """Return the object prefix, defaulting only when unset."""
    return os.getenv("BACKUP_R2_PREFIX", "daily/")


def get_backup_r2_access_key_id() -> str | None:
    """Return the access key ID for backup uploads."""
    return os.getenv("BACKUP_R2_ACCESS_KEY_ID", "").strip() or None


def get_backup_r2_secret_access_key() -> str | None:
    """Return the secret access key for backup uploads."""
    return os.getenv("BACKUP_R2_SECRET_ACCESS_KEY", "") or None


def get_uptimerobot_backup_heartbeat_url() -> str | None:
    """Return the optional secret backup heartbeat URL."""
    return os.getenv("UPTIMEROBOT_BACKUP_HEARTBEAT_URL", "").strip() or None


def get_uptimerobot_ranking_heartbeat_url() -> str | None:
    """Return the optional secret ranking heartbeat URL."""
    return os.getenv("UPTIMEROBOT_RANKING_HEARTBEAT_URL", "").strip() or None
