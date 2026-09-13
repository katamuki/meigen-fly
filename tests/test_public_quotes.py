import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db import create_db_engine, get_connection, metadata
from app.instants import format_instant
from app.main import app
from app.schema import (
    author_country,
    author_professions,
    author_rankings,
    authors,
    categories,
    category_rankings,
    characters,
    countries,
    professions,
    quote_categories,
    quote_likes,
    quote_ranking_scores,
    quotes,
    source_type_assignments,
    source_types,
    sources,
)
from app.services.likes import like_rate_limiter
from app.services.quotes import SQLITE_MAX_INTEGER
from app.services.rate_limit import RateLimiter

LIKE_HEADERS = {
    "Origin": "http://localhost:8000",
    "Sec-Fetch-Site": "same-origin",
    "CF-Connecting-IP": "203.0.113.10",
}


@pytest.fixture
def public_client(tmp_path: Path) -> Iterator[TestClient]:
    like_rate_limiter.reset()
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
                    "legacy_vote_count": 4,
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
                    "legacy_vote_count": 3,
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
                    "legacy_vote_count": 0,
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
                        "legacy_vote_count": 0,
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
        with test_engine.begin() as connection:
            yield connection

    app.dependency_overrides[get_connection] = override_connection
    app.state.public_test_engine = test_engine
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client
    app.dependency_overrides.clear()
    del app.state.public_test_engine
    like_rate_limiter.reset()
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
    # ADR 008 normalizes page 1 onto the base path instead of serving it.
    page_one = public_client.get("/quotes/page/1", follow_redirects=False)
    assert page_one.status_code == 301
    assert page_one.headers["location"] == "/quotes"
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
    assert "新着名言から" in home.text
    assert 'href="/quotes/q2"' in home.text
    assert home.text.count("?size=pill") == 1
    assert detail.text.count("?size=solid") == 1
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
    assert (
        '<script src="http://localhost:8000/static/likes.313469f4.js" defer>'
        in response.text
    )
    assert "<script>" not in response.text

    for path in (
        "/static/theme.caadaed0.js",
        "/static/likes.313469f4.js",
        "/static/tokens.74bc89e2.css",
        "/static/components.85b1abc0.css",
    ):
        asset = public_client.get(path)
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"

    like_script = public_client.get("/static/likes.313469f4.js").text
    assert "window.localStorage" in like_script
    assert "window.crypto.randomUUID" in like_script
    assert 'method: "POST"' in like_script

    mobile_css = public_client.get("/static/components.85b1abc0.css").text
    assert ".mg-header__spacer { display: none; }" in mobile_css
    assert ".mg-header .mg-search > svg { flex: 0 0 15px; }" in mobile_css
    assert ".mg-header .mg-search__input { min-width: 0; }" in mobile_css


@pytest.mark.parametrize(
    ("path", "title"),
    [
        ("/about", "このサイトについて"),
        ("/privacy", "プライバシーポリシー"),
        ("/terms", "利用規約"),
    ],
)
def test_static_pages_render_with_self_canonical_and_weekly_cache(
    public_client: TestClient, path: str, title: str
) -> None:
    response = public_client.get(path)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, s-maxage=604800, max-age=86400"
    assert f'<link rel="canonical" href="http://localhost:8000{path}">' in response.text
    assert f'<h1 class="mg-h1">{title}</h1>' in response.text
    assert f"<title>{title}｜名言集.com</title>" in response.text


def test_policy_pages_show_their_last_update(public_client: TestClient) -> None:
    privacy = public_client.get("/privacy").text
    assert "最終更新日: <time" in privacy
    # Section 8 sends readers to the contact at the end of the page.
    assert 'href="https://docs.google.com/forms/d/e/' in privacy
    assert "最終更新日: <time" in public_client.get("/terms").text
    assert "最終更新日" not in public_client.get("/about").text


def test_every_footer_link_resolves(public_client: TestClient) -> None:
    # The footer pointed at /about, /privacy and /terms long before they existed.
    home = public_client.get("/").text
    footer = home.split('<footer class="mg-footer">', 1)[1].split("</footer>", 1)[0]
    links = re.findall(r'href="([^"]+)"', footer)

    assert {"/about", "/privacy", "/terms"} <= set(links)
    for link in links:
        assert public_client.get(link, follow_redirects=False).status_code == 200


def test_random_returns_at_most_twenty_public_quotes_without_cache(
    public_client: TestClient,
) -> None:
    response = public_client.get("/random")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.text.count('data-quote-id="') == 20
    assert "非公開三" not in response.text


