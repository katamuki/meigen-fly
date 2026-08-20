"""Transform the JSON Lines dump and load it into an empty, migrated SQLite file.

Conversion rules (docs/database/migration-runbook.md §4):
- instants: timestamptz -> 27-char fixed-length UTC TEXT (ADR 011)
- booleans: true/false -> 1/0
- historical dates: "YYYY-MM-DD[ BC]" -> "YYYY-MM-DD"; the BC suffix must agree
  with the separate era column, otherwise loading stops
- categories.updated_at: new column, initialized from created_at (decision #15)
- quotes.legacy_vote_count: sum of legacy_votes per quote, 0 when absent (#3)
- quote_likes: only quote_id/client_uuid/created_at/is_valid are loaded (#4/#5)
- countries.code and every other value: copied unchanged (#13)
- quotes high-water mark: sqlite_sequence >= max(id), old sequence value, 3197 (#14)

Nothing is silently corrected: any value the new constraints reject aborts
the whole load and leaves the database empty.

Usage: uv run python scripts/load_source_data.py --source-dir DIR --database PATH
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, insert, literal, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app import schema  # noqa: F401  (registers tables on metadata)
from app.db import create_db_engine, metadata
from app.instants import format_instant
from scripts.source_dump import (
    BOOLEAN_COLUMNS,
    DATE_COLUMNS,
    INSTANT_COLUMNS,
    QUOTES_SEQUENCE_FLOOR,
    TABLES,
    read_quotes_sequence,
    read_table,
)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LoadError(Exception):
    pass


def convert_instant(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise LoadError(f"timestamp without offset: {value!r}")
    return format_instant(parsed)


def convert_date(value: str | None, era: str) -> str | None:
    if value is None:
        return None
    date, _, suffix = value.partition(" ")
    expected_era = "bc" if suffix == "BC" else "ad"
    if suffix not in ("", "BC") or not DATE_PATTERN.match(date):
        raise LoadError(f"unsupported date value: {value!r}")
    if era != expected_era:
        raise LoadError(f"date {value!r} does not match era {era!r}")
    return date


def convert_row(table: str, row: dict) -> dict:
    converted = dict(row)
    for column in INSTANT_COLUMNS[table]:
        converted[column] = convert_instant(row[column])
    for column in BOOLEAN_COLUMNS.get(table, ()):
        if not isinstance(row[column], bool):
            raise LoadError(f"{table}.{column} is not boolean: {row[column]!r}")
        converted[column] = int(row[column])
    for column, era_column in DATE_COLUMNS.get(table, ()):
        converted[column] = convert_date(row[column], row[era_column])
    if table == "categories":
        converted["updated_at"] = converted["created_at"]
    return converted


def legacy_vote_counts(source_dir: Path, quote_ids: set[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for row in read_table(source_dir, "legacy_votes"):
        quote_id, votes = row["quote_id"], row["vote_count"]
        if quote_id not in quote_ids:
            raise LoadError(f"legacy_votes references unknown quote {quote_id}")
        if not isinstance(votes, int) or votes < 0:
            raise LoadError(f"legacy_votes has invalid vote_count for quote {quote_id}")
        counts[quote_id] = counts.get(quote_id, 0) + votes
    return counts


def expected_revision() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise LoadError(f"expected one migration head, found {heads}")
    return heads[0]


def check_target_is_empty_and_current(connection: Connection) -> None:
    head = expected_revision()
    try:
        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    except Exception as error:  # table missing -> not migrated
        raise LoadError("target database has no alembic_version table") from error
    if version != head:
        raise LoadError(f"target database is at revision {version}, expected {head}")
    for table in metadata.sorted_tables:
        count = connection.execute(
            text(f"SELECT count(*) FROM {table.name}")
        ).scalar_one()
        if count:
            raise LoadError(f"target table {table.name} is not empty ({count} rows)")


def set_quotes_sequence(connection: Connection, source_dir: Path) -> int:
    max_id = connection.execute(
        text("SELECT coalesce(max(id), 0) FROM quotes")
    ).scalar_one()
    target = max(max_id, read_quotes_sequence(source_dir), QUOTES_SEQUENCE_FLOOR)
    current = connection.execute(
        text("SELECT seq FROM sqlite_sequence WHERE name = 'quotes'")
    ).scalar()
    if current is None:
        connection.execute(
            text("INSERT INTO sqlite_sequence (name, seq) VALUES ('quotes', :seq)"),
            {"seq": target},
        )
    elif current < target:
        connection.execute(
            text("UPDATE sqlite_sequence SET seq = :seq WHERE name = 'quotes'"),
            {"seq": target},
        )
    return target


def insert_rows(connection: Connection, table_name: str, rows: list[dict]) -> None:
    """Bulk insert; when the database rejects it, name the first bad row."""
    table = metadata.tables[table_name]
    if any(row.keys() != rows[0].keys() for row in rows):
        raise LoadError(f"{table_name}: rows do not share the same columns")
    try:
        connection.execute(insert(table), rows)
    except IntegrityError as error:
        raise LoadError(
            describe_rejected_row(connection, table_name, rows, error)
        ) from error


def describe_rejected_row(
    connection: Connection, table_name: str, rows: list[dict], error: IntegrityError
) -> str:
    """Retry row by row to find the first row the constraints reject.

    The caller rolls the whole transaction back afterwards, so the extra
    inserts made here never persist. Rows the bulk insert already stored are
    skipped. (SAVEPOINTs are avoided on purpose: pysqlite's legacy transaction
    handling can commit them implicitly.)
    """
    table = metadata.tables[table_name]
    pk = TABLES[table_name]
    for row in rows:
        key = {column: row[column] for column in pk}
        already_stored = connection.execute(
            select(literal(1)).where(
                *[table.c[column] == value for column, value in key.items()]
            )
        ).first()
        if already_stored:
            continue
        try:
            connection.execute(insert(table), [row])
        except IntegrityError as row_error:
            return f"{table_name}: row {key} rejected: {row_error.orig}"
    return f"{table_name}: bulk insert rejected: {error.orig}"


def load(source_dir: Path, engine: Engine) -> dict[str, int]:
    """Load every table inside one transaction; return row counts per table."""
    counts: dict[str, int] = {}
    with engine.begin() as connection:
        check_target_is_empty_and_current(connection)
        for table_name in TABLES:
            rows = [
                convert_row(table_name, row)
                for row in read_table(source_dir, table_name)
            ]
            if table_name == "categories":
                rows.sort(key=lambda row: (row["level"], row["id"]))  # parents first
            if table_name == "quotes":
                votes = legacy_vote_counts(source_dir, {row["id"] for row in rows})
                for row in rows:
                    row["legacy_vote_count"] = votes.get(row["id"], 0)
            if rows:
                insert_rows(connection, table_name, rows)
            counts[table_name] = len(rows)
        counts["quotes_sequence"] = set_quotes_sequence(connection, source_dir)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()

    engine = create_db_engine(f"sqlite:///{args.database}")
    try:
        counts = load(args.source_dir, engine)
    except LoadError as error:
        sys.exit(f"load aborted: {error}")
    finally:
        engine.dispose()
    for name, count in counts.items():
        print(f"{count:8d}  {name}")


if __name__ == "__main__":
    main()
