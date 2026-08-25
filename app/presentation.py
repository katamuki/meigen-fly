"""Presentation helpers shared by public quote surfaces."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

DisplayLanguage = Literal["ja", "en"]


@dataclass(frozen=True)
class QuoteDisplay:
    """Resolved primary and optional secondary text for one quote."""

    text: str
    language: DisplayLanguage
    alternate_text: str | None
    alternate_language: DisplayLanguage | None


def _filled(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def resolve_quote_display(quote: Mapping[str, object]) -> QuoteDisplay:
    """Resolve ADR 009's per-record display preference with fallback."""
    preference = quote.get("display_language_preference")
    if preference not in {"ja", "en"}:
        raise ValueError(f"invalid display language preference: {preference!r}")

    japanese = _filled(quote.get("text"))
    english = _filled(quote.get("text_en"))
    preferred = japanese if preference == "ja" else english
    fallback = english if preference == "ja" else japanese

    if preferred is not None:
        alternate_language: DisplayLanguage = "en" if preference == "ja" else "ja"
        return QuoteDisplay(
            text=preferred,
            language=preference,
            alternate_text=fallback,
            alternate_language=alternate_language if fallback is not None else None,
        )
    if fallback is not None:
        fallback_language: DisplayLanguage = "en" if preference == "ja" else "ja"
        return QuoteDisplay(
            text=fallback,
            language=fallback_language,
            alternate_text=None,
            alternate_language=None,
        )
    raise ValueError("quote has no displayable text")
