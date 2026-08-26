from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import create_db_engine, get_connection, metadata
from app.instants import format_instant
from app.main import app
from app.schema import (
    author_country,
    author_professions,
    authors,
    categories,
    characters,
    countries,
    professions,
    quote_categories,
    quotes,
    source_type_assignments,
    source_types,
    sources,
)
from app.services.quotes import SQLITE_MAX_INTEGER


@pytest.fixture
def public_client(tmp_path: Path) -> Iterator[TestClient]:
    test_engine = create_db_engine(f"sqlite:///{tmp_path / 'public.db'}")
    metadata.create_all(test_engine)
    first = format_instant(datetime(2026, 1, 1, tzinfo=UTC))
    second = format_instant(datetime(2026, 1, 2, tzinfo=UTC))

    with test_engine.begin() as connection:
        connection.execute(
            authors.insert(),
            [
                {
                    "id": 1,
                    "name": "著者一",
                    "slug": "author-one",
                    "name_reading": "ちょしゃいち",
                    "birth_date": "1867-02-09",
                    "birth_era": "ad",
                    "birth_precision": "day",
                    "death_date": "1916-01-01",
                    "death_era": "ad",
                    "death_precision": "year",
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 2,
                    "name": "著者二",
                    "slug": "author-two",
                    "name_reading": None,
                    "birth_date": None,
                    "birth_era": "ad",
                    "birth_precision": "unknown",
                    "death_date": None,
                    "death_era": "ad",
                    "death_precision": "unknown",
                    "created_at": first,
                    "updated_at": first,
                },
            ],
        )
        connection.execute(
            professions.insert(),
            [
                {
                    "id": 20,
                    "name": "哲学者",
                    "slug": "philosopher",
                    "display_order": 1,
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 21,
                    "name": "作家",
                    "slug": "writer",
                    "display_order": 2,
                    "created_at": first,
                    "updated_at": first,
                },
            ],
        )
        connection.execute(
            author_professions.insert(),
            {
                "author_id": 1,
                "profession_id": 20,
                "display_order": 1,
                "created_at": first,
            },
        )
        connection.execute(
            countries.insert(),
            [
                {
                    "id": 30,
                    "name": "日本",
                    "slug": "japan",
                    "code": "JP",
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 31,
                    "name": "フランス",
                    "slug": "france",
                    "code": "FR",
                    "created_at": first,
                    "updated_at": first,
                },
            ],
        )
        connection.execute(
            author_country.insert(),
            {
                "author_id": 1,
                "country_id": 30,
                "is_birth_country": 1,
                "created_at": first,
            },
        )
        connection.execute(
            source_types.insert(),
            [
                {
                    "id": 40,
                    "name": "書籍",
                    "slug": "book",
                    "display_order": 1,
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 41,
                    "name": "映画",
                    "slug": "movie",
                    "display_order": 2,
                    "created_at": first,
                    "updated_at": first,
                },
            ],
        )
        connection.execute(
            sources.insert(),
            [
                {
                    "id": 50,
                    "title": "第一の本",
                    "slug": "first-book",
                    "author_id": 1,
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 51,
                    "title": "空の映画",
                    "slug": "empty-movie",
                    "author_id": None,
                    "created_at": first,
                    "updated_at": first,
                },
            ],
        )
        connection.execute(
            source_type_assignments.insert(),
            [
                {"source_id": 50, "type_id": 40, "created_at": first},
                {"source_id": 51, "type_id": 41, "created_at": first},
            ],
        )
        connection.execute(
            characters.insert(),
            [
                {
                    "id": 60,
                    "name": "主人公",
                    "slug": "hero",
                    "source_id": 50,
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 61,
                    "name": "登場なし",
                    "slug": "unused-character",
                    "source_id": None,
                    "created_at": first,
                    "updated_at": first,
                },
            ],
        )
        connection.execute(
            categories.insert(),
            [
                {
                    "id": 10,
                    "name": "人生",
                    "slug": "life",
                    "sort_order": 1,
                    "level": 1,
                    "parent_id": None,
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 11,
                    "name": "希望",
                    "slug": "hope",
                    "sort_order": 1,
                    "level": 2,
                    "parent_id": 10,
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 12,
                    "name": "努力",
                    "slug": "effort",
                    "sort_order": 2,
                    "level": 2,
                    "parent_id": 10,
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 13,
                    "name": "未分類",
                    "slug": "unused-category",
                    "sort_order": 2,
                    "level": 1,
                    "parent_id": None,
                    "created_at": first,
                    "updated_at": first,
                },
            ],
        )
        connection.execute(
            quotes.insert(),
            [
                {
                    "id": 1,
                    "slug": "quote-one",
                    "text": "日本語一",
                    "text_en": "English one",
                    "display_language_preference": "en",
                    "author_id": 1,
                    "source_id": 50,
                    "character_id": 60,
                    "enable": 1,
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 2,
                    "slug": None,
                    "text": "公開二",
                    "text_en": None,
                    "display_language_preference": "ja",
                    "author_id": 2,
                    "source_id": None,
                    "character_id": None,
                    "enable": 1,
                    "created_at": second,
                    "updated_at": second,
                },
                {
                    "id": 3,
                    "slug": "private-quote",
                    "text": "非公開三",
                    "text_en": None,
                    "display_language_preference": "ja",
                    "author_id": 1,
                    "source_id": 50,
                    "character_id": 60,
                    "enable": 0,
                    "created_at": first,
                    "updated_at": first,
                },
                *[
                    {
                        "id": quote_id,
                        "slug": None,
                        "text": f"追加{quote_id}",
                        "text_en": None,
                        "display_language_preference": "ja",
                        "author_id": 2,
                        "source_id": None,
                        "character_id": None,
                        "enable": 1,
                        "created_at": first,
                        "updated_at": first,
                    }
                    for quote_id in range(10, 30)
                ],
            ],
        )
        connection.execute(
            quote_categories.insert(),
            [
                {"quote_id": 1, "category_id": 11},
                {"quote_id": 1, "category_id": 12},
                {"quote_id": 2, "category_id": 12},
                {"quote_id": 3, "category_id": 11},
            ],
        )

    def override_connection() -> Iterator:
        with test_engine.connect() as connection:
            yield connection

    app.dependency_overrides[get_connection] = override_connection
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client
    app.dependency_overrides.clear()
    test_engine.dispose()


