from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app import schema  # noqa: F401  (registers tables on metadata)
from app.db import create_db_engine, metadata

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TABLES = {
    "authors",
    "professions",
    "author_professions",
    "countries",
    "author_country",
    "source_types",
    "sources",
    "source_type_assignments",
    "characters",
    "categories",
    "quotes",
    "quote_categories",
    "quote_likes",
    "quote_ranking_scores",
    "author_rankings",
    "category_rankings",
}
NOW = "2026-08-20T00:00:00.000000Z"


def upgrade_to_head(database_path: Path) -> Engine:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    url = f"sqlite:///{database_path}"
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_db_engine(url)


@pytest.fixture
def engine(tmp_path: Path, monkeypatch) -> Engine:
    database_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    migrated = upgrade_to_head(database_path)
    yield migrated
    migrated.dispose()


def test_single_head() -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1


def test_upgrade_head_creates_all_tables_matching_metadata(engine: Engine) -> None:
    with engine.connect() as connection:
        names = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert EXPECTED_TABLES <= names
        assert "sqlite_sequence" in names  # quotes uses AUTOINCREMENT
        triggers = connection.execute(
            text("SELECT count(*) FROM sqlite_master WHERE type = 'trigger'")
        ).scalar_one()
        assert triggers == 5
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"

        # The migration history and app/schema.py must describe the same schema.
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "render_as_batch": True}
        )
        assert compare_metadata(context, metadata) == []


def _insert_category(connection, cid: int, level: int, parent_id: int | None) -> None:
    connection.execute(
        text(
            "INSERT INTO categories (id, name, slug, level, parent_id, created_at, updated_at)"
            " VALUES (:id, :name, :slug, :level, :parent_id, :now, :now)"
        ),
        {
            "id": cid,
            "name": f"c{cid}",
            "slug": f"c{cid}",
            "level": level,
            "parent_id": parent_id,
            "now": NOW,
        },
    )


def test_category_hierarchy_triggers(engine: Engine) -> None:
    with engine.begin() as connection:
        _insert_category(connection, 1, 1, None)
        _insert_category(connection, 2, 2, 1)

        with pytest.raises(IntegrityError, match="level 1"):
            _insert_category(connection, 3, 2, 2)  # parent is level 2
        with pytest.raises(IntegrityError, match="level 1"):
            _insert_category(connection, 3, 2, 999)  # parent missing
        with pytest.raises(IntegrityError, match="children"):
            connection.execute(
                text("UPDATE categories SET level = 2, parent_id = 2 WHERE id = 1")
            )
        with pytest.raises(IntegrityError):
            connection.execute(text("DELETE FROM categories WHERE id = 1"))  # RESTRICT


def test_quote_categories_require_level_two(engine: Engine) -> None:
    with engine.begin() as connection:
        _insert_category(connection, 1, 1, None)
        _insert_category(connection, 2, 2, 1)
        connection.execute(
            text(
                "INSERT INTO quotes (id, text, created_at, updated_at)"
                " VALUES (10, 'hello', :now, :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text("INSERT INTO quote_categories (quote_id, category_id) VALUES (10, 2)")
        )
        with pytest.raises(IntegrityError, match="level 2"):
            connection.execute(
                text(
                    "INSERT INTO quote_categories (quote_id, category_id) VALUES (10, 1)"
                )
            )
        with pytest.raises(IntegrityError, match="quote assignments"):
            connection.execute(text("UPDATE categories SET level = 1 WHERE id = 2"))


def test_birth_country_is_unique_per_author(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO authors (id, name, slug, created_at, updated_at)"
                " VALUES (1, 'a', 'a', :now, :now)"
            ),
            {"now": NOW},
        )
        for cid in (1, 2, 3):
            connection.execute(
                text(
                    "INSERT INTO countries (id, name, slug, created_at, updated_at)"
                    " VALUES (:id, :name, :slug, :now, :now)"
                ),
                {"id": cid, "name": f"n{cid}", "slug": f"s{cid}", "now": NOW},
            )
        insert = text(
            "INSERT INTO author_country (author_id, country_id, is_birth_country, created_at)"
            " VALUES (1, :country_id, :birth, :now)"
        )
        connection.execute(insert, {"country_id": 1, "birth": 1, "now": NOW})
        connection.execute(insert, {"country_id": 2, "birth": 0, "now": NOW})
        with pytest.raises(IntegrityError):
            connection.execute(insert, {"country_id": 3, "birth": 1, "now": NOW})


def test_quotes_autoincrement_does_not_reuse_deleted_ids(engine: Engine) -> None:
    with engine.begin() as connection:
        insert = text(
            "INSERT INTO quotes (text, created_at, updated_at) VALUES ('t', :now, :now)"
        )
        connection.execute(insert, {"now": NOW})
        connection.execute(text("DELETE FROM quotes"))
        connection.execute(insert, {"now": NOW})
        assert connection.execute(text("SELECT max(id) FROM quotes")).scalar_one() == 2


def test_author_date_checks(engine: Engine) -> None:
    insert = text(
        "INSERT INTO authors (id, name, slug, birth_date, birth_era, birth_precision,"
        " death_date, death_era, death_precision, created_at, updated_at)"
        " VALUES (:id, :id, :id, :bd, :be, :bp, :dd, :de, :dp, :now, :now)"
    )
    ok = [
        # Horace: 65 BC -> 8 BC, day precision, valid in BC order.
        {
            "bd": "0065-12-08",
            "be": "bc",
            "bp": "day",
            "dd": "0008-11-27",
            "de": "bc",
            "dp": "day",
        },
        {
            "bd": "0043-01-01",
            "be": "bc",
            "bp": "year",
            "dd": "0017-01-01",
            "de": "ad",
            "dp": "year",
        },
        {
            "bd": None,
            "be": "ad",
            "bp": "unknown",
            "dd": "0399-01-01",
            "de": "bc",
            "dp": "year",
        },
    ]
    bad = [
        {
            "bd": "1900-01-02",
            "be": "ad",
            "bp": "day",
            "dd": "1900-01-01",
            "de": "ad",
            "dp": "day",
        },
        {
            "bd": "0008-11-27",
            "be": "bc",
            "bp": "day",
            "dd": "0065-12-08",
            "de": "bc",
            "dp": "day",
        },
        {
            "bd": "1900-01-01",
            "be": "ad",
            "bp": "year",
            "dd": "0100-01-01",
            "de": "bc",
            "dp": "year",
        },
        {"bd": None, "be": "ad", "bp": "year", "dd": None, "de": "ad", "dp": "unknown"},
        {
            "bd": "1900-1-1",
            "be": "ad",
            "bp": "day",
            "dd": None,
            "de": "ad",
            "dp": "unknown",
        },
    ]
    with engine.begin() as connection:
        for i, row in enumerate(ok):
            connection.execute(insert, {"id": str(i), "now": NOW, **row})
        for i, row in enumerate(bad, start=100):
            with pytest.raises(IntegrityError):
                connection.execute(insert, {"id": str(i), "now": NOW, **row})
