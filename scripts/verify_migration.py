"""Verify a migrated SQLite file against the JSON Lines dump it was built from.

Expected values are derived from the dump itself, never hard-coded (the source
keeps changing), except the quotes high-water floor of 3,197 (decision #14).
Every row of the 13 tables is compared column by column with the source row of
the same primary key. Converted columns get their expected value from this
script's own, deliberately separate, rules (instants are parsed back and
compared with the source timestamp instead of re-serialized).

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
    BOOLEAN_COLUMNS,
    DATE_COLUMNS,
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


def expected_values(table: str, src: dict, legacy: Counter) -> dict:
    """Expected SQLite values for the non-instant columns of one source row."""
    date_columns = {column for column, _ in DATE_COLUMNS.get(table, ())}
    expected = {}
    for column, value in src.items():
        if column in INSTANT_COLUMNS[table]:
            continue  # compared by parsing, see expected_instants
        if column in BOOLEAN_COLUMNS.get(table, ()):
            expected[column] = int(value)
        elif column in date_columns:
            expected[column] = None if value is None else value.removesuffix(" BC")
        else:
            expected[column] = value
    if table == "quotes":
        expected["legacy_vote_count"] = legacy.get(src["id"], 0)
    return expected


def expected_instants(table: str, src: dict) -> dict[str, datetime]:
    """Expected aware datetimes for the instant columns of one source row."""
    expected = {
        column: datetime.fromisoformat(src[column]) for column in INSTANT_COLUMNS[table]
    }
    if table == "categories":
        expected["updated_at"] = expected["created_at"]  # new column, decision #15
    return expected


def instant_matches(db_value: object, expected: datetime) -> bool:
    if not isinstance(db_value, str) or len(db_value) != INSTANT_LENGTH:
        return False
    try:
        return parse_instant(db_value) == expected
    except ValueError:
        return False


def compare_table(
    connection, report: Report, table: str, src_rows: list[dict], legacy: Counter
):
    pk = TABLES[table]
    result = connection.execute(text(f"SELECT * FROM {table}"))
    db_columns = set(result.keys())
    db_rows = [dict(row) for row in result.mappings()]
    if src_rows:
        # Every SQLite column must be covered by a source-derived expectation,
        # otherwise a dropped dump column would pass on server defaults.
        sample = src_rows[0]
        expected_columns = set(expected_values(table, sample, legacy)) | set(
            expected_instants(table, sample)
        )
        report.check(
            f"{table}: column set equals schema",
            expected_columns == db_columns,
            f"missing {sorted(db_columns - expected_columns)},"
            f" unexpected {sorted(expected_columns - db_columns)}",
        )
    report.check(
        f"{table}: row count",
        len(db_rows) == len(src_rows),
        f"sqlite {len(db_rows)} / source {len(src_rows)}",
    )
    db_by_key = {key_of(r, pk): r for r in db_rows}
    src_by_key = {key_of(r, pk): r for r in src_rows}
    report.check(
        f"{table}: primary keys identical", db_by_key.keys() == src_by_key.keys()
    )

    value_mismatches: Counter = Counter()
    instant_mismatches: Counter = Counter()
    for key, src in src_by_key.items():
        db = db_by_key.get(key)
        if db is None:
            continue  # already reported above
        for column, value in expected_values(table, src, legacy).items():
            if db.get(column) != value:
                value_mismatches[column] += 1
        for column, value in expected_instants(table, src).items():
            if not instant_matches(db.get(column), value):
                instant_mismatches[column] += 1
    report.check(
        f"{table}: column values equal source",
        not value_mismatches,
        ", ".join(f"{c}: {n}" for c, n in value_mismatches.items())
        or f"{len(db_rows)} rows",
    )
    if INSTANT_COLUMNS[table]:
        report.check(
            f"{table}: instants are fixed-length UTC and round-trip to source",
            not instant_mismatches,
            ", ".join(f"{c}: {n}" for c, n in instant_mismatches.items())
            or "0 mismatches",
        )


def verify(source_dir: Path, engine: Engine) -> Report:
    report = Report()
    source = {name: read_table(source_dir, name) for name in TABLES}
    legacy: Counter = Counter()
    for row in read_table(source_dir, "legacy_votes"):
        legacy[row["quote_id"]] += row["vote_count"]

    with engine.connect() as connection:
        report.check(
            "PRAGMA integrity_check",
            connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok",
        )
        fk_violations = fetch(connection, "PRAGMA foreign_key_check")
        report.check(
            "PRAGMA foreign_key_check", not fk_violations, f"{len(fk_violations)} rows"
        )

        for table in TABLES:
            compare_table(connection, report, table, source[table], legacy)

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

        db_total = connection.execute(
            text("SELECT coalesce(sum(legacy_vote_count), 0) FROM quotes")
        ).scalar_one()
        report.check(
            "quotes.legacy_vote_count: total equals legacy_votes total",
            db_total == sum(legacy.values()),
            f"sqlite {db_total} / source {sum(legacy.values())}",
        )

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