def test_quote_url_resolution_and_public_visibility(public_client: TestClient) -> None:
    slug = public_client.get("/quotes/quote-one")
    qid_with_slug = public_client.get("/quotes/q1", follow_redirects=False)
    qid_without_slug = public_client.get("/quotes/q2")

    assert slug.status_code == 200
    assert 'data-quote-id="1"' in slug.text
    assert "English one" in slug.text
    assert qid_with_slug.status_code == 301
    assert qid_with_slug.headers["location"] == "/quotes/quote-one"
    assert qid_without_slug.status_code == 200
    assert 'data-quote-id="2"' in qid_without_slug.text

    for identifier in (
        "q0",
        "q01",
        "Q2",
        "q2x",
        "q999",
        f"q{SQLITE_MAX_INTEGER}",
        f"q{SQLITE_MAX_INTEGER + 1}",
        "private-quote",
        "q3",
    ):
        response = public_client.get(f"/quotes/{identifier}")
        assert response.status_code == 404
        assert response.headers["cache-control"] == "private, no-store"


def test_quote_list_filters_use_public_distinct_semantics(
    public_client: TestClient,
) -> None:
    by_author = public_client.get("/quotes?author_id=1")
    by_profession = public_client.get("/quotes?profession_id=20")
    by_parent_category = public_client.get("/quotes?category_id=10")
    by_child_category = public_client.get("/quotes?category_id=11")

    for response in (by_author, by_profession, by_child_category):
        assert response.status_code == 200
        assert response.text.count('data-quote-id="1"') == 1
        assert 'data-quote-id="2"' not in response.text
        assert "非公開三" not in response.text

    assert by_parent_category.text.count('data-quote-id="1"') == 1
    assert by_parent_category.text.count('data-quote-id="2"') == 1
    assert "全 2件" in by_parent_category.text


def test_quote_list_pagination_and_latest_order(public_client: TestClient) -> None:
    first_page = public_client.get("/quotes")
    second_page = public_client.get("/quotes/page/2")
    latest = public_client.get("/quotes/latest")

    assert first_page.status_code == 200
    assert "/quotes/page/2" in first_page.text
    assert second_page.status_code == 200
    assert second_page.text.count('data-quote-id="') == 2
    assert latest.text.index('data-quote-id="2"') < latest.text.index(
        'data-quote-id="29"'
    )
    assert 'datetime="2026-01-02T00:00:00+00:00"' in latest.text
    assert public_client.get("/quotes/page/3").status_code == 404
    assert public_client.get("/quotes/page/1").status_code == 404
    assert public_client.get("/quotes/page/02").status_code == 200
    assert public_client.get("/quotes/page/not-a-page").status_code == 404


def test_sqlite_integer_boundaries_do_not_raise_server_errors(
    public_client: TestClient,
) -> None:
    for page in (SQLITE_MAX_INTEGER, SQLITE_MAX_INTEGER + 1):
        response = public_client.get(f"/quotes/page/{page}")
        assert response.status_code == 404
        assert response.headers["cache-control"] == "private, no-store"

    for filter_name in ("author_id", "category_id", "profession_id"):
        boundary = public_client.get(f"/quotes?{filter_name}={SQLITE_MAX_INTEGER}")
        overflow = public_client.get(f"/quotes?{filter_name}={SQLITE_MAX_INTEGER + 1}")
        assert boundary.status_code == 200
        assert overflow.status_code == 422
        assert overflow.headers["cache-control"] == "private, no-store"


def test_home_and_quote_pages_use_public_cache_headers(
    public_client: TestClient,
) -> None:
    home = public_client.get("/")
    listing = public_client.get("/quotes")
    detail = public_client.get("/quotes/q2")

    assert home.status_code == 200
    assert "注目名言はランキング連動の準備中です" in home.text
    assert home.headers["cache-control"] == "public, s-maxage=300, max-age=60"
    for response in (listing, detail):
        assert response.headers["cache-control"] == "public, s-maxage=600, max-age=60"


