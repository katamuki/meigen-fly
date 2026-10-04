from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select

from app.admin import issue_csrf_token
from app.db import create_db_engine, get_connection, metadata
from app.main import app
from app.routers import admin_authors
from app.schema import (
    author_country,
    author_professions,
    authors,
    countries,
    professions,
    quotes,
    sources,
)
from app.services.cache_purge import CachePurgeResult, CachePurgeStatus

EMAIL = "admin@example.com"
INSTANT = "2026-01-01T00:00:00.000000Z"


@pytest.fixture
def admin_author_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Engine]]:
    monkeypatch.setenv("ADMIN_DEV_EMAIL", EMAIL)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("PUBLIC_ORIGIN", "http://localhost:8000")
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'admin-authors.db'}")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(professions),
            [
                {
                    "id": 1,
                    "name": "旧職業",
                    "slug": "old-profession",
                    "display_order": 1,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 2,
                    "name": "新職業",
                    "slug": "new-profession",
                    "display_order": 2,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )
        connection.execute(
            insert(countries),
            [
                {
                    "id": 1,
                    "name": "旧国",
                    "slug": "old-country",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 2,
                    "name": "新国",
                    "slug": "new-country",
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


def _author_form(**overrides) -> dict:
    data = {
        "csrf_token": issue_csrf_token(EMAIL),
        "name": "作成した著者",
        "slug": "created-author",
        "name_reading": "さくせいしたちょしゃ",
        "name_kana": "サクセイシタチョシャ",
        "name_foreign": "Created Author",
        "description": "説明",
        "image_url": "https://example.com/image.jpg",
        "birth_date": "0480-01-01",
        "birth_era": "bc",
        "birth_precision": "year",
        "death_date": "0406-01-01",
        "death_era": "bc",
        "death_precision": "year",
        "profession_ids": ["1", "2"],
        "profession_order_1": "2",
        "profession_order_2": "1",
        "country_ids": ["1", "2"],
        "birth_country_id": "1",
    }
    data.update(overrides)
    return data


def test_author_create_relations_commit_before_purge_and_log(
    admin_author_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, engine = admin_author_client
    observed = {}

    def assert_committed(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            observed["author"] = connection.execute(select(authors)).mappings().one()
            observed["professions"] = connection.execute(
                select(
                    author_professions.c.profession_id,
                    author_professions.c.display_order,
                ).order_by(author_professions.c.display_order)
            ).all()
            observed["countries"] = connection.execute(
                select(
                    author_country.c.country_id,
                    author_country.c.is_birth_country,
                ).order_by(author_country.c.country_id)
            ).all()
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))

    monkeypatch.setattr(admin_authors, "purge_cache", assert_committed)
    with caplog.at_level("INFO", logger="app.admin"):
        response = client.post(
            "/admin/authors", data=_author_form(), follow_redirects=False
        )

    assert response.status_code == 303
    assert observed["author"]["name"] == "作成した著者"
    assert observed["author"]["birth_era"] == "bc"
    assert observed["professions"] == [(2, 1), (1, 2)]
    assert observed["countries"] == [(1, 1), (2, 0)]
    assert {
        "/authors",
        "/authors/created-author",
        "/authors/created-author/og.png",
        "/authors/places/old-country",
        "/authors/places/new-country",
        "/professions/old-profession",
        "/professions/new-profession",
        "/sitemap.xml",
    } <= observed["paths"]
    author_id = observed["author"]["id"]
    assert f"action=create target=authors:{author_id}" in caplog.text


def test_author_list_filters_by_name(admin_author_client) -> None:
    client, engine = admin_author_client
    with engine.begin() as connection:
        connection.execute(
            insert(authors),
            [
                {
                    "id": 31,
                    "name": "検索対象著者",
                    "slug": "search-target",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 32,
                    "name": "別の著者",
                    "slug": "other-author",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )

    response = client.get("/admin/authors", params={"q": "検索対象"})

    assert "検索対象著者" in response.text
    assert "別の著者" not in response.text


def test_author_update_uses_old_and_new_values_for_purge(
    admin_author_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = admin_author_client
    with engine.begin() as connection:
        connection.execute(
            insert(authors),
            {
                "id": 10,
                "name": "更新前",
                "slug": "old-author",
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(author_professions),
            {
                "author_id": 10,
                "profession_id": 1,
                "display_order": 1,
                "created_at": INSTANT,
            },
        )
        connection.execute(
            insert(author_country),
            {
                "author_id": 10,
                "country_id": 1,
                "is_birth_country": 1,
                "created_at": INSTANT,
            },
        )
    observed = {}

    def capture(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            observed["row"] = (
                connection.execute(select(authors).where(authors.c.id == 10))
                .mappings()
                .one()
            )
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.SKIPPED, ())

    monkeypatch.setattr(admin_authors, "purge_cache", capture)
    response = client.post(
        "/admin/authors/10",
        data=_author_form(
            name="更新後",
            slug="new-author",
            profession_ids=["2"],
            profession_order_2="1",
            country_ids=["2"],
            birth_country_id="2",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert observed["row"]["name"] == "更新後"
    assert {
        "/authors/old-author",
        "/authors/old-author/og.png",
        "/authors/new-author",
        "/authors/new-author/og.png",
        "/authors/places/old-country",
        "/authors/places/new-country",
        "/professions/old-profession",
        "/professions/new-profession",
    } <= observed["paths"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"birth_precision": "unknown"}, "日付を空欄"),
        ({"death_era": "bc", "birth_era": "ad"}, "以前"),
        ({"birth_country_id": "2", "country_ids": ["1"]}, "選択した国"),
        (
            {"profession_order_1": "1", "profession_order_2": "1"},
            "重複しない",
        ),
        ({"birth_country_id": ["1", "2"]}, "1件だけ"),
    ],
)
def test_author_validation_errors_redisplay_input(
    admin_author_client, changes: dict, message: str
) -> None:
    client, _engine = admin_author_client
    response = client.post("/admin/authors", data=_author_form(**changes))

    assert response.status_code == 422
    assert "作成した著者" in response.text
    assert message in response.text
    if message == "重複しない":
        assert 'name="profession_order_1" value="1"' in response.text
        assert 'name="profession_order_2" value="1"' in response.text


def test_author_duplicate_slug_is_form_error(admin_author_client) -> None:
    client, engine = admin_author_client
    with engine.begin() as connection:
        connection.execute(
            insert(authors),
            [
                {
                    "id": 40,
                    "name": "既存",
                    "slug": "duplicate",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 41,
                    "name": "更新対象",
                    "slug": "update-target",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )
    response = client.post("/admin/authors", data=_author_form(slug="duplicate"))
    update_response = client.post(
        "/admin/authors/41", data=_author_form(slug="duplicate")
    )
    assert response.status_code == 422
    assert "このslugは既に使われています" in response.text
    assert update_response.status_code == 422
    assert "このslugは既に使われています" in update_response.text


def test_author_reserved_public_route_slug_is_rejected(admin_author_client) -> None:
    client, _engine = admin_author_client
    response = client.post("/admin/authors", data=_author_form(slug="places"))

    assert response.status_code == 422
    assert "公開ページ用に予約" in response.text


def test_author_posts_require_csrf(admin_author_client) -> None:
    client, _engine = admin_author_client
    response = client.post("/admin/authors", data={"name": "CSRFなし"})
    assert response.status_code == 403


def test_author_delete_shows_impact_and_sets_foreign_keys_null(
    admin_author_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, engine = admin_author_client
    with engine.begin() as connection:
        connection.execute(
            insert(authors),
            {
                "id": 20,
                "name": "削除著者",
                "slug": "delete-author",
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(quotes),
            {
                "id": 20,
                "text": "著者が外れる名言",
                "author_id": 20,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(sources),
            {
                "id": 20,
                "title": "著者が外れる出典",
                "slug": "delete-source",
                "author_id": 20,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
    confirmation = client.get("/admin/authors/20/delete")
    assert confirmation.status_code == 200
    assert "著者が外れる名言" in confirmation.text
    assert "著者が外れる出典" in confirmation.text
    assert confirmation.text.count("1件") >= 2

    observed = {}

    def assert_deleted(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            observed["author_count"] = connection.execute(
                select(func.count()).select_from(authors).where(authors.c.id == 20)
            ).scalar_one()
            observed["quote_author"] = connection.execute(
                select(quotes.c.author_id).where(quotes.c.id == 20)
            ).scalar_one()
            observed["source_author"] = connection.execute(
                select(sources.c.author_id).where(sources.c.id == 20)
            ).scalar_one()
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.FAILED, tuple(paths))

    monkeypatch.setattr(admin_authors, "purge_cache", assert_deleted)
    with caplog.at_level("INFO", logger="app.admin"):
        response = client.post(
            "/admin/authors/20/delete",
            data={"csrf_token": issue_csrf_token(EMAIL)},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert observed["author_count"] == 0
    assert observed["quote_author"] is None
    assert observed["source_author"] is None
    assert "/authors/delete-author" in observed["paths"]
    assert "action=delete target=authors:20" in caplog.text
