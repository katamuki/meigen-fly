"""End-to-end test of scripts/load_source_data.py and scripts/verify_migration.py
on a tiny synthetic dump shaped like the output of scripts/export_source_db.sh."""

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from scripts import load_source_data, verify_migration
from tests.test_migrations import upgrade_to_head

T1 = "2025-07-04T12:14:33+00:00"  # no fractional seconds
T2 = "2026-01-12T02:40:15.881074+00:00"
T3 = "2026-02-08T11:59:07.5+09:00"  # non-UTC offset

DUMP = {
    "export_meta": [{"exported_at": T2, "time_zone": "UTC"}],
    "countries": [
        {"id": 1, "name": "日本", "name_en": None, "code": "JPN", "slug": "japan",
         "created_at": T1, "updated_at": T2},
        {"id": 2, "name": "ギリシャ", "name_en": "Greece", "code": None, "slug": "greece",
         "created_at": T1, "updated_at": T1},
    ],
    "professions": [
        {"id": 5, "name": "詩人", "slug": "poet", "description": None, "display_order": 0,
         "created_at": T1, "updated_at": T1},
    ],
    "source_types": [
        {"id": 3, "slug": "book", "name": "書籍", "display_order": 1, "description": None,
         "created_at": T1, "updated_at": T1},
    ],
    "authors": [
        {"id": 1479, "name": "ホラティウス", "slug": "horatius", "description": "詩人",
         "image_url": None, "name_kana": None, "name_foreign": "Horatius",
         "name_reading": "ほらてぃうす", "birth_date": "0065-12-08 BC", "birth_era": "bc",
         "birth_precision": "day", "death_date": "0008-11-27 BC", "death_era": "bc",
         "death_precision": "day", "created_at": T1, "updated_at": T2},
        {"id": 2232, "name": "無名", "slug": "anon", "description": None, "image_url": None,
         "name_kana": None, "name_foreign": None, "name_reading": None, "birth_date": None,
         "birth_era": "ad", "birth_precision": "unknown", "death_date": "1900-01-01",
         "death_era": "ad", "death_precision": "year", "created_at": T3, "updated_at": T3},
    ],
    "sources": [
        {"id": 7, "title": "歌集", "slug": "odes", "author_id": 1479, "published_year": None,
         "description": None, "created_at": T1, "updated_at": T1},
    ],
    "characters": [
        {"id": 9, "name": "語り手", "slug": "narrator", "source_id": 7, "description": None,
         "character_type": "narrator", "created_at": T1, "updated_at": T1},
    ],
    "categories": [
        # child listed before parent on purpose: the loader must order by level
        {"id": 200, "name": "愛", "slug": "love", "description": None, "sort_order": 1,
         "level": 2, "parent_id": 100, "color": None, "created_at": T2},
        {"id": 100, "name": "人生", "slug": "life", "description": "d", "sort_order": 0,
         "level": 1, "parent_id": None, "color": None, "created_at": T2},
    ],
    "quotes": [
        {"id": 1, "text": "今を摘め", "text_en": "Carpe diem", "author_id": 1479,
         "source_id": 7, "character_id": 9, "weight": 5, "slug": "carpe-diem",
         "enable": True, "context_note": None, "display_language_preference": "ja",
         "created_at": T1, "updated_at": T2},
        {"id": 3000, "text": "非公開", "text_en": None, "author_id": None, "source_id": None,
         "character_id": None, "weight": 1, "slug": None, "enable": False,
         "context_note": "note", "display_language_preference": "en",
         "created_at": T3, "updated_at": T3},
    ],
    "author_professions": [
        {"author_id": 1479, "profession_id": 5, "display_order": 1, "created_at": T1},
    ],
    "author_country": [
        {"author_id": 1479, "country_id": 2, "is_birth_country": True, "created_at": T1},
        {"author_id": 1479, "country_id": 1, "is_birth_country": False, "created_at": T1},
    ],
    "source_type_assignments": [
        {"source_id": 7, "type_id": 3, "created_at": T1},
    ],
    "quote_categories": [
        {"quote_id": 1, "category_id": 200},
    ],
    "quote_likes": [
        {"quote_id": 1, "client_uuid": "9b50bfd3-264f-4d6d-a127-47ea8b51341c",
         "created_at": T2, "is_valid": True},
        {"quote_id": 1, "client_uuid": "00000000-0000-4000-8000-000000000000",
         "created_at": T3, "is_valid": False},
    ],
    "legacy_votes": [
        {"quote_id": 1, "vote_count": 574},
    ],
    "quotes_sequence": [{"last_value": 3197, "is_called": True}],
}  # fmt: skip