def test_like_uuid_validation_and_request_guards(public_client: TestClient) -> None:
    assert public_client.get("/api/likes/1").status_code == 405

    for invalid_uuid in (
        "not-a-uuid",
        "550E8400-E29B-41D4-A716-446655440000",
        "{550e8400-e29b-41d4-a716-446655440000}",
        "550e8400-e29b-41d4-a716-446655440000 ",
    ):
        response = public_client.post(
            "/api/likes/1",
            data={"client_uuid": invalid_uuid},
            headers=LIKE_HEADERS,
        )
        assert response.status_code == 422

    assert (
        public_client.post(
            "/api/likes/1",
            content="client_uuid=550e8400-e29b-41d4-a716-446655440000",
            headers={
                **LIKE_HEADERS,
                "Origin": "https://attacker.invalid",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        ).status_code
        == 403
    )
    oversized = public_client.post(
        "/api/likes/1",
        content="client_uuid=" + ("a" * 300),
        headers={**LIKE_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert oversized.status_code == 413
    assert (
        public_client.post(
            "/api/likes/1",
            json={"client_uuid": "550e8400-e29b-41d4-a716-446655440000"},
            headers=LIKE_HEADERS,
        ).status_code
        == 415
    )
    assert (
        public_client.post(
            "/api/likes/1",
            data={"client_uuid": "550e8400-e29b-41d4-a716-446655440000"},
            headers={**LIKE_HEADERS, "Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 403
    )


def test_like_first_insert_is_idempotent_and_returns_combined_count(
    public_client: TestClient,
) -> None:
    client_uuid = "550e8400-e29b-41d4-a716-446655440000"

    first = public_client.post(
        "/api/likes/1", data={"client_uuid": client_uuid}, headers=LIKE_HEADERS
    )
    duplicate = public_client.post(
        "/api/likes/1", data={"client_uuid": client_uuid}, headers=LIKE_HEADERS
    )

    assert first.status_code == duplicate.status_code == 200
    assert first.headers["cache-control"] == "private, no-store"
    assert 'data-like-count="5"' in first.text
    assert 'data-like-count="5"' in duplicate.text
    with public_client.app.state.public_test_engine.connect() as connection:
        rows = connection.execute(
            quote_likes.select().where(quote_likes.c.quote_id == 1)
        ).all()
        assert len(rows) == 1


def test_like_insert_race_is_an_idempotent_success(public_client: TestClient) -> None:
    engine = public_client.app.state.public_test_engine
    original_override = app.dependency_overrides[get_connection]

    class RaceConnection:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.raced = False

        def execute(self, statement, *args, **kwargs):
            if (
                not self.raced
                and getattr(statement, "is_insert", False)
                and statement.table.name == "quote_likes"
            ):
                self.raced = True
                self.connection.execute(statement, *args, **kwargs)
                raise IntegrityError(
                    "INSERT",
                    {},
                    sqlite3.IntegrityError("UNIQUE constraint failed"),
                )
            return self.connection.execute(statement, *args, **kwargs)

    def race_override() -> Iterator:
        with engine.begin() as connection:
            yield RaceConnection(connection)

    app.dependency_overrides[get_connection] = race_override
    try:
        response = public_client.post(
            "/api/likes/1",
            data={"client_uuid": "00000000-0000-4000-8000-000000000123"},
            headers=LIKE_HEADERS,
        )
    finally:
        app.dependency_overrides[get_connection] = original_override

    assert response.status_code == 200
    assert 'data-like-count="5"' in response.text
    with engine.connect() as connection:
        rows = connection.execute(
            quote_likes.select().where(quote_likes.c.quote_id == 1)
        ).all()
        assert len(rows) == 1


def test_display_count_adds_legacy_votes_and_only_valid_likes(
    public_client: TestClient,
) -> None:
    first = format_instant(datetime(2026, 1, 1, tzinfo=UTC))
    with public_client.app.state.public_test_engine.begin() as connection:
        connection.execute(
            quote_likes.insert(),
            [
                {
                    "quote_id": 2,
                    "client_uuid": "00000000-0000-4000-8000-000000000001",
                    "created_at": first,
                    "is_valid": 1,
                },
                {
                    "quote_id": 2,
                    "client_uuid": "00000000-0000-4000-8000-000000000002",
                    "created_at": first,
                    "is_valid": 0,
                },
            ],
        )

    response = public_client.get("/quotes/q2")
    assert response.status_code == 200
    assert 'data-like-count="4"' in response.text


def test_like_rejects_private_and_missing_quotes(public_client: TestClient) -> None:
    for quote_id in (3, 999):
        response = public_client.post(
            f"/api/likes/{quote_id}",
            data={"client_uuid": f"00000000-0000-4000-8000-{quote_id:012d}"},
            headers=LIKE_HEADERS,
        )
        assert response.status_code == 404


def test_like_rate_limit_returns_retry_after(public_client: TestClient) -> None:
    for sequence in range(like_rate_limiter.max_requests):
        response = public_client.post(
            "/api/likes/1",
            data={"client_uuid": f"00000000-0000-4000-8000-{sequence:012d}"},
            headers=LIKE_HEADERS,
        )
        assert response.status_code == 200

    limited = public_client.post(
        "/api/likes/1",
        data={"client_uuid": "00000000-0000-4000-8000-999999999999"},
        headers=LIKE_HEADERS,
    )
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_rate_limiter_bounds_source_keys() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=10, max_sources=2)

    assert limiter.allow("192.0.2.1", now=0)[0]
    assert limiter.allow("192.0.2.2", now=0)[0]
    assert limiter.allow("192.0.2.3", now=20)[0]
    assert limiter.tracked_source_count == 2


def test_empty_ranking_snapshots_render_and_home_falls_back(
    public_client: TestClient,
) -> None:
    for path in ("/ranking", "/ranking/authors", "/ranking/categories"):
        response = public_client.get(path)
        assert response.status_code == 200
        assert "ランキングはまだ集計されていません" in response.text

    home = public_client.get("/")
    assert home.status_code == 200
    assert "新着名言から" in home.text
    assert 'href="/quotes/q2"' in home.text


def test_snapshot_rankings_use_score_then_stable_id_and_drive_home_feature(
    public_client: TestClient,
) -> None:
    refreshed_at = format_instant(datetime(2026, 1, 3, tzinfo=UTC))
    engine = public_client.app.state.public_test_engine
    with engine.begin() as connection:
        connection.execute(
            quote_ranking_scores.insert(),
            [
                {
                    "quote_id": 2,
                    "score_total": 5,
                    "likes_total": 3,
                    "likes_7d": 0,
                    "likes_1d": 0,
                    "refreshed_at": refreshed_at,
                },
                {
                    "quote_id": 1,
                    "score_total": 5,
                    "likes_total": 4,
                    "likes_7d": 0,
                    "likes_1d": 0,
                    "refreshed_at": refreshed_at,
                },
                {
                    "quote_id": 10,
                    "score_total": 9,
                    "likes_total": 0,
                    "likes_7d": 0,
                    "likes_1d": 0,
                    "refreshed_at": refreshed_at,
                },
            ],
        )
        connection.execute(
            author_rankings.insert(),
            [
                {
                    "author_id": 1,
                    "rank": 1,
                    "score": 2,
                    "total_score": 2,
                    "avg_score": 2,
                    "quote_count": 1,
                    "refreshed_at": refreshed_at,
                },
                {
                    "author_id": 2,
                    "rank": 2,
                    "score": 8,
                    "total_score": 8,
                    "avg_score": 8,
                    "quote_count": 21,
                    "refreshed_at": refreshed_at,
                },
            ],
        )
        connection.execute(
            category_rankings.insert(),
            [
                {
                    "category_id": 11,
                    "rank": 1,
                    "score": 7,
                    "total_score": 7,
                    "avg_score": 7,
                    "adjusted_score": 7,
                    "quote_count": 1,
                    "refreshed_at": refreshed_at,
                },
                {
                    "category_id": 10,
                    "rank": 2,
                    "score": 7,
                    "total_score": 7,
                    "avg_score": 7,
                    "adjusted_score": 7,
                    "quote_count": 2,
                    "refreshed_at": refreshed_at,
                },
                {
                    "category_id": 13,
                    "rank": 3,
                    "score": 9,
                    "total_score": 9,
                    "avg_score": 9,
                    "adjusted_score": 9,
                    "quote_count": 0,
                    "refreshed_at": refreshed_at,
                },
            ],
        )

    quote_page = public_client.get("/ranking")
    author_page = public_client.get("/ranking/authors")
    category_page = public_client.get("/ranking/categories")
    assert (
        quote_page.text.index('data-ranking-id="10"')
        < quote_page.text.index('data-ranking-id="1"')
        < quote_page.text.index('data-ranking-id="2"')
    )
    assert author_page.text.index('data-ranking-id="2"') < author_page.text.index(
        'data-ranking-id="1"'
    )
    assert (
        category_page.text.index('data-ranking-id="13"')
        < category_page.text.index('data-ranking-id="10"')
        < category_page.text.index('data-ranking-id="11"')
    )

    home = public_client.get("/")
    assert "ランキング注目名言" in home.text
    assert 'href="/quotes/q10"' in home.text


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
