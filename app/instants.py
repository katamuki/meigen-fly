"""Codec for "instant" columns stored as fixed-length UTC TEXT (ADR 011).

Every timestamp column (created_at, updated_at, like time, refreshed_at, ...)
stores exactly ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (27 characters). Values must pass
through ``format_instant`` on the way in and ``parse_instant`` on the way out so
that string order equals time order.
"""

from datetime import UTC, datetime

INSTANT_LENGTH = 27
_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def format_instant(value: datetime) -> str:
    """Serialize a timezone-aware datetime to the fixed-length UTC form."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("instant must be timezone-aware")
    text = value.astimezone(UTC).strftime(_FORMAT)
    if len(text) != INSTANT_LENGTH:
        raise ValueError(f"instant out of supported range: {value!r}")
    return text


def parse_instant(text: str) -> datetime:
    """Parse the fixed-length UTC form back to an aware UTC datetime."""
    if len(text) != INSTANT_LENGTH or not text.endswith("Z"):
        raise ValueError(f"malformed instant: {text!r}")
    return datetime.strptime(text, _FORMAT).replace(tzinfo=UTC)


def is_instant(text: object) -> bool:
    """Return True when ``text`` is a valid fixed-length UTC instant."""
    if not isinstance(text, str):
        return False
    try:
        parse_instant(text)
    except ValueError:
        return False
    return True
