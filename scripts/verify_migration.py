"""Verify a migrated SQLite file against the JSON Lines dump it was built from.

Expected values are derived from the dump itself, never hard-coded (the source
keeps changing), except the quotes high-water floor of 3,197 (decision #14).
Instants are checked by parsing the SQLite text back and comparing it with the
source timestamp, independently of the loader's serializer.

Exit status is 0 only when every check passes.

Usage: uv run python scripts/verify_migration.py --source-dir DIR --database PATH
"""

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import Engine, text

from app.db import create_db_engine
from app.instants import INSTANT_LENGTH, parse_instant
from scripts.source_dump import (
    INSTANT_COLUMNS,
    QUOTES_SEQUENCE_FLOOR,
    TABLES,
    read_quotes_sequence,
    read_table,
)

SNAPSHOT_TABLES = ("quote_ranking_scores", "author_rankings", "category_rankings")
RELATIONS = (  # (table, column, referenced table) for the orphan check
    ("sources", "author_id", "authors"),
    ("characters", "source_id", "sources"),
    ("categories", "parent_id", "categories"),
    ("quotes", "author_id", "authors"),
    ("quotes", "source_id", "sources"),
    ("quotes", "character_id", "characters"),
    ("author_professions", "author_id", "authors"),
    ("author_professions", "profession_id", "professions"),
    ("author_country", "author_id", "authors"),
    ("author_country", "country_id", "countries"),
    ("source_type_assignments", "source_id", "sources"),
    ("source_type_assignments", "type_id", "source_types"),
    ("quote_categories", "quote_id", "quotes"),
    ("quote_categories", "category_id", "categories"),
    ("quote_likes", "quote_id", "quotes"),
)
TEXT_COLUMNS = (  # byte-for-byte comparison (mojibake check)
    ("quotes", "text"),
    ("quotes", "text_en"),
    ("quotes", "context_note"),
    ("authors", "name"),
    ("authors", "description"),
    ("sources", "title"),
    ("categories", "name"),
)


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {name}" + (f"  ({detail})" if detail else ""))
        if not ok:
            self.failures.append(name)


def key_of(row: dict, pk: tuple[str, ...]) -> tuple:
    return tuple(row[column] for column in pk)


def fetch(connection, sql: str, **params) -> list[dict]:
    return [dict(row) for row in connection.execute(text(sql), params).mappings()]


