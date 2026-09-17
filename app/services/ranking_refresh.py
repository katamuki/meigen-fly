"""Rebuild all three ranking snapshots from their source tables."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import log10, sqrt
from statistics import fmean, pstdev
from time import perf_counter

from sqlalchemy import case, delete, distinct, func, insert, select
from sqlalchemy.engine import Connection, Engine

from app.instants import format_instant
from app.schema import (
    author_rankings,
    category_rankings,
    quote_categories,
    quote_likes,
    quote_ranking_scores,
    quotes,
)


@dataclass(frozen=True)
class RankingCoefficients:
    weight_factor: float = 10.0
    like_weight_default: float = 1.0
    like_weight_7d: float = 5.0
    like_weight_1d: float = 10.0


COEFFICIENTS = RankingCoefficients()


@dataclass(frozen=True)
class RankingRefreshResult:
    quote_count: int
    author_count: int
    category_count: int
    duration_seconds: float
    refreshed_at: datetime


def _quote_score(
    weight: int | None,
    likes_total: int,
    likes_7d: int,
    likes_1d: int,
) -> float:
    return (
        (weight or 0) * COEFFICIENTS.weight_factor
        + (likes_total - likes_7d) * COEFFICIENTS.like_weight_default
        + (likes_7d - likes_1d) * COEFFICIENTS.like_weight_7d
        + likes_1d * COEFFICIENTS.like_weight_1d
    )


def _z_values(values: list[float]) -> list[float]:
    if not values:
        return []
    deviation = pstdev(values)
    if deviation == 0:
        return [0.0] * len(values)
    mean = fmean(values)
    return [(value - mean) / deviation for value in values]


def _quote_rows(connection: Connection, now: datetime) -> list[dict]:
    cutoff_1d = format_instant(now - timedelta(days=1))
    cutoff_7d = format_instant(now - timedelta(days=7))
    valid = quote_likes.c.is_valid == 1
    rows = connection.execute(
        select(
            quotes.c.id.label("quote_id"),
            quotes.c.author_id,
            quotes.c.enable,
            quotes.c.weight,
            quotes.c.legacy_vote_count,
            func.sum(case((valid, 1), else_=0)).label("valid_likes"),
            func.sum(
                case((valid & (quote_likes.c.created_at >= cutoff_7d), 1), else_=0)
            ).label("likes_7d"),
            func.sum(
                case((valid & (quote_likes.c.created_at >= cutoff_1d), 1), else_=0)
            ).label("likes_1d"),
        )
        .select_from(
            quotes.outerjoin(quote_likes, quote_likes.c.quote_id == quotes.c.id)
        )
        .group_by(quotes.c.id)
        .order_by(quotes.c.id)
    ).mappings()

    result = []
    for row in rows:
        likes_total = row["legacy_vote_count"] + row["valid_likes"]
        score_total = _quote_score(
            row["weight"], likes_total, row["likes_7d"], row["likes_1d"]
        )
        result.append(
            {
                **dict(row),
                "likes_total": likes_total,
                "score_total": score_total,
            }
        )
    return result


def _ranked_aggregates(aggregates: list[dict], *, category: bool = False) -> list[dict]:
    totals = [row["total_score"] for row in aggregates]
    averages = [row["avg_score"] for row in aggregates]
    quote_logs = [log10(1 + row["quote_count"]) for row in aggregates]
    total_z = _z_values(totals)
    count_z = _z_values(quote_logs)
    average_z = _z_values(averages) if category else []

    scored = []
    for index, row in enumerate(aggregates):
        score = (
            0.5 * total_z[index] + 0.3 * average_z[index] + 0.2 * count_z[index]
            if category
            else 0.6 * total_z[index] + 0.4 * count_z[index]
        )
        scored.append({**row, "score": score})
    id_key = "category_id" if category else "author_id"
    scored.sort(key=lambda row: (-row["score"], row[id_key]))
    for rank, row in enumerate(scored, 1):
        row["rank"] = rank
    return scored


def _author_rows(quote_rows: list[dict]) -> list[dict]:
    scores: dict[int, list[float]] = {}
    for row in quote_rows:
        if row["enable"] == 1 and row["author_id"] is not None:
            scores.setdefault(row["author_id"], []).append(row["score_total"])
    aggregates = [
        {
            "author_id": author_id,
            "quote_count": len(values),
            "total_score": sum(values),
            "avg_score": fmean(values),
        }
        for author_id, values in scores.items()
    ]
    return _ranked_aggregates(aggregates)


def _category_rows(connection: Connection, quote_rows: list[dict]) -> list[dict]:
    score_by_quote = {
        row["quote_id"]: row["score_total"] for row in quote_rows if row["enable"] == 1
    }
    if not score_by_quote:
        return []
    assignments = connection.execute(
        select(
            distinct(quote_categories.c.quote_id).label("quote_id"),
            quote_categories.c.category_id,
        ).where(quote_categories.c.quote_id.in_(score_by_quote))
    )
    scores: dict[int, list[float]] = {}
    for assignment in assignments:
        scores.setdefault(assignment.category_id, []).append(
            score_by_quote[assignment.quote_id]
        )
    aggregates = []
    for category_id, values in scores.items():
        total = sum(values)
        average = fmean(values)
        aggregates.append(
            {
                "category_id": category_id,
                "quote_count": len(values),
                "total_score": total,
                "avg_score": average,
                "adjusted_score": total * sqrt(max(average, 0)),
            }
        )
    return _ranked_aggregates(aggregates, category=True)


def _replace_snapshots(
    connection: Connection,
    quote_rows: list[dict],
    author_rows: list[dict],
    category_rows: list[dict],
    refreshed_at: str,
) -> None:
    connection.execute(delete(category_rankings))
    connection.execute(delete(author_rankings))
    connection.execute(delete(quote_ranking_scores))
    if quote_rows:
        connection.execute(
            insert(quote_ranking_scores),
            [
                {
                    "quote_id": row["quote_id"],
                    "score_total": row["score_total"],
                    "likes_total": row["likes_total"],
                    "likes_7d": row["likes_7d"],
                    "likes_1d": row["likes_1d"],
                    "refreshed_at": refreshed_at,
                }
                for row in quote_rows
            ],
        )
    if author_rows:
        connection.execute(
            insert(author_rankings),
            [{**row, "refreshed_at": refreshed_at} for row in author_rows],
        )
    if category_rows:
        connection.execute(
            insert(category_rankings),
            [{**row, "refreshed_at": refreshed_at} for row in category_rows],
        )


def refresh_rankings(engine: Engine, *, now: datetime) -> RankingRefreshResult:
    """Atomically replace all ranking snapshots at one fixed reference time."""
    refreshed_at = format_instant(now)
    started = perf_counter()
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            quote_rows = _quote_rows(connection, now)
            author_rows = _author_rows(quote_rows)
            category_rows = _category_rows(connection, quote_rows)
            _replace_snapshots(
                connection,
                quote_rows,
                author_rows,
                category_rows,
                refreshed_at,
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    return RankingRefreshResult(
        quote_count=len(quote_rows),
        author_count=len(author_rows),
        category_count=len(category_rows),
        duration_seconds=perf_counter() - started,
        refreshed_at=now,
    )
