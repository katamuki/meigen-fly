"""Presentation helpers shared by public quote surfaces."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

DisplayLanguage = Literal["ja", "en"]
DatePrecision = Literal["day", "month", "year", "unknown"]
LifeEra = Literal["bc", "ad"]
_LIFE_DATE_PATTERN = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")


@dataclass(frozen=True)
class QuoteDisplay:
    """Resolved primary and optional secondary text for one quote."""

    text: str
    language: DisplayLanguage
    alternate_text: str | None
    alternate_language: DisplayLanguage | None


def format_life_date(
    date_text: str | None,
    precision: DatePrecision,
    era: LifeEra,
) -> str | None:
    """Format one normalized historical date at its recorded precision."""
    if precision == "unknown":
        return None
    if date_text is None:
        raise ValueError("known life date must have a value")

    match = _LIFE_DATE_PATTERN.fullmatch(date_text)
    if match is None:
        raise ValueError(f"invalid life date: {date_text!r}")
    year, month, day = (int(part) for part in match.groups())
    prefix = "紀元前" if era == "bc" else ""
    if precision == "year":
        return f"{prefix}{year}年"
    if precision == "month":
        return f"{prefix}{year}年{month}月"
    return f"{prefix}{year}年{month}月{day}日"


def format_lifespan(
    birth_date: str | None,
    birth_precision: DatePrecision,
    birth_era: LifeEra,
    death_date: str | None,
    death_precision: DatePrecision,
    death_era: LifeEra,
) -> str | None:
    """Format an author's known lifespan, or return ``None`` when unknown."""
    birth = format_life_date(birth_date, birth_precision, birth_era)
    death = format_life_date(death_date, death_precision, death_era)
    if birth is None and death is None:
        return None
    if birth is None:
        return f"不明 - {death}"
    if death is None:
        return f"{birth} -"
    return f"{birth} - {death}"


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