def verify(source_dir: Path, engine: Engine) -> Report:
    report = Report()
    source = {name: read_table(source_dir, name) for name in TABLES}
    with engine.connect() as connection:
        report.check(
            "PRAGMA integrity_check",
            connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok",
        )
        fk_violations = fetch(connection, "PRAGMA foreign_key_check")
        report.check(
            "PRAGMA foreign_key_check", not fk_violations, f"{len(fk_violations)} rows"
        )

        for name, pk in TABLES.items():
            db_rows = fetch(connection, f"SELECT * FROM {name}")
            src_rows = source[name]
            report.check(
                f"{name}: row count",
                len(db_rows) == len(src_rows),
                f"sqlite {len(db_rows)} / source {len(src_rows)}",
            )
            report.check(
                f"{name}: primary keys identical",
                {key_of(r, pk) for r in db_rows} == {key_of(r, pk) for r in src_rows},
            )
            db_by_key = {key_of(r, pk): r for r in db_rows}
            src_by_key = {key_of(r, pk): r for r in src_rows}
            for column in INSTANT_COLUMNS[name]:
                bad_format = sum(
                    1
                    for r in db_rows
                    if not isinstance(r[column], str)
                    or len(r[column]) != INSTANT_LENGTH
                )
                report.check(
                    f"{name}.{column}: fixed-length UTC format",
                    bad_format == 0,
                    f"{bad_format} malformed",
                )
                mismatches = 0
                for key, src in src_by_key.items():
                    db = db_by_key.get(key)
                    try:
                        if db is None or parse_instant(
                            db[column]
                        ) != datetime.fromisoformat(src[column]):
                            mismatches += 1
                    except ValueError:
                        mismatches += 1
                report.check(
                    f"{name}.{column}: round-trip equals source",
                    mismatches == 0,
                    f"{mismatches} mismatches",
                )
            if name == "categories":
                copied = all(r["updated_at"] == r["created_at"] for r in db_rows)
                report.check(
                    "categories.updated_at initialized from created_at", copied
                )

        for name in SNAPSHOT_TABLES:
            count = connection.execute(
                text(f"SELECT count(*) FROM {name}")
            ).scalar_one()
            report.check(f"{name}: empty snapshot table", count == 0, f"{count} rows")

        for table, column, ref in RELATIONS:
            orphans = connection.execute(
                text(
                    f"SELECT count(*) FROM {table} t WHERE t.{column} IS NOT NULL"
                    f" AND NOT EXISTS (SELECT 1 FROM {ref} r WHERE r.id = t.{column})"
                )
            ).scalar_one()
            report.check(
                f"{table}.{column}: no orphans", orphans == 0, f"{orphans} orphans"
            )

        # legacy votes -> quotes.legacy_vote_count
        legacy = Counter()
        for row in read_table(source_dir, "legacy_votes"):
            legacy[row["quote_id"]] += row["vote_count"]
        db_votes = {
            r["id"]: r["legacy_vote_count"]
            for r in fetch(connection, "SELECT id, legacy_vote_count FROM quotes")
        }
        report.check(
            "quotes.legacy_vote_count: total equals legacy_votes total",
            sum(db_votes.values()) == sum(legacy.values()),
            f"sqlite {sum(db_votes.values())} / source {sum(legacy.values())}",
        )
        report.check(
            "quotes.legacy_vote_count: per-quote values equal",
            all(db_votes.get(q, 0) == v for q, v in legacy.items())
            and all(v == 0 for q, v in db_votes.items() if q not in legacy),
        )

        # quotes high-water mark
        seq = connection.execute(
            text("SELECT seq FROM sqlite_sequence WHERE name = 'quotes'")
        ).scalar()
        max_id = max((r["id"] for r in source["quotes"]), default=0)
        expected_seq = max(
            max_id, read_quotes_sequence(source_dir), QUOTES_SEQUENCE_FLOOR
        )
        report.check(
            "quotes: sqlite_sequence >= max(id), source sequence, 3197",
            seq is not None and seq >= expected_seq,
            f"sqlite_sequence {seq} / expected >= {expected_seq}",
        )

        # text bytes and distributions
        for table, column in TEXT_COLUMNS:
            pk = TABLES[table]
            src_by_key = {key_of(r, pk): r for r in source[table]}
            diffs = 0
            for row in fetch(connection, f"SELECT * FROM {table}"):
                src_value = src_by_key[key_of(row, pk)][column]
                db_value = row[column]
                if (src_value is None) != (db_value is None) or (
                    src_value is not None and src_value.encode() != db_value.encode()
                ):
                    diffs += 1
            report.check(
                f"{table}.{column}: bytes identical", diffs == 0, f"{diffs} differ"
            )

        src_quotes = source["quotes"]
        db_quotes = fetch(connection, "SELECT id, enable, slug FROM quotes")
        report.check(
            "quotes.enable: distribution identical",
            Counter(int(r["enable"]) for r in src_quotes)
            == Counter(r["enable"] for r in db_quotes),
        )
        report.check(
            "quotes.slug: values identical",
            {(r["id"], r["slug"]) for r in src_quotes}
            == {(r["id"], r["slug"]) for r in db_quotes},
        )
        report.check(
            "quote_likes.is_valid: distribution identical",
            Counter(int(r["is_valid"]) for r in source["quote_likes"])
            == Counter(
                r["is_valid"]
                for r in fetch(connection, "SELECT is_valid FROM quote_likes")
            ),
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()

    engine = create_db_engine(f"sqlite:///{args.database}")
    try:
        report = verify(args.source_dir, engine)
    finally:
        engine.dispose()
    if report.failures:
        sys.exit(f"{len(report.failures)} check(s) failed")
    print("all checks passed")


if __name__ == "__main__":
    main()