def write_dump(directory: Path, dump: dict) -> Path:
    for name, rows in dump.items():
        with (directory / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return directory


@pytest.fixture
def migrated_db(tmp_path: Path, monkeypatch) -> Path:
    database_path = tmp_path / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    upgrade_to_head(database_path).dispose()
    return database_path


def test_load_then_verify_passes(tmp_path: Path, migrated_db: Path) -> None:
    (tmp_path / "dump").mkdir()
    source_dir = write_dump(tmp_path / "dump", DUMP)
    engine = load_source_data.create_db_engine(f"sqlite:///{migrated_db}")
    try:
        counts = load_source_data.load(source_dir, engine)
        assert counts["quotes"] == 2
        assert counts["quotes_sequence"] == 3197

        with engine.connect() as connection:
            horace = connection.execute(
                text(
                    "SELECT birth_date, birth_era, death_date FROM authors WHERE id = 1479"
                )
            ).one()
            assert tuple(horace) == ("0065-12-08", "bc", "0008-11-27")
            anon = connection.execute(
                text("SELECT created_at FROM authors WHERE id = 2232")
            ).scalar_one()
            assert anon == "2026-02-08T02:59:07.500000Z"  # +09:00 converted to UTC
            quote = connection.execute(
                text(
                    "SELECT enable, legacy_vote_count, created_at FROM quotes WHERE id = 1"
                )
            ).one()
            assert tuple(quote) == (1, 574, "2025-07-04T12:14:33.000000Z")
            category = connection.execute(
                text("SELECT created_at, updated_at FROM categories WHERE id = 200")
            ).one()
            assert category[0] == category[1] == "2026-01-12T02:40:15.881074Z"
            assert connection.execute(
                text("SELECT is_valid FROM quote_likes ORDER BY is_valid")
            ).scalars().all() == [0, 1]

        report = verify_migration.verify(source_dir, engine)
        assert report.failures == []
    finally:
        engine.dispose()


def test_load_refuses_non_empty_target(tmp_path: Path, migrated_db: Path) -> None:
    (tmp_path / "dump").mkdir()
    source_dir = write_dump(tmp_path / "dump", DUMP)
    engine = load_source_data.create_db_engine(f"sqlite:///{migrated_db}")
    try:
        load_source_data.load(source_dir, engine)
        with pytest.raises(load_source_data.LoadError, match="not empty"):
            load_source_data.load(source_dir, engine)
    finally:
        engine.dispose()


def test_load_aborts_on_inconsistent_data(tmp_path: Path, migrated_db: Path) -> None:
    (tmp_path / "dump").mkdir()
    dump = json.loads(json.dumps(DUMP))
    dump["legacy_votes"].append({"quote_id": 999, "vote_count": 1})  # unknown quote
    source_dir = write_dump(tmp_path / "dump", dump)
    engine = load_source_data.create_db_engine(f"sqlite:///{migrated_db}")
    try:
        with pytest.raises(load_source_data.LoadError, match="unknown quote 999"):
            load_source_data.load(source_dir, engine)
        with engine.connect() as connection:  # whole load rolled back
            assert (
                connection.execute(text("SELECT count(*) FROM authors")).scalar_one()
                == 0
            )
    finally:
        engine.dispose()


def test_date_era_mismatch_is_rejected() -> None:
    with pytest.raises(load_source_data.LoadError, match="does not match era"):
        load_source_data.convert_date("0065-12-08 BC", "ad")
    with pytest.raises(load_source_data.LoadError, match="unsupported"):
        load_source_data.convert_date("65-12-08", "ad")
    assert load_source_data.convert_date("1900-01-01", "ad") == "1900-01-01"


def test_verify_detects_a_tampered_row(tmp_path: Path, migrated_db: Path) -> None:
    (tmp_path / "dump").mkdir()
    source_dir = write_dump(tmp_path / "dump", DUMP)
    engine = load_source_data.create_db_engine(f"sqlite:///{migrated_db}")
    try:
        load_source_data.load(source_dir, engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE quotes SET text = 'changed', legacy_vote_count = 0 WHERE id = 1"
                )
            )
        report = verify_migration.verify(source_dir, engine)
        assert "quotes.text: bytes identical" in report.failures
        assert (
            "quotes.legacy_vote_count: total equals legacy_votes total"
            in report.failures
        )
    finally:
        engine.dispose()
