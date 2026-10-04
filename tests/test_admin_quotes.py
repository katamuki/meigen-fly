from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select

from app.admin import issue_csrf_token
from app.db import create_db_engine, get_connection, metadata
from app.main import app
from app.routers import admin_quotes
from app.routers.admin_quotes import QuoteForm
from app.schema import (
    authors,
    categories,
    characters,
    quote_categories,
    quote_likes,
    quotes,
    sources,
)
from app.services.cache_purge import CachePurgeResult, CachePurgeStatus

EMAIL = "admin@example.com"
INSTANT = "2026-01-01T00:00:00.000000Z"


@pytest.fixture
def admin_quote_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Engine]]:
    monkeypatch.setenv("ADMIN_DEV_EMAIL", EMAIL)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("PUBLIC_ORIGIN", "http://localhost:8000")
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'admin-quotes.db'}")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(authors),
            [
                {
                    "id": 1,
                    "name": "旧著者",
                    "slug": "old-author",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 2,
                    "name": "新著者",
                    "slug": "new-author",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )
        connection.execute(
            insert(sources),
            {
                "id": 1,
                "title": "出典",
                "slug": "source",
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(characters),
            {
                "id": 1,
                "name": "人物",
                "slug": "character",
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(categories),
            [
                {
                    "id": 1,
                    "name": "親",
                    "slug": "parent",
                    "level": 1,
                    "parent_id": None,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 2,
                    "name": "旧カテゴリ",
                    "slug": "old-category",
                    "level": 2,
                    "parent_id": 1,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 3,
                    "name": "新カテゴリ",
                    "slug": "new-category",
                    "level": 2,
                    "parent_id": 1,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )

    def override_connection():
        with engine.begin() as connection:
            yield connection

    app.dependency_overrides[get_connection] = override_connection
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def _quote_form(**overrides) -> dict:
    data = {
        "csrf_token": issue_csrf_token(EMAIL),
        "text": "作成した名言",
        "text_en": "Created quote",
        "author_id": "1",
        "source_id": "1",
        "character_id": "1",
        "weight": "7",
        "slug": "created-quote",
        "enable": "1",
        "context_note": "注記",
        "display_language_preference": "ja",
        "legacy_vote_count": "3",
        "category_ids": "2",
    }
    data.update(overrides)
    return data


def test_quote_create_commits_before_purge_and_logs(
    admin_quote_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, engine = admin_quote_client
    observed = {}

    def assert_committed(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            row = connection.execute(select(quotes)).mappings().one()
            observed["row"] = row
            observed["categories"] = (
                connection.execute(select(quote_categories.c.category_id))
                .scalars()
                .all()
            )
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))

    monkeypatch.setattr(admin_quotes, "purge_cache", assert_committed)
    with caplog.at_level("INFO", logger="app.admin"):
        response = client.post(
            "/admin/quotes", data=_quote_form(), follow_redirects=False
        )

    assert response.status_code == 303
    assert observed["row"]["text"] == "作成した名言"
    assert observed["row"]["author_id"] == 1
    assert observed["row"]["weight"] == 7
    assert observed["row"]["legacy_vote_count"] == 3
    assert observed["categories"] == [2]
    quote_id = observed["row"]["id"]
    assert {
        "/",
        "/quotes",
        "/quotes/latest",
        "/sitemap.xml",
        "/quotes/created-quote",
        "/quotes/created-quote/og.png",
        f"/quotes/q{quote_id}",
        "/authors/old-author",
        "/sources/source",
        "/characters/character",
        "/categories/old-category",
    } <= observed["paths"]
    assert f"action=create target=quotes:{quote_id}" in caplog.text


def test_quote_list_filters_by_id_or_text(admin_quote_client) -> None:
    client, engine = admin_quote_client
    with engine.begin() as connection:
        connection.execute(
            insert(quotes),
            [
                {
                    "id": 31,
                    "text": "検索できる本文",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 32,
                    "text": "別の本文",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )

    by_text = client.get("/admin/quotes", params={"q": "検索できる"})
    by_id = client.get("/admin/quotes", params={"q": "32"})

    assert "検索できる本文" in by_text.text
    assert "別の本文" not in by_text.text
    assert "別の本文" in by_id.text
    assert "検索できる本文" not in by_id.text


def test_quote_non_strict_qid_like_slug_remains_available() -> None:
    assert QuoteForm(text="本文", slug="q01").slug == "q01"
    assert QuoteForm(text="本文", slug="123").slug == "123"


def test_quote_update_uses_old_and_new_values_for_purge(
    admin_quote_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = admin_quote_client
    with engine.begin() as connection:
        connection.execute(
            insert(quotes),
            {
                "id": 10,
                "text": "更新前",
                "slug": "old-quote",
                "author_id": 1,
                "source_id": 1,
                "character_id": 1,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(insert(quote_categories), {"quote_id": 10, "category_id": 2})
    observed = {}

    def capture(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            observed["row"] = (
                connection.execute(select(quotes).where(quotes.c.id == 10))
                .mappings()
                .one()
            )
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.SKIPPED, ())

    monkeypatch.setattr(admin_quotes, "purge_cache", capture)
    response = client.post(
        "/admin/quotes/10",
        data=_quote_form(
            text="更新後",
            slug="new-quote",
            author_id="2",
            category_ids="3",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert observed["row"]["text"] == "更新後"
    assert observed["row"]["author_id"] == 2
    assert {
        "/quotes/old-quote",
        "/quotes/old-quote/og.png",
        "/quotes/new-quote",
        "/quotes/new-quote/og.png",
        "/quotes/q10",
        "/authors/old-author",
        "/authors/new-author",
        "/categories/old-category",
        "/categories/new-category",
    } <= observed["paths"]


def test_quote_slug_removal_purges_qid(
    admin_quote_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = admin_quote_client
    with engine.begin() as connection:
        connection.execute(
            insert(quotes),
            {
                "id": 11,
                "text": "slug削除前",
                "slug": "remove-slug",
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
    observed = {}

    def capture(paths: list[str]) -> CachePurgeResult:
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.SKIPPED, ())

    monkeypatch.setattr(admin_quotes, "purge_cache", capture)
    response = client.post(
        "/admin/quotes/11",
        data=_quote_form(text="slug削除後", slug="", author_id=""),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "/quotes/remove-slug" in observed["paths"]
    assert "/quotes/q11" in observed["paths"]


@pytest.mark.parametrize("slug", ["q1", "1234", "-bad", "bad_slug"])
def test_quote_slug_format_error_redisplays_values(
    admin_quote_client, slug: str
) -> None:
    client, _engine = admin_quote_client
    response = client.post("/admin/quotes", data=_quote_form(slug=slug))

    assert response.status_code == 422
    assert "作成した名言" in response.text
    assert "slug" in response.text


@pytest.mark.parametrize("slug", ["latest", "page"])
def test_quote_reserved_public_route_slug_is_rejected(
    admin_quote_client, slug: str
) -> None:
    client, _engine = admin_quote_client
    response = client.post("/admin/quotes", data=_quote_form(slug=slug))

    assert response.status_code == 422
    assert "公開ページ用に予約" in response.text


def test_quote_duplicate_slug_and_level_one_category_are_form_errors(
    admin_quote_client,
) -> None:
    client, engine = admin_quote_client
    with engine.begin() as connection:
        connection.execute(
            insert(quotes),
            [
                {
                    "id": 40,
                    "text": "既存",
                    "slug": "duplicate",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 41,
                    "text": "更新対象",
                    "slug": "update-target",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )

    duplicate = client.post("/admin/quotes", data=_quote_form(slug="duplicate"))
    duplicate_update = client.post(
        "/admin/quotes/41", data=_quote_form(slug="duplicate")
    )
    invalid_category = client.post(
        "/admin/quotes", data=_quote_form(slug="valid", category_ids="1")
    )

    assert duplicate.status_code == 422
    assert "このslugは既に使われています" in duplicate.text
    assert duplicate_update.status_code == 422
    assert "このslugは既に使われています" in duplicate_update.text
    assert invalid_category.status_code == 422
    assert "level 2" in invalid_category.text


def test_quote_posts_require_csrf(admin_quote_client) -> None:
    client, _engine = admin_quote_client
    response = client.post("/admin/quotes", data={"text": "CSRFなし"})
    assert response.status_code == 403


def test_quote_delete_confirmation_and_delete(
    admin_quote_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, engine = admin_quote_client
    with engine.begin() as connection:
        connection.execute(
            insert(quotes),
            {
                "id": 20,
                "text": "削除対象",
                "slug": "delete-quote",
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(insert(quote_categories), {"quote_id": 20, "category_id": 2})
        connection.execute(
            insert(quote_likes),
            [
                {
                    "quote_id": 20,
                    "client_uuid": "00000000-0000-0000-0000-000000000001",
                    "created_at": INSTANT,
                },
                {
                    "quote_id": 20,
                    "client_uuid": "00000000-0000-0000-0000-000000000002",
                    "created_at": INSTANT,
                },
            ],
        )
    confirmation = client.get("/admin/quotes/20/delete")
    assert confirmation.status_code == 200
    assert "カテゴリ関連" in confirmation.text
    assert "1件" in confirmation.text
    assert "同時に削除されるいいね" in confirmation.text
    assert "2件" in confirmation.text

    observed = {}

    def assert_deleted(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            observed["count"] = connection.execute(
                select(func.count()).select_from(quotes).where(quotes.c.id == 20)
            ).scalar_one()
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.FAILED, tuple(paths))

    monkeypatch.setattr(admin_quotes, "purge_cache", assert_deleted)
    with caplog.at_level("INFO", logger="app.admin"):
        response = client.post(
            "/admin/quotes/20/delete",
            data={"csrf_token": issue_csrf_token(EMAIL)},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert observed["count"] == 0
    assert "/quotes/delete-quote" in observed["paths"]
    assert "action=delete target=quotes:20" in caplog.text
