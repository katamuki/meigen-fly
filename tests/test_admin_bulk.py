import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.admin import issue_csrf_token
from app.db import create_db_engine, get_connection, metadata
from app.main import app
from app.routers import admin_bulk
from app.schema import (
    author_country,
    author_professions,
    authors,
    characters,
    countries,
    professions,
    quotes,
    sources,
)
from app.services.cache_purge import CachePurgeResult, CachePurgeStatus

EMAIL = "admin@example.com"
INSTANT = "2026-01-01T00:00:00.000000Z"


@pytest.fixture
def admin_bulk_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Engine]]:
    monkeypatch.setenv("ADMIN_DEV_EMAIL", EMAIL)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("PUBLIC_ORIGIN", "http://localhost:8000")
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'admin-bulk.db'}")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(authors),
            [
                {
                    "id": 1,
                    "name": "既存著者",
                    "slug": "existing-author",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 2,
                    "name": "同名著者",
                    "slug": "same-name-existing",
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
                "name": "登場人物",
                "slug": "character",
                "created_at": INSTANT,
                "updated_at": INSTANT,
            },
        )
        connection.execute(
            insert(professions),
            [
                {
                    "id": 1,
                    "name": "作家",
                    "slug": "writer",
                    "display_order": 1,
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 2,
                    "name": "詩人",
                    "slug": "poet",
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
                    "name": "日本",
                    "slug": "japan",
                    "created_at": INSTANT,
                    "updated_at": INSTANT,
                },
                {
                    "id": 2,
                    "name": "フランス",
                    "slug": "france",
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


def _quote_bulk_form(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "csrf_token": issue_csrf_token(EMAIL),
        "bulk_input": "一つ目\tFirst\t7\n\n二つ目\t\t",
        "author_id": "1",
        "source_id": "1",
        "character_id": "1",
        "weight": "4",
        "enable": "1",
        "display_language_preference": "en",
    }
    data.update(overrides)
    return data


def _author_item(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "新しい著者",
        "slug": "new-author",
        "name_reading": "あたらしいちょしゃ",
        "name_kana": "アタラシイチョシャ",
        "name_foreign": "New Author",
        "description": "説明",
        "image_url": "https://example.com/author.jpg",
        "birth_date": "0480-01-01",
        "birth_era": "bc",
        "birth_precision": "year",
        "death_date": "0406-01-01",
        "death_era": "bc",
        "death_precision": "year",
        "professions": ["作家", "詩人"],
        "countries": ["日本", "フランス"],
        "birth_country": "日本",
    }
    data.update(overrides)
    return data


def _author_bulk_form(items: object) -> dict[str, str]:
    return {
        "csrf_token": issue_csrf_token(EMAIL),
        "json_input": json.dumps(items, ensure_ascii=False),
    }


@pytest.mark.parametrize(
    ("changes", "messages"),
    [
        ({"bulk_input": "本文\t英文\t5\t余分"}, ["3列まで"]),
        (
            {"bulk_input": "範囲外\t\t11\n非整数\t\tabc"},
            ["1行目", "2行目", "重み"],
        ),
        ({"bulk_input": "\tEnglish\t5"}, ["1行目", "日本語本文"]),
        (
            {"author_id": "", "source_id": "", "character_id": ""},
            ["最低1つ"],
        ),
        ({"bulk_input": "\n\u3000\n\t"}, ["有効な行がありません"]),
    ],
)
def test_quote_bulk_validation_collects_errors_and_preserves_input(
    admin_bulk_client,
    changes: dict[str, object],
    messages: list[str],
) -> None:
    client, _engine = admin_bulk_client
    response = client.post(
        "/admin/quotes/bulk/confirm", data=_quote_bulk_form(**changes)
    )

    assert response.status_code == 422
    for message in messages:
        assert message in response.text
    if "bulk_input" in changes:
        first_text = str(changes["bulk_input"]).split("\n", 1)[0].split("\t", 1)[0]
        if first_text:
            assert first_text in response.text


def test_quote_bulk_limit(admin_bulk_client) -> None:
    client, _engine = admin_bulk_client
    bulk_input = "\n".join(f"名言{i}" for i in range(501))

    response = client.post(
        "/admin/quotes/bulk/confirm",
        data=_quote_bulk_form(bulk_input=bulk_input),
    )

    assert response.status_code == 422
    assert "最大500件" in response.text


def test_quote_bulk_common_error_is_not_repeated_for_each_line(
    admin_bulk_client,
) -> None:
    client, _engine = admin_bulk_client
    response = client.post(
        "/admin/quotes/bulk/confirm",
        data=_quote_bulk_form(
            weight="invalid",
            bulk_input="一行目\n二行目\n三行目",
        ),
    )

    assert response.status_code == 422
    assert response.text.count("既定の重みは1〜10の整数") == 1
    assert "weightの形式" not in response.text


def test_quote_bulk_confirm_then_create_commits_before_purge_and_logs(
    admin_bulk_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, engine = admin_bulk_client
    form = _quote_bulk_form()
    confirmation = client.post("/admin/quotes/bulk/confirm", data=form)
    assert confirmation.status_code == 200
    assert "2件を登録" in confirmation.text
    assert "既存著者" in confirmation.text
    assert "出典" in confirmation.text
    assert "登場人物" in confirmation.text
    assert "著者ID" not in confirmation.text
    observed: dict[str, object] = {}

    def assert_committed(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            observed["rows"] = list(
                connection.execute(select(quotes).order_by(quotes.c.id)).mappings()
            )
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.SUCCESS, tuple(paths))

    monkeypatch.setattr(admin_bulk, "purge_cache", assert_committed)
    with caplog.at_level("INFO", logger="app.admin"):
        response = client.post("/admin/quotes/bulk", data=form, follow_redirects=False)

    assert response.status_code == 303
    rows = observed["rows"]
    assert [(row["text"], row["text_en"], row["weight"]) for row in rows] == [
        ("一つ目", "First", 7),
        ("二つ目", None, 4),
    ]
    assert all(row["slug"] is None for row in rows)
    assert all(row["enable"] == 1 for row in rows)
    assert all(row["display_language_preference"] == "en" for row in rows)
    assert observed["paths"] == {
        "/",
        "/quotes",
        "/quotes/latest",
        "/sitemap.xml",
        "/authors/existing-author",
        "/sources/source",
        "/characters/character",
    }
    assert "action=bulk_create target=quotes:count=2" in caplog.text
    assert caplog.text.count("action=bulk_create") == 1


def test_quote_bulk_registration_revalidates_tampered_hidden_input(
    admin_bulk_client,
) -> None:
    client, engine = admin_bulk_client
    response = client.post(
        "/admin/quotes/bulk",
        data=_quote_bulk_form(bulk_input="改変\t\t99"),
    )

    assert response.status_code == 422
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(quotes)).scalar_one()
            == 0
        )


def test_bulk_posts_require_csrf(admin_bulk_client) -> None:
    client, _engine = admin_bulk_client
    data = {"bulk_input": "CSRFなし", "json_input": "[]"}
    assert client.post("/admin/quotes/bulk/confirm", data=data).status_code == 403
    assert client.post("/admin/quotes/bulk/edit", data=data).status_code == 403
    assert client.post("/admin/quotes/bulk", data=data).status_code == 403
    assert client.post("/admin/authors/bulk/confirm", data=data).status_code == 403
    assert client.post("/admin/authors/bulk/edit", data=data).status_code == 403
    assert client.post("/admin/authors/bulk", data=data).status_code == 403


@pytest.mark.parametrize(
    ("raw_input", "message"),
    [
        ("not-json", "JSONの形式が不正"),
        (json.dumps({"authors": []}), "最上位は著者の配列"),
        ("[]", "1件以上"),
        (json.dumps([_author_item()] * 11, ensure_ascii=False), "10件以内"),
        (json.dumps([{"slug": "missing-name"}]), "著者名は必須"),
        (
            json.dumps(
                [_author_item(birthdate="0480-01-01", desciption="誤記")],
                ensure_ascii=False,
            ),
            "不明な項目「birthdate」",
        ),
        (
            json.dumps(
                [_author_item(slug="same"), _author_item(name="別名", slug="same")],
                ensure_ascii=False,
            ),
            "入力内で重複",
        ),
        (
            json.dumps([_author_item(slug="existing-author")], ensure_ascii=False),
            "既に使われています",
        ),
        (
            json.dumps([_author_item(professions=["未登録職業"])], ensure_ascii=False),
            "登録されていません",
        ),
        (
            json.dumps([_author_item(countries=["未登録国"])], ensure_ascii=False),
            "登録されていません",
        ),
        (
            json.dumps(
                [_author_item(birth_date="2020-02-30", birth_era="ad")],
                ensure_ascii=False,
            ),
            "存在する日付",
        ),
        (
            json.dumps(
                [
                    _author_item(
                        birth_date="2020-01-01",
                        birth_era="ad",
                        death_date="1900-01-01",
                        death_era="ad",
                    )
                ],
                ensure_ascii=False,
            ),
            "以前",
        ),
    ],
)
def test_author_bulk_validation_errors(
    admin_bulk_client, raw_input: str, message: str
) -> None:
    client, _engine = admin_bulk_client
    response = client.post(
        "/admin/authors/bulk/confirm",
        data={"csrf_token": issue_csrf_token(EMAIL), "json_input": raw_input},
    )

    assert response.status_code == 422
    assert message in response.text


def test_author_bulk_warnings_do_not_block_confirmation(admin_bulk_client) -> None:
    client, _engine = admin_bulk_client
    items = [
        _author_item(name="同名著者", slug="same-name-new-one"),
        _author_item(name="同名著者", slug="same-name-new-two"),
    ]

    response = client.post("/admin/authors/bulk/confirm", data=_author_bulk_form(items))

    assert response.status_code == 200
    assert "同名の著者が既にいます" in response.text
    assert "入力内" in response.text


def test_author_bulk_confirmation_shows_readings_and_life_dates(
    admin_bulk_client,
) -> None:
    client, _engine = admin_bulk_client

    response = client.post(
        "/admin/authors/bulk/confirm", data=_author_bulk_form([_author_item()])
    )

    assert response.status_code == 200
    assert "あたらしいちょしゃ" in response.text
    assert "アタラシイチョシャ" in response.text
    assert "New Author" in response.text
    assert "0480-01-01（bc / year）" in response.text
    assert "0406-01-01（bc / year）" in response.text


def test_bulk_edit_returns_to_input_with_values(admin_bulk_client) -> None:
    client, _engine = admin_bulk_client
    quote_form = _quote_bulk_form()
    quote_response = client.post("/admin/quotes/bulk/edit", data=quote_form)
    author_form = _author_bulk_form([_author_item()])
    author_response = client.post("/admin/authors/bulk/edit", data=author_form)

    assert quote_response.status_code == 200
    assert "一つ目\tFirst\t7" in quote_response.text
    assert 'option value="1" selected' in quote_response.text
    assert author_response.status_code == 200
    assert "new-author" in author_response.text


def test_author_bulk_confirm_then_create_relations_purge_and_log(
    admin_bulk_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, engine = admin_bulk_client
    items = [
        _author_item(),
        _author_item(
            name="二人目",
            slug="second-author",
            professions=["詩人"],
            countries=["フランス"],
            birth_country="フランス",
        ),
    ]
    form = _author_bulk_form(items)
    confirmation = client.post("/admin/authors/bulk/confirm", data=form)
    assert confirmation.status_code == 200
    observed: dict[str, object] = {}

    def assert_committed(paths: list[str]) -> CachePurgeResult:
        with engine.connect() as connection:
            observed["authors"] = list(
                connection.execute(
                    select(authors).where(authors.c.id > 2).order_by(authors.c.id)
                ).mappings()
            )
            observed["professions"] = connection.execute(
                select(
                    author_professions.c.author_id,
                    author_professions.c.profession_id,
                    author_professions.c.display_order,
                ).order_by(
                    author_professions.c.author_id,
                    author_professions.c.display_order,
                )
            ).all()
            observed["countries"] = connection.execute(
                select(
                    author_country.c.author_id,
                    author_country.c.country_id,
                    author_country.c.is_birth_country,
                ).order_by(author_country.c.author_id, author_country.c.country_id)
            ).all()
        observed["paths"] = set(paths)
        return CachePurgeResult(CachePurgeStatus.SKIPPED, ())

    monkeypatch.setattr(admin_bulk, "purge_cache", assert_committed)
    with caplog.at_level("INFO", logger="app.admin"):
        response = client.post("/admin/authors/bulk", data=form, follow_redirects=False)

    assert response.status_code == 303
    assert [row["slug"] for row in observed["authors"]] == [
        "new-author",
        "second-author",
    ]
    assert observed["professions"] == [(3, 1, 1), (3, 2, 2), (4, 2, 1)]
    assert observed["countries"] == [(3, 1, 1), (3, 2, 0), (4, 2, 1)]
    assert observed["paths"] == {"/authors", "/sitemap.xml"}
    assert "action=bulk_create target=authors:count=2" in caplog.text
    assert caplog.text.count("action=bulk_create") == 1


def test_author_bulk_rolls_back_all_when_later_entry_fails(
    admin_bulk_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = admin_bulk_client
    original = admin_bulk.write_author_relations
    calls = 0

    def fail_second(connection, author_id: int, data, now) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise IntegrityError("forced", {}, Exception("forced"))
        original(connection, author_id, data, now)

    monkeypatch.setattr(admin_bulk, "write_author_relations", fail_second)
    items = [
        _author_item(),
        _author_item(name="二人目", slug="second-author"),
    ]

    response = client.post("/admin/authors/bulk", data=_author_bulk_form(items))

    assert response.status_code == 422
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(authors)).scalar_one()
            == 2
        )
        assert (
            connection.execute(
                select(func.count()).select_from(author_professions)
            ).scalar_one()
            == 0
        )


def test_author_bulk_registration_revalidates_tampered_hidden_json(
    admin_bulk_client,
) -> None:
    client, engine = admin_bulk_client
    response = client.post(
        "/admin/authors/bulk",
        data=_author_bulk_form([_author_item(slug="existing-author")]),
    )

    assert response.status_code == 422
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(authors)).scalar_one()
            == 2
        )


def test_bulk_entry_points_are_linked(admin_bulk_client) -> None:
    client, _engine = admin_bulk_client

    assert "/admin/quotes/bulk" in client.get("/admin/quotes").text
    assert "/admin/authors/bulk" in client.get("/admin/authors").text
    dashboard = client.get("/admin").text
    assert "/admin/quotes/bulk" in dashboard
    assert "/admin/authors/bulk" in dashboard