def test_hashed_design_assets_and_external_theme_script_are_served(
    public_client: TestClient,
) -> None:
    response = public_client.get("/")
    assert (
        '<script src="http://localhost:8000/static/theme.caadaed0.js">' in response.text
    )
    assert "<script>" not in response.text

    for path in (
        "/static/theme.caadaed0.js",
        "/static/tokens.74bc89e2.css",
        "/static/components.fae1678a.css",
    ):
        asset = public_client.get(path)
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"

    mobile_css = public_client.get("/static/components.fae1678a.css").text
    assert ".mg-header__spacer { display: none; }" in mobile_css
    assert ".mg-header .mg-search > svg { flex: 0 0 15px; }" in mobile_css
    assert ".mg-header .mg-search__input { min-width: 0; }" in mobile_css


def test_authors_work_with_empty_ranking_snapshot_and_public_counts(
    public_client: TestClient,
) -> None:
    listing = public_client.get("/authors")
    detail = public_client.get("/authors/author-one")

    assert listing.status_code == 200
    assert 'data-entity-id="1" data-quote-count="1"' in listing.text
    assert 'data-entity-id="2" data-quote-count="21"' in listing.text
    assert listing.text.index('data-entity-id="2"') < listing.text.index(
        'data-entity-id="1"'
    )
    assert detail.status_code == 200
    assert (
        '<span class="mg-chip" data-author-lifespan>1867年2月9日 - 1916年</span>'
        in detail.text
    )
    assert (
        'data-entity-type="author" data-entity-id="1" data-quote-count="1"'
        in detail.text
    )
    assert "非公開三" not in detail.text
    assert "data-author-lifespan" not in public_client.get("/authors/author-two").text
    assert public_client.get("/authors/not-found").status_code == 404


def test_category_tree_counts_distinct_public_quotes_and_keeps_empty_masters(
    public_client: TestClient,
) -> None:
    listing = public_client.get("/categories")

    assert listing.status_code == 200
    # Quote 1 belongs to both children, but the parent counts it only once.
    assert 'data-category-id="10" data-quote-count="2"' in listing.text
    assert 'data-category-id="11" data-quote-count="1"' in listing.text
    assert 'data-category-id="12" data-quote-count="2"' in listing.text
    assert 'data-category-id="13" data-quote-count="0"' in listing.text
    assert public_client.get("/categories/life").status_code == 200
    assert (
        'data-entity-type="category" data-entity-id="10" data-quote-count="2"'
        in public_client.get("/categories/life").text
    )
    assert public_client.get("/categories/not-found").status_code == 404


def test_sources_support_type_filter_public_counts_and_slug_404(
    public_client: TestClient,
) -> None:
    listing = public_client.get("/sources")
    books = public_client.get("/sources?type=book")
    movies = public_client.get("/sources?type=movie")
    detail = public_client.get("/sources/first-book")

    assert 'data-entity-id="50" data-quote-count="1"' in listing.text
    assert 'data-entity-id="51" data-quote-count="0"' in listing.text
    assert "第一の本" in books.text
    assert "空の映画" not in books.text
    assert "空の映画" in movies.text
    assert detail.status_code == 200
    assert (
        'data-entity-type="source" data-entity-id="50" data-quote-count="1"'
        in detail.text
    )
    assert "非公開三" not in detail.text
    assert public_client.get("/sources/not-found").status_code == 404


def test_character_profession_and_country_pages_keep_zero_counts_and_404(
    public_client: TestClient,
) -> None:
    characters_page = public_client.get("/characters")
    professions_page = public_client.get("/professions")
    authors_page = public_client.get("/authors")

    assert 'data-entity-id="60" data-quote-count="1"' in characters_page.text
    assert 'data-entity-id="61" data-quote-count="0"' in characters_page.text
    assert 'data-entity-id="20" data-quote-count="1"' in professions_page.text
    assert 'data-entity-id="21" data-quote-count="0"' in professions_page.text
    assert 'data-country-id="30">日本 1' in authors_page.text
    assert 'data-country-id="31">フランス 0' in authors_page.text

    expected_counts = {
        "/characters/hero": 'data-entity-type="character" data-entity-id="60" data-quote-count="1"',
        "/professions/philosopher": 'data-entity-type="profession" data-entity-id="20" data-quote-count="1"',
        "/professions/philosopher/quotes": 'data-entity-type="profession" data-entity-id="20" data-quote-count="1"',
        "/authors/places/japan": 'data-entity-type="country" data-entity-id="30" data-quote-count="1"',
    }
    for path, expected in expected_counts.items():
        response = public_client.get(path)
        assert response.status_code == 200
        assert expected in response.text
        assert "非公開三" not in response.text
    for path in (
        "/characters/not-found",
        "/professions/not-found",
        "/authors/places/not-found",
    ):
        assert public_client.get(path).status_code == 404
