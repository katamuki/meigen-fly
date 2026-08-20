"""Shared description of the JSON Lines dump written by export_source_db.sh."""

import json
from pathlib import Path

# Source table -> primary key columns, in the order rows must be loaded
# (parents before children). These 13 tables plus legacy_votes are the
# migration scope; the three ranking snapshot tables stay empty (phase 4).
TABLES: dict[str, tuple[str, ...]] = {
    "countries": ("id",),
    "professions": ("id",),
    "source_types": ("id",),
    "authors": ("id",),
    "sources": ("id",),
    "characters": ("id",),
    "categories": ("id",),
    "quotes": ("id",),
    "author_professions": ("author_id", "profession_id"),
    "author_country": ("author_id", "country_id"),
    "source_type_assignments": ("source_id", "type_id"),
    "quote_categories": ("quote_id", "category_id"),
    "quote_likes": ("quote_id", "client_uuid"),
}

# Columns holding an instant (timestamptz in the source, fixed-length UTC TEXT
# in SQLite). categories.updated_at is new and initialized from created_at.
INSTANT_COLUMNS: dict[str, tuple[str, ...]] = {
    "countries": ("created_at", "updated_at"),
    "professions": ("created_at", "updated_at"),
    "source_types": ("created_at", "updated_at"),
    "authors": ("created_at", "updated_at"),
    "sources": ("created_at", "updated_at"),
    "characters": ("created_at", "updated_at"),
    "categories": ("created_at",),
    "quotes": ("created_at", "updated_at"),
    "author_professions": ("created_at",),
    "author_country": ("created_at",),
    "source_type_assignments": ("created_at",),
    "quote_categories": (),
    "quote_likes": ("created_at",),
}

BOOLEAN_COLUMNS: dict[str, tuple[str, ...]] = {
    "quotes": ("enable",),
    "author_country": ("is_birth_country",),
    "quote_likes": ("is_valid",),
}

# Historical calendar dates: source `date` (possibly "YYYY-MM-DD BC") plus a
# separate era column; stored as "YYYY-MM-DD" TEXT with the era kept as is.
DATE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "authors": (("birth_date", "birth_era"), ("death_date", "death_era")),
}

QUOTES_SEQUENCE_FLOOR = 3197  # high-water mark confirmed on 2026-07-17 (decision #14)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_table(source_dir: Path, name: str) -> list[dict]:
    return read_jsonl(source_dir / f"{name}.jsonl")


def read_quotes_sequence(source_dir: Path) -> int:
    rows = read_jsonl(source_dir / "quotes_sequence.jsonl")
    if len(rows) != 1:
        raise ValueError("quotes_sequence.jsonl must contain exactly one row")
    return int(rows[0]["last_value"])
