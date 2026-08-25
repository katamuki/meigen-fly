from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import create_db_engine, get_connection, metadata
from app.instants import format_instant
from app.main import app
from app.schema import (
    author_professions,
    authors,
    categories,
    professions,
    quote_categories,
    quotes,
)


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
                    "created_at": first,
                    "updated_at": first,
                },
                {
                    "id": 2,
                    "name": "著者二",
                    "slug": "author-two",
                    "created_at": first,
                    "updated_at": first,
                },
            ],
        )
        connection.execute(
            professions.insert(),
            {
                "id": 20,
                "name": "哲学者",
                "slug": "philosopher",
                "display_order": 1,
                "created_at": first,
                "updated_at": first,
            },
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

    for identifier in ("q0", "q01", "Q2", "q2x", "q999", "private-quote", "q3"):
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
        "/static/components.76732ec5.css",
    ):
        asset = public_client.get(path)
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
