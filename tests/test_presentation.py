import pytest

from app.presentation import QuoteDisplay, resolve_quote_display


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
