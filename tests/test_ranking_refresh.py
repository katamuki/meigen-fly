from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, insert, select

from app.db import create_db_engine, metadata
from app.instants import format_instant
from app.schema import (
    author_rankings,
    authors,
    categories,
    category_rankings,
    quote_categories,
    quote_likes,
    quote_ranking_scores,
    quotes,
)
from app.services import ranking_refresh
from app.services.ranking_refresh import _quote_score, refresh_rankings

NOW = datetime(2026, 1, 8, 12, tzinfo=UTC)
INSTANT = format_instant(NOW - timedelta(days=30))


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    result = create_db_engine(f"sqlite:///{tmp_path / 'ranking.db'}")
    metadata.create_all(result)
    yield result
    result.dispose()


def _author(author_id: int) -> dict:
    return {
        "id": author_id,
        "name": f"author-{author_id}",
        "slug": f"author-{author_id}",
        "created_at": INSTANT,
        "updated_at": INSTANT,
    }


def _category(category_id: int, level: int, parent_id: int | None = None) -> dict:
    return {
        "id": category_id,
        "name": f"category-{category_id}",
        "slug": f"category-{category_id}",
        "level": level,
        "parent_id": parent_id,
        "created_at": INSTANT,
        "updated_at": INSTANT,
    }


def _quote(
    quote_id: int,
    author_id: int,
    *,
    weight: int = 1,
    enable: int = 1,
    legacy_votes: int = 0,
) -> dict:
    return {
        "id": quote_id,
        "text": f"quote-{quote_id}",
        "author_id": author_id,
        "weight": weight,
        "enable": enable,
        "legacy_vote_count": legacy_votes,
        "created_at": INSTANT,
        "updated_at": INSTANT,
    }


def _like(quote_id: int, number: int, created_at: datetime, valid: int = 1) -> dict:
    return {
        "quote_id": quote_id,
        "client_uuid": f"00000000-0000-4000-8000-{number:012d}",
        "created_at": format_instant(created_at),
        "is_valid": valid,
    }


def test_quote_score_treats_null_weight_as_zero() -> None:
    assert _quote_score(None, 4, 3, 1) == 21


