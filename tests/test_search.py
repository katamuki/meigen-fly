import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import create_db_engine, get_connection, metadata
from app.instants import format_instant
from app.main import app
from app.schema import author_professions, authors, professions, quotes, sources
from app.services.search import (
    MAX_TERM_LENGTH,
    QUOTE_RESULT_LIMIT,
    highlight,
    normalize_term,
    search_rate_limiter,
)

SEARCH_HEADERS = {"CF-Connecting-IP": "203.0.113.20"}

# Each quote is written so that one search term reaches it and no other.
QUOTE_ROWS = [
    {
        "id": 1,
        "slug": "moon-quote",
        "text": "本文に月が出ています",
        "text_en": "The moon is beautiful",
        "context_note": "文脈の注釈です",
        "author_id": 1,
        "source_id": 20,
    },
    {"id": 2, "slug": "percent-quote", "text": "達成率100%の努力"},
    {"id": 3, "slug": "underscore-quote", "text": "snake_case の話"},
    {"id": 4, "slug": "backslash-quote", "text": "円\\記号の話"},
    {"id": 5, "slug": "slash-quote", "text": "1/2の確率"},
    {"id": 6, "slug": "love-quote", "text": "愛だけが残る"},
    {
        "id": 7,
        "slug": "english-quote",
        "text": "日本語だけの本文",
        "text_en": "an unusual english line",
    },
    {
        "id": 8,
        "slug": "script-quote",
        "text": "<script>alert(1)</script> を含む本文",
    },
    {
        "id": 9,
        "slug": "hidden-quote",
        "text": "非公開の月です",
        "author_id": 1,
        "source_id": 20,
        "enable": 0,
    },
]


