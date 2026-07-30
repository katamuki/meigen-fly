from pathlib import Path

from sqlalchemy import text

from app.db import create_db_engine


def test_sqlite_connection_uses_required_pragmas(tmp_path: Path) -> None:
    database_path = tmp_path / "test.db"
    engine = create_db_engine(f"sqlite:///{database_path}")

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
        assert connection.execute(text("PRAGMA synchronous")).scalar_one() == 1
        assert connection.execute(text("PRAGMA cache_size")).scalar_one() == -64000
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000

    engine.dispose()
