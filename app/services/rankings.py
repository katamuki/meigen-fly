"""Read-only access to the three current ranking snapshots."""

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.schema import author_rankings, authors, categories, category_rankings

RANKING_LIMIT = 20


def list_author_rankings(
    connection: Connection, limit: int = RANKING_LIMIT
) -> list[dict]:
    rows = connection.execute(
        select(
            authors.c.id,
            authors.c.name,
            authors.c.slug,
            author_rankings.c.score,
            author_rankings.c.quote_count,
        )
        .select_from(
            author_rankings.join(authors, authors.c.id == author_rankings.c.author_id)
        )
        .order_by(author_rankings.c.score.desc(), authors.c.id)
        .limit(limit)
    ).mappings()
    return [dict(row) for row in rows]


def list_category_rankings(
    connection: Connection, limit: int = RANKING_LIMIT
) -> list[dict]:
    rows = connection.execute(
        select(
            categories.c.id,
            categories.c.name,
            categories.c.slug,
            category_rankings.c.score,
            category_rankings.c.quote_count,
        )
        .select_from(
            category_rankings.join(
                categories, categories.c.id == category_rankings.c.category_id
            )
        )
        .order_by(category_rankings.c.score.desc(), categories.c.id)
        .limit(limit)
    ).mappings()
    return [dict(row) for row in rows]