@pytest.fixture
def search_client(tmp_path: Path) -> Iterator[TestClient]:
    search_rate_limiter.reset()
    test_engine = create_db_engine(f"sqlite:///{tmp_path / 'search.db'}")
    metadata.create_all(test_engine)
    now = format_instant(datetime(2026, 1, 1, tzinfo=UTC))

    with test_engine.begin() as connection:
        connection.execute(
            authors.insert(),
            [
                {
                    "id": 1,
                    "name": "夏目漱石",
                    "slug": "natsume-soseki",
                    "name_kana": "なつめそうせき",
                    "name_foreign": "Soseki Natsume",
                    "name_reading": "なつめそうせき",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": 2,
                    "name": "著者二",
                    "slug": "author-two",
                    "name_kana": None,
                    "name_foreign": None,
                    "name_reading": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        connection.execute(
            professions.insert(),
            {
                "id": 10,
                "name": "小説家",
                "slug": "novelist",
                "display_order": 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        connection.execute(
            author_professions.insert(),
            {
                "author_id": 1,
                "profession_id": 10,
                "display_order": 1,
                "created_at": now,
            },
        )
        connection.execute(
            sources.insert(),
            {
                "id": 20,
                "title": "星の王子さま",
                "slug": "little-prince",
                "author_id": 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        quote_defaults = {
            "text_en": None,
            "context_note": None,
            "author_id": 2,
            "source_id": None,
            "enable": 1,
            "display_language_preference": "ja",
            "legacy_vote_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        connection.execute(
            quotes.insert(), [quote_defaults | row for row in QUOTE_ROWS]
        )

    def override_connection() -> Iterator:
        with test_engine.begin() as connection:
            yield connection

    app.dependency_overrides[get_connection] = override_connection
    app.state.search_test_engine = test_engine
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client
    app.dependency_overrides.clear()
    del app.state.search_test_engine
    search_rate_limiter.reset()
    test_engine.dispose()


def quote_ids(body: str) -> list[str]:
    return [part.split('"', 1)[0] for part in body.split('data-quote-id="')[1:]]


def test_normalize_term_collapses_whitespace_and_bounds_length() -> None:
    assert normalize_term("  月　が   出る ") == "月 が 出る"
    assert normalize_term("\t月\n出\r") == "月 出"
    assert normalize_term(None) == ""
    assert normalize_term("   ") == ""
    assert normalize_term("あ" * 120) == "あ" * MAX_TERM_LENGTH
    assert normalize_term(f"{'あ' * 99} いいえ") == "あ" * 99


def test_blank_query_shows_the_initial_prompt_without_searching(
    search_client: TestClient,
) -> None:
    for path in ("/search", "/search?q=", "/search?q=%20%20"):
        response = search_client.get(path)
        assert response.status_code == 200
        assert "キーワードを入力すると" in response.text
        assert "検索対象" not in response.text
        assert "data-quote-id" not in response.text


def test_like_wildcards_and_escape_characters_stay_literal(
    search_client: TestClient,
) -> None:
    # "/" is SQLAlchemy's autoescape escape character; quote 8 holds one in
    # "</script>", so both literal matches are expected there.
    literal_terms = {
        "100%": ["2"],
        "%": ["2"],
        "_": ["3"],
        "\\": ["4"],
        "/": ["5", "8"],
        "%の": ["2"],
    }
    for term, expected in literal_terms.items():
        response = search_client.get("/search", params={"q": term})
        assert response.status_code == 200
        assert quote_ids(response.text) == expected, term


def test_single_japanese_character_and_normalized_term_match(
    search_client: TestClient,
) -> None:
    single = search_client.get("/search", params={"q": "愛"})
    padded = search_client.get("/search", params={"q": "  愛  "})

    assert quote_ids(single.text) == ["6"]
    assert quote_ids(padded.text) == ["6"]


def test_every_searched_column_matches_and_hidden_quotes_stay_out(
    search_client: TestClient,
) -> None:
    by_column = {
        "月": ["1"],  # quotes.text, and the disabled quote 9 must not appear
        "beautiful": ["1"],  # quotes.text_en
        "注釈": ["1"],  # quotes.context_note
        "夏目": ["1"],  # authors.name
        "王子": ["1"],  # sources.title
        "unusual": ["7"],
    }
    for term, expected in by_column.items():
        response = search_client.get("/search", params={"q": term})
        assert quote_ids(response.text) == expected, term
        assert "非公開の月" not in response.text


def test_author_columns_match_and_carry_public_quote_counts(
    search_client: TestClient,
) -> None:
    for term in ("夏目", "なつめ", "Soseki"):
        response = search_client.get("/search", params={"q": term})
        assert response.status_code == 200
        assert "/authors/natsume-soseki" in response.text
        assert "小説家 · 名言 1件" in response.text


def test_scope_chips_limit_the_rendered_sections(search_client: TestClient) -> None:
    everything = search_client.get("/search", params={"q": "夏目"})
    only_quotes = search_client.get("/search", params={"q": "夏目", "scope": "quotes"})
    only_authors = search_client.get(
        "/search", params={"q": "夏目", "scope": "authors"}
    )
    unknown_scope = search_client.get(
        "/search", params={"q": "夏目", "scope": "categories"}
    )

    assert "結果 · 名言" in everything.text and "結果 · 著者" in everything.text
    assert "結果 · 名言" in only_quotes.text and "結果 · 著者" not in only_quotes.text
    assert "結果 · 名言" not in only_authors.text and "結果 · 著者" in only_authors.text
    assert unknown_scope.text == everything.text
    # The counts describe the whole result set, not the selected scope.
    for response in (everything, only_quotes, only_authors):
        assert "すべて 2" in response.text
        assert "名言 1" in response.text
        assert "著者 1" in response.text


def test_quote_results_are_capped_and_ordered_by_id(
    search_client: TestClient,
) -> None:
    now = format_instant(datetime(2026, 1, 1, tzinfo=UTC))
    engine = search_client.app.state.search_test_engine
    with engine.begin() as connection:
        connection.execute(
            quotes.insert(),
            [
                {
                    "id": 100 + offset,
                    "slug": f"bulk-{offset}",
                    "text": f"上限確認の名言{offset}",
                    "display_language_preference": "ja",
                    "author_id": 2,
                    "enable": 1,
                    "legacy_vote_count": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                for offset in range(QUOTE_RESULT_LIMIT + 5)
            ],
        )

    response = search_client.get("/search", params={"q": "上限確認"})
    ids = quote_ids(response.text)

    assert len(ids) == QUOTE_RESULT_LIMIT
    assert ids == [str(100 + offset) for offset in range(QUOTE_RESULT_LIMIT)]
    assert f"名言 {QUOTE_RESULT_LIMIT + 5}" in response.text


def test_fragment_matches_the_page_and_neither_response_is_cached(
    search_client: TestClient,
) -> None:
    page = search_client.get("/search", params={"q": "月"})
    fragment = search_client.get(
        "/search/partial", params={"q": "月"}, headers={"HX-Request": "true"}
    )

    assert page.status_code == fragment.status_code == 200
    assert "<!doctype html>" in page.text.lower()
    assert "<!doctype" not in fragment.text.lower()
    assert "<html" not in fragment.text.lower()
    assert fragment.text.strip() in page.text
    assert quote_ids(page.text) == quote_ids(fragment.text) == ["1"]
    for response in (page, fragment):
        assert response.headers["vary"] == "HX-Request"
        assert response.headers["cache-control"] == "private, no-store"


def test_search_page_declares_noindex_and_the_htmx_configuration(
    search_client: TestClient,
) -> None:
    page = search_client.get("/search")
    fragment = search_client.get("/search/partial", headers={"HX-Request": "true"})

    assert '<meta name="robots" content="noindex">' in page.text
    assert (
        '<meta name="htmx-config" '
        'content=\'{"allowEval":false,"allowScriptTags":false,'
        '"selfRequestsOnly":true}\'>' in page.text
    )
    assert "robots" not in fragment.text
    for path in re.findall(r'src="(/static/[^"]+)"', page.text):
        assert search_client.get(path).status_code == 200
    assert any(
        "/static/htmx." in src for src in re.findall(r'src="([^"]+)"', page.text)
    )


def test_search_output_escapes_markup_in_quotes_and_in_the_term(
    search_client: TestClient,
) -> None:
    by_text = search_client.get("/search", params={"q": "script"})
    by_term = search_client.get("/search", params={"q": "<script>alert(1)</script>"})

    assert quote_ids(by_text.text) == ["8"]
    assert "<script>alert(1)</script>" not in by_text.text
    assert "&lt;<mark>script</mark>&gt;alert(1)" in by_text.text
    assert "<script>alert(1)</script>" not in by_term.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in by_term.text


def test_highlight_escapes_before_marking_matches() -> None:
    assert highlight("<b>愛</b>", "愛") == "&lt;b&gt;<mark>愛</mark>&lt;/b&gt;"
    assert highlight("Love and LOVE", "love") == (
        "<mark>Love</mark> and <mark>LOVE</mark>"
    )
    assert highlight("<b>", "") == "&lt;b&gt;"
    assert highlight(None, "愛") == ""
    assert highlight("<mark>", "<mark>") == "<mark>&lt;mark&gt;</mark>"


def test_search_rate_limit_returns_retry_after(search_client: TestClient) -> None:
    for _ in range(search_rate_limiter.max_requests):
        allowed = search_client.get(
            "/search/partial",
            params={"q": "月"},
            headers={**SEARCH_HEADERS, "HX-Request": "true"},
        )
        assert allowed.status_code == 200

    limited = search_client.get(
        "/search/partial",
        params={"q": "月"},
        headers={**SEARCH_HEADERS, "HX-Request": "true"},
    )
    page = search_client.get("/search", params={"q": "月"}, headers=SEARCH_HEADERS)

    for response in (limited, page):
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) >= 1
        assert response.headers["vary"] == "HX-Request"
        assert response.headers["cache-control"] == "private, no-store"
