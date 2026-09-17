from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select

from app.admin import issue_csrf_token
from app.db import create_db_engine, get_connection, metadata
from app.main import app
from app.routers import admin as admin_router
from app.schema import (
    author_rankings,
    authors,
    categories,
    category_rankings,
    quote_categories,
    quote_ranking_scores,
    quotes,
)
from app.services.cache_purge import CachePurgeResult, CachePurgeStatus

EMAIL = "admin@example.com"
INSTANT = "2026-01-01T00:00:00.000000Z"


@pytest.fixture
def admin_ranking_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Engine]]:
    monkeypatch.setenv("ADMIN_DEV_EMAIL", EMAIL)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("PUBLIC_ORIGIN", "http://localhost:8000")
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)

    engine = create_db_engine(f"sqlite:///{tmp_path / 'admin-ranking.db'}")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(authors),
            {
                "id": 1,
                "name": "著者",
                "slug": "author",
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
                    "name": "子",
                    "slug": "child",
                    "level": 2,
                    "parent_id": 1,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )
        connection.execute(
            insert(quotes),
            {
                "id": 1,
                "text": "名言",
                "author_id": 1,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(insert(quote_categories), {"quote_id": 1, "category_id": 2})

    def override_connection():
        with engine.begin() as connection:
            yield connection

    app.dependency_overrides[get_connection] = override_connection
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def test_refresh_post_requires_csrf(admin_ranking_client) -> None:
    client, _engine = admin_ranking_client
    response = client.post(
        "/admin/rankings/refresh", data={"other": "value"}, follow_redirects=False
    )

    assert response.status_code == 403


def test_refresh_updates_three_tables_then_purges_and_shows_notice(
    admin_ranking_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = admin_ranking_client
    observed = {}

    def assert_committed(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            observed["counts"] = tuple(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
                for table in (
                    quote_ranking_scores,
                    author_rankings,
                    category_rankings,
                )
            )
        observed["paths"] = paths
        return CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))

    monkeypatch.setattr(admin_router, "purge_cache", assert_committed)
    response = client.post(
        "/admin/rankings/refresh",
        data={"csrf_token": issue_csrf_token(EMAIL)},
    )

    assert response.status_code == 200
    assert observed["counts"] == (1, 1, 1)
    assert observed["paths"] == [
        "/",
        "/ranking",
        "/ranking/authors",
        "/ranking/categories",
    ]
    assert "ランキングを再計算しました" in response.text
    assert "名言 1件、著者 1件、カテゴリ 1件" in response.text
    assert "キャッシュパージ成功" in response.text
    assert "JST" in response.text


def test_refresh_failure_is_logged_and_shown(
    admin_ranking_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _engine = admin_ranking_client

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(admin_router, "refresh_rankings", fail)
    with caplog.at_level("INFO"):
        response = client.post(
            "/admin/rankings/refresh",
            data={"csrf_token": issue_csrf_token(EMAIL)},
        )

    assert response.status_code == 200
    assert "前回の結果を維持しています" in response.text
    assert "ranking refresh failed" in caplog.text
    assert "action=refresh_failed target=rankings" in caplog.text
