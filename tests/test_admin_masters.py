from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select

from app.admin import issue_csrf_token
from app.db import create_db_engine, get_connection, metadata
from app.main import app
from app.routers import (
    admin_categories,
    admin_characters,
    admin_professions,
    admin_sources,
)
from app.schema import (
    author_professions,
    authors,
    categories,
    characters,
    professions,
    quote_categories,
    quotes,
    source_type_assignments,
    source_types,
    sources,
)
from app.services.cache_purge import CachePurgeResult, CachePurgeStatus

EMAIL = "admin@example.com"
INSTANT = "2026-01-01T00:00:00.000000Z"


@pytest.fixture
def admin_master_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Engine]]:
    monkeypatch.setenv("ADMIN_DEV_EMAIL", EMAIL)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("PUBLIC_ORIGIN", "http://localhost:8000")
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'admin-masters.db'}")
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
            insert(source_types),
            [
                {
                    "id": 1,
                    "name": "書籍",
                    "slug": "book",
                    "display_order": 1,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 2,
                    "name": "映画",
                    "slug": "movie",
                    "display_order": 2,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
            ],
        )
        connection.execute(
            insert(sources),
            {
                "id": 1,
                "title": "旧出典",
                "slug": "old-source",
                "author_id": 1,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(categories),
            {
                "id": 1,
                "name": "旧親",
                "slug": "old-parent",
                "level": 1,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(categories),
            {
                "id": 2,
                "name": "子",
                "slug": "child",
                "level": 2,
                "parent_id": 1,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )

    def override_connection():
        with engine.begin() as connection:
            yield connection

    app.dependency_overrides[get_connection] = override_connection
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def _csrf() -> str:
    return issue_csrf_token(EMAIL)


def _ok_purger(observed: list[set[str]], engine: Engine, check) -> callable:
    def purge(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            check(connection)
        observed.append(set(paths))
        return CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))

    return purge


def test_category_crud_commits_purges_old_and_new_and_logs(
    admin_master_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, engine = admin_master_client
    observed: list[set[str]] = []
    monkeypatch.setattr(
        admin_categories,
        "purge_cache",
        _ok_purger(
            observed,
            engine,
            lambda connection: connection.execute(
                select(categories.c.slug).where(categories.c.slug == "created-category")
            ).scalar_one(),
        ),
    )
    with caplog.at_level("INFO", logger="app.admin"):
        response = client.post(
            "/admin/categories",
            data={
                "csrf_token": _csrf(),
                "name": "作成カテゴリ",
                "slug": "created-category",
                "level": "2",
                "parent_id": "1",
                "sort_order": "4",
                "description": "説明",
                "color": "blue",
            },
            follow_redirects=False,
        )
    assert response.status_code == 303
    with engine.connect() as connection:
        row = (
            connection.execute(
                select(categories).where(categories.c.slug == "created-category")
            )
            .mappings()
            .one()
        )
    assert row["parent_id"] == 1
    assert {
        "/categories",
        "/categories/created-category",
        "/categories/old-parent",
        "/sitemap.xml",
    } <= observed[-1]
    assert "action=create target=categories:" in caplog.text

    monkeypatch.setattr(
        admin_categories,
        "purge_cache",
        lambda paths: (
            observed.append(set(paths))
            or CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))
        ),
    )
    response = client.post(
        f"/admin/categories/{row['id']}",
        data={
            "csrf_token": _csrf(),
            "name": "更新カテゴリ",
            "slug": "updated-category",
            "level": "2",
            "parent_id": "1",
            "sort_order": "5",
            "color": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert {"/categories/created-category", "/categories/updated-category"} <= observed[
        -1
    ]
    response = client.post(
        f"/admin/categories/{row['id']}/delete",
        data={"csrf_token": _csrf()},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with engine.connect() as connection:
        assert (
            connection.execute(
                select(categories.c.id).where(categories.c.id == row["id"])
            ).first()
            is None
        )


def test_category_hierarchy_errors_are_redisplayed(admin_master_client) -> None:
    client, engine = admin_master_client
    with engine.begin() as connection:
        connection.execute(
            insert(categories),
            {
                "id": 3,
                "name": "別の親",
                "slug": "other-parent",
                "level": 1,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
    response = client.post(
        "/admin/categories/1",
        data={
            "csrf_token": _csrf(),
            "name": "親",
            "slug": "old-parent",
            "level": "2",
            "parent_id": "3",
            "sort_order": "0",
        },
    )
    assert response.status_code == 422
    assert "子カテゴリがあるため" in response.text
    with engine.begin() as connection:
        connection.execute(
            insert(quotes),
            {"id": 1, "text": "名言", "created_at": INSTANT, "updated_at": INSTANT},
        )
        connection.execute(insert(quote_categories), {"quote_id": 1, "category_id": 2})
    response = client.post(
        "/admin/categories/2",
        data={
            "csrf_token": _csrf(),
            "name": "子",
            "slug": "child",
            "level": "1",
            "parent_id": "",
            "sort_order": "0",
        },
    )
    assert response.status_code == 422
    assert "名言が関連付いているため" in response.text
    response = client.post(
        "/admin/categories",
        data={
            "csrf_token": _csrf(),
            "name": "不正",
            "slug": "invalid-parent",
            "level": "2",
            "parent_id": "2",
            "sort_order": "0",
        },
    )
    assert response.status_code == 422
    assert "level 1カテゴリ" in response.text
    response = client.post("/admin/categories/1/delete", data={"csrf_token": _csrf()})
    assert response.status_code == 422
    assert "子カテゴリがあるため削除できません" in response.text


def test_character_crud_validation_counts_and_purge(
    admin_master_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = admin_master_client
    observed: list[set[str]] = []
    monkeypatch.setattr(
        admin_characters,
        "purge_cache",
        lambda paths: (
            observed.append(set(paths))
            or CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))
        ),
    )
    response = client.post(
        "/admin/characters",
        data={
            "csrf_token": _csrf(),
            "name": "人物",
            "slug": "created-character",
            "source_id": "1",
            "description": "説明",
            "character_type": "narrator",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with engine.connect() as connection:
        row = connection.execute(select(characters)).mappings().one()
    assert row["character_type"] == "narrator"
    assert {
        "/characters/created-character",
        "/characters",
        "/sources/old-source",
    } <= observed[-1]
    response = client.post(
        f"/admin/characters/{row['id']}",
        data={
            "csrf_token": _csrf(),
            "name": "更新人物",
            "slug": "updated-character",
            "source_id": "",
            "character_type": "author_voice",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert {
        "/characters/created-character",
        "/characters/updated-character",
        "/sources/old-source",
    } <= observed[-1]
    response = client.post(
        f"/admin/characters/{row['id']}/delete",
        data={"csrf_token": _csrf()},
        follow_redirects=False,
    )
    assert response.status_code == 303
    response = client.post(
        "/admin/characters",
        data={
            "csrf_token": _csrf(),
            "name": "x",
            "slug": "bad slug",
            "character_type": "invalid",
        },
    )
    assert response.status_code == 422
    assert "bad slug" in response.text


def test_source_crud_relations_commit_and_purge(
    admin_master_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = admin_master_client
    observed: list[set[str]] = []
    monkeypatch.setattr(
        admin_sources,
        "purge_cache",
        _ok_purger(
            observed,
            engine,
            lambda connection: connection.execute(
                select(sources.c.id).where(sources.c.slug == "created-source")
            ).scalar_one(),
        ),
    )
    response = client.post(
        "/admin/sources",
        data={
            "csrf_token": _csrf(),
            "title": "作成出典",
            "slug": "created-source",
            "author_id": "1",
            "published_year": "2026",
            "description": "説明",
            "type_ids": ["1", "2"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with engine.connect() as connection:
        row = (
            connection.execute(
                select(sources).where(sources.c.slug == "created-source")
            )
            .mappings()
            .one()
        )
        assert set(
            connection.execute(
                select(source_type_assignments.c.type_id).where(
                    source_type_assignments.c.source_id == row["id"]
                )
            ).scalars()
        ) == {1, 2}
    assert {
        "/sources",
        "/sources/created-source",
        "/authors/author",
        "/sitemap.xml",
    } <= observed[-1]
    monkeypatch.setattr(
        admin_sources,
        "purge_cache",
        lambda paths: (
            observed.append(set(paths))
            or CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))
        ),
    )
    response = client.post(
        f"/admin/sources/{row['id']}",
        data={
            "csrf_token": _csrf(),
            "title": "更新出典",
            "slug": "updated-source",
            "author_id": "",
            "published_year": "1",
            "type_ids": "2",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert {
        "/sources/created-source",
        "/sources/updated-source",
        "/authors/author",
    } <= observed[-1]
    response = client.post(
        f"/admin/sources/{row['id']}/delete",
        data={"csrf_token": _csrf()},
        follow_redirects=False,
    )
    assert response.status_code == 303
    response = client.post(
        "/admin/sources",
        data={
            "csrf_token": _csrf(),
            "title": "不正",
            "slug": "bad slug",
            "published_year": "0",
        },
    )
    assert response.status_code == 422
    assert "bad slug" in response.text


def test_profession_crud_unique_messages_commit_and_purge(
    admin_master_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = admin_master_client
    observed: list[set[str]] = []
    monkeypatch.setattr(
        admin_professions,
        "purge_cache",
        _ok_purger(
            observed,
            engine,
            lambda connection: connection.execute(
                select(professions.c.id).where(professions.c.slug == "writer")
            ).scalar_one(),
        ),
    )
    response = client.post(
        "/admin/professions",
        data={
            "csrf_token": _csrf(),
            "name": "作家",
            "slug": "writer",
            "display_order": "2",
            "description": "説明",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with engine.connect() as connection:
        row = connection.execute(select(professions)).mappings().one()
    assert observed[-1] == {"/professions", "/professions/writer"}
    response = client.post(
        "/admin/professions",
        data={
            "csrf_token": _csrf(),
            "name": "作家",
            "slug": "other",
            "display_order": "0",
        },
    )
    assert response.status_code == 422
    assert "この名称は既に使われています" in response.text
    response = client.post(
        "/admin/professions",
        data={
            "csrf_token": _csrf(),
            "name": "別",
            "slug": "writer",
            "display_order": "0",
        },
    )
    assert response.status_code == 422
    assert "このslugは既に使われています" in response.text
    with engine.begin() as connection:
        connection.execute(
            insert(author_professions),
            {
                "author_id": 1,
                "profession_id": row["id"],
                "display_order": 1,
                "created_at": INSTANT,
            },
        )
    response = client.post(
        f"/admin/professions/{row['id']}",
        data={
            "csrf_token": _csrf(),
            "name": "入力保持名",
            "slug": "bad slug",
            "display_order": "3",
        },
    )
    assert response.status_code == 422
    assert "入力保持名" in response.text
    assert "bad slug" in response.text
    monkeypatch.setattr(
        admin_professions,
        "purge_cache",
        lambda paths: (
            observed.append(set(paths))
            or CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))
        ),
    )
    response = client.post(
        f"/admin/professions/{row['id']}",
        data={
            "csrf_token": _csrf(),
            "name": "文筆家",
            "slug": "author-job",
            "display_order": "3",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert {
        "/professions/writer",
        "/professions/author-job",
        "/authors/author",
    } <= observed[-1]
    delete_page = client.get(f"/admin/professions/{row['id']}/delete")
    assert "関連が外れる著者</dt><dd>1件" in delete_page.text
    response = client.post(
        f"/admin/professions/{row['id']}/delete",
        data={"csrf_token": _csrf()},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with engine.connect() as connection:
        assert (
            connection.execute(
                select(professions.c.id).where(professions.c.id == row["id"])
            ).first()
            is None
        )
        assert connection.execute(select(author_professions)).first() is None


@pytest.mark.parametrize(
    "path",
    ["/admin/categories", "/admin/characters", "/admin/sources", "/admin/professions"],
)
def test_master_create_posts_require_csrf(admin_master_client, path: str) -> None:
    client, _engine = admin_master_client
    assert client.post(path, data={"name": "x"}).status_code == 403


@pytest.mark.parametrize(
    ("path", "data"),
    [
        (
            "/admin/categories",
            {"name": "重複", "slug": "old-parent", "level": "1", "sort_order": "0"},
        ),
        (
            "/admin/characters",
            {"name": "一", "slug": "same", "character_type": "character"},
        ),
        ("/admin/sources", {"title": "重複", "slug": "old-source"}),
    ],
)
def test_master_slug_duplicate_is_specific(
    admin_master_client, path: str, data: dict
) -> None:
    client, _engine = admin_master_client
    first = {"csrf_token": _csrf(), **data}
    if path == "/admin/characters":
        assert client.post(path, data=first, follow_redirects=False).status_code == 303
    response = client.post(path, data=first)
    assert response.status_code == 422
    assert "このslugは既に使われています" in response.text


@pytest.mark.parametrize(
    ("path", "data"),
    [
        (
            "/admin/categories",
            {"name": "不正", "slug": "bad slug", "level": "1", "sort_order": "0"},
        ),
        (
            "/admin/characters",
            {"name": "不正", "slug": "bad slug", "character_type": "character"},
        ),
        ("/admin/sources", {"title": "不正", "slug": "bad slug"}),
        (
            "/admin/professions",
            {"name": "不正", "slug": "bad slug", "display_order": "0"},
        ),
    ],
)
def test_master_slug_format_error_redisplays_input(
    admin_master_client, path: str, data: dict
) -> None:
    client, _engine = admin_master_client
    response = client.post(path, data={"csrf_token": _csrf(), **data})
    assert response.status_code == 422
    assert "slugは小文字の英数字とハイフン" in response.text
    assert "bad slug" in response.text


def test_delete_confirmation_shows_actual_counts(admin_master_client) -> None:
    client, engine = admin_master_client
    with engine.begin() as connection:
        connection.execute(
            insert(characters),
            {
                "id": 1,
                "name": "人物",
                "slug": "person",
                "source_id": 1,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(quotes),
            {
                "id": 1,
                "text": "名言",
                "source_id": 1,
                "character_id": 1,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(insert(quote_categories), {"quote_id": 1, "category_id": 2})
    assert (
        "関連が外れる名言</dt><dd>1件" in client.get("/admin/categories/2/delete").text
    )
    assert (
        "登場人物が外れる名言</dt><dd>1件"
        in client.get("/admin/characters/1/delete").text
    )
    source_page = client.get("/admin/sources/1/delete").text
    assert "出典が外れる名言</dt><dd>1件" in source_page
    assert "出典が外れる登場人物</dt><dd>1件" in source_page
    assert (
        client.post(
            "/admin/characters/1/delete",
            data={"csrf_token": _csrf()},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/admin/sources/1/delete",
            data={"csrf_token": _csrf()},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/admin/categories/2/delete",
            data={"csrf_token": _csrf()},
            follow_redirects=False,
        ).status_code
        == 303
    )
    with engine.connect() as connection:
        quote = connection.execute(select(quotes)).mappings().one()
        assert quote["source_id"] is None
        assert quote["character_id"] is None
        assert connection.execute(select(quote_categories)).first() is None