def test_refresh_matches_manual_scores_and_public_aggregate_rules(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        connection.execute(insert(authors), [_author(1), _author(2)])
        connection.execute(
            insert(categories),
            [_category(10, 1), _category(11, 2, 10), _category(12, 2, 10)],
        )
        connection.execute(
            insert(quotes),
            [
                _quote(1, 1, weight=2, legacy_votes=3),
                _quote(2, 1, weight=10, enable=0),
                _quote(3, 2),
                _quote(4, 2),
            ],
        )
        connection.execute(
            insert(quote_likes),
            [
                _like(1, 1, NOW - timedelta(days=1)),
                _like(1, 2, NOW - timedelta(days=1, microseconds=1)),
                _like(1, 3, NOW - timedelta(days=7)),
                _like(1, 4, NOW - timedelta(days=7, microseconds=1)),
                _like(1, 5, NOW, valid=0),
            ],
        )
        connection.execute(
            insert(quote_categories),
            [
                {"quote_id": 1, "category_id": 11},
                {"quote_id": 2, "category_id": 11},
                {"quote_id": 3, "category_id": 12},
                {"quote_id": 4, "category_id": 12},
            ],
        )

    result = refresh_rankings(engine, now=NOW)

    assert (result.quote_count, result.author_count, result.category_count) == (4, 2, 2)
    with engine.connect() as connection:
        quote_rows = {
            row.quote_id: row
            for row in connection.execute(select(quote_ranking_scores))
        }
        assert quote_rows[1].likes_total == 7
        assert quote_rows[1].likes_7d == 3
        assert quote_rows[1].likes_1d == 1
        assert quote_rows[1].score_total == 44
        assert quote_rows[2].score_total == 100  # private quotes remain in this table
        assert all(
            row.likes_1d <= row.likes_7d <= row.likes_total
            for row in quote_rows.values()
        )

        author_rows = connection.execute(
            select(author_rankings).order_by(author_rankings.c.rank)
        ).all()
        assert [row.author_id for row in author_rows] == [1, 2]
        assert author_rows[0].total_score == 44
        assert author_rows[0].score == pytest.approx(0.2)
        assert author_rows[1].total_score == 20
        assert author_rows[1].score == pytest.approx(-0.2)

        category_rows = connection.execute(
            select(category_rankings).order_by(category_rankings.c.rank)
        ).all()
        assert [row.category_id for row in category_rows] == [11, 12]
        assert category_rows[0].score == pytest.approx(0.6)
        assert category_rows[1].score == pytest.approx(-0.6)
        assert 10 not in {row.category_id for row in category_rows}

        expected_refreshed_at = format_instant(NOW)
        assert {row.refreshed_at for row in quote_rows.values()} == {
            expected_refreshed_at
        }
        assert {row.refreshed_at for row in author_rows} == {expected_refreshed_at}
        assert {row.refreshed_at for row in category_rows} == {expected_refreshed_at}


def test_zero_standard_deviation_and_ties_use_id_order(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(insert(authors), [_author(1), _author(2)])
        connection.execute(
            insert(categories),
            [_category(10, 1), _category(11, 2, 10), _category(12, 2, 10)],
        )
        connection.execute(insert(quotes), [_quote(1, 1), _quote(2, 2)])
        connection.execute(
            insert(quote_categories),
            [
                {"quote_id": 1, "category_id": 11},
                {"quote_id": 2, "category_id": 12},
            ],
        )

    refresh_rankings(engine, now=NOW)

    with engine.connect() as connection:
        author_rows = connection.execute(
            select(author_rankings).order_by(author_rankings.c.rank)
        ).all()
        category_rows = connection.execute(
            select(category_rankings).order_by(category_rankings.c.rank)
        ).all()
    assert [(row.author_id, row.rank, row.score) for row in author_rows] == [
        (1, 1, 0),
        (2, 2, 0),
    ]
    assert [(row.category_id, row.rank, row.score) for row in category_rows] == [
        (11, 1, 0),
        (12, 2, 0),
    ]


def test_refresh_acquires_write_lock_before_reading(engine: Engine) -> None:
    statements = []

    def record_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        refresh_rankings(engine, now=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert statements[0] == "BEGIN IMMEDIATE"


def test_refresh_rolls_back_all_snapshots_on_replacement_failure(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = format_instant(NOW - timedelta(days=1))
    with engine.begin() as connection:
        connection.execute(insert(authors), _author(1))
        connection.execute(insert(categories), _category(1, 1))
        connection.execute(insert(quotes), _quote(1, 1))
        connection.execute(
            insert(quote_ranking_scores),
            {
                "quote_id": 1,
                "score_total": 999,
                "likes_total": 0,
                "likes_7d": 0,
                "likes_1d": 0,
                "refreshed_at": old,
            },
        )
        connection.execute(
            insert(author_rankings),
            {
                "author_id": 1,
                "rank": 1,
                "score": 999,
                "total_score": 999,
                "avg_score": 999,
                "quote_count": 1,
                "refreshed_at": old,
            },
        )
        connection.execute(
            insert(category_rankings),
            {
                "category_id": 1,
                "rank": 1,
                "score": 999,
                "total_score": 999,
                "avg_score": 999,
                "adjusted_score": 999,
                "quote_count": 1,
                "refreshed_at": old,
            },
        )

    def fail_during_replacement(connection, *_args) -> None:
        connection.execute(quote_ranking_scores.delete())
        connection.execute(author_rankings.delete())
        connection.execute(category_rankings.delete())
        raise RuntimeError("injected failure")

    monkeypatch.setattr(ranking_refresh, "_replace_snapshots", fail_during_replacement)
    with pytest.raises(RuntimeError, match="injected failure"):
        refresh_rankings(engine, now=NOW)

    with engine.connect() as connection:
        quote_row = connection.execute(select(quote_ranking_scores)).one()
        author_row = connection.execute(select(author_rankings)).one()
        category_row = connection.execute(select(category_rankings)).one()
    assert (quote_row.score_total, quote_row.refreshed_at) == (999, old)
    assert (author_row.score, author_row.refreshed_at) == (999, old)
    assert (category_row.score, category_row.refreshed_at) == (999, old)
