#!/usr/bin/env bash
# Build a fresh SQLite database from the exported JSON Lines dump and verify it.
#
# Steps: remove the target file -> alembic upgrade head -> load -> verify.
# Re-running always starts from an empty file, so the same command is used for
# local rehearsals and for the final cut-over migration.
#
# Usage: scripts/rebuild_sqlite.sh [SOURCE_DIR] [DB_PATH]
#   SOURCE_DIR defaults to ~/prj/meigen-fly-private/source-db/data
#   DB_PATH    defaults to data/app.db
set -euo pipefail
cd "$(dirname "$0")/.."

SOURCE_DIR="${1:-$HOME/prj/meigen-fly-private/source-db/data}"
DB_PATH="${2:-data/app.db}"

rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
DATABASE_URL="sqlite:///$DB_PATH" uv run alembic upgrade head
uv run python scripts/load_source_data.py --source-dir "$SOURCE_DIR" --database "$DB_PATH"
uv run python scripts/verify_migration.py --source-dir "$SOURCE_DIR" --database "$DB_PATH"
