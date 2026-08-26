import pytest

from app.presentation import (
    QuoteDisplay,
    format_life_date,
    format_lifespan,
    resolve_quote_display,
)


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        (
            {
                "text": "日本語",
                "text_en": "English",
                "display_language_preference": "ja",
            },
            QuoteDisplay("日本語", "ja", "English", "en"),
        ),
        (
            {
                "text": "日本語",
                "text_en": "English",
                "display_language_preference": "en",
            },
            QuoteDisplay("English", "en", "日本語", "ja"),
        ),
        (
            {
                "text": "日本語",
                "text_en": None,
                "display_language_preference": "en",
            },
            QuoteDisplay("日本語", "ja", None, None),
        ),
        (
            {
                "text": "   ",
                "text_en": "English",
                "display_language_preference": "ja",
            },
            QuoteDisplay("English", "en", None, None),
        ),
    ],
)
def test_resolve_quote_display_uses_preference_then_fallback(
    quote: dict, expected: QuoteDisplay
) -> None:
    assert resolve_quote_display(quote) == expected


def test_resolve_quote_display_rejects_invalid_records() -> None:
    with pytest.raises(ValueError, match="invalid display language"):
        resolve_quote_display(
            {
                "text": "日本語",
                "text_en": None,
                "display_language_preference": "fr",
            }
        )

    with pytest.raises(ValueError, match="no displayable text"):
        resolve_quote_display(
            {
                "text": "",
                "text_en": None,
                "display_language_preference": "ja",
            }
        )


@pytest.mark.parametrize(
    ("date_text", "precision", "era", "expected"),
    [
        ("1867-02-09", "day", "ad", "1867年2月9日"),
        ("1867-02-01", "month", "ad", "1867年2月"),
        ("1867-01-01", "year", "ad", "1867年"),
        ("0480-01-01", "year", "bc", "紀元前480年"),
        (None, "unknown", "ad", None),
    ],
)
def test_format_life_date_respects_precision_and_era(
    date_text: str | None,
    precision: str,
    era: str,
    expected: str | None,
) -> None:
    assert format_life_date(date_text, precision, era) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            ("1867-02-09", "day", "ad", "1916-01-01", "year", "ad"),
            "1867年2月9日 - 1916年",
        ),
        (
            ("1961-07-08", "day", "ad", None, "unknown", "ad"),
            "1961年7月8日 -",
        ),
        (
            (None, "unknown", "ad", "1916-01-01", "year", "ad"),
            "不明 - 1916年",
        ),
        ((None, "unknown", "ad", None, "unknown", "ad"), None),
    ],
)
def test_format_lifespan_handles_partial_and_unknown_dates(
    values: tuple,
    expected: str | None,
) -> None:
    assert format_lifespan(*values) == expected
