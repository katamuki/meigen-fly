"""Public quote queries and URL helpers."""

import re
from collections.abc import Iterable, Mapping
from math import ceil

from sqlalchemy import Select, func, literal, or_, select
from sqlalchemy.engine import Connection

from app.instants import parse_instant
from app.presentation import resolve_quote_display
from app.schema import (
    author_country,
    author_professions,
    authors,
    categories,
    characters,
    countries,
    professions,
    quote_categories,
    quote_likes,
    quote_ranking_scores,
    quotes,
    sources,
)

QUOTES_PER_PAGE = 20
SQLITE_MAX_INTEGER = 2**63 - 1
_QID_PATTERN = re.compile(r"q([1-9][0-9]*)\Z")


def parse_qid(identifier: str) -> int | None:
    """Return the positive quote ID only for a strict lowercase qid."""
    match = _QID_PATTERN.fullmatch(identifier)
    if match is None:
        return None
    try:
        quote_id = int(match.group(1))
    except ValueError:
        return None
    return quote_id if quote_id <= SQLITE_MAX_INTEGER else None


def quote_path(quote: Mapping[str, object]) -> str:
    slug = quote.get("slug")
    return f"/quotes/{slug}" if slug else f"/quotes/q{quote['id']}"


def _public_conditions(
    *,
    author_id: int | None = None,
    category_id: int | None = None,
    profession_id: int | None = None,
) -> list:
    conditions = [quotes.c.enable == 1]
    if author_id is not None:
        conditions.append(quotes.c.author_id == author_id)
    if category_id is not None:
        assigned = categories.alias("assigned_category")
        category_match = (
            select(literal(1))
            .select_from(
                quote_categories.join(
                    assigned, assigned.c.id == quote_categories.c.category_id
                )
            )
            .where(
                quote_categories.c.quote_id == quotes.c.id,
                or_(
                    quote_categories.c.category_id == category_id,
                    assigned.c.parent_id == category_id,
                ),
            )
            .exists()
        )
        conditions.append(category_match)
    if profession_id is not None:
        profession_match = (
            select(literal(1))
            .select_from(author_professions)
            .where(
                author_professions.c.author_id == quotes.c.author_id,
                author_professions.c.profession_id == profession_id,
            )
            .exists()
        )
        conditions.append(profession_match)
    return conditions


def _quote_select() -> Select:
    valid_likes = (
        select(func.count())
        .select_from(quote_likes)
        .where(
            quote_likes.c.quote_id == quotes.c.id,
            quote_likes.c.is_valid == 1,
        )
        .correlate(quotes)
        .scalar_subquery()
    )
    return select(
        quotes.c.id,
        quotes.c.slug,
        quotes.c.text,
        quotes.c.text_en,
        quotes.c.display_language_preference,
        quotes.c.context_note,
        quotes.c.created_at,
        quotes.c.updated_at,
        (quotes.c.legacy_vote_count + valid_likes).label("likes"),
        authors.c.id.label("author_id"),
        authors.c.name.label("author_name"),
        authors.c.slug.label("author_slug"),
        authors.c.description.label("author_description"),
        sources.c.id.label("source_id"),
        sources.c.title.label("source_title"),
        sources.c.slug.label("source_slug"),
        sources.c.published_year.label("source_published_year"),
        characters.c.id.label("character_id"),
        characters.c.name.label("character_name"),
        characters.c.slug.label("character_slug"),
        quote_ranking_scores.c.score_total.label("ranking_score"),
    ).select_from(
        quotes.outerjoin(authors, authors.c.id == quotes.c.author_id)
        .outerjoin(sources, sources.c.id == quotes.c.source_id)
        .outerjoin(characters, characters.c.id == quotes.c.character_id)
        .outerjoin(
            quote_ranking_scores,
            quote_ranking_scores.c.quote_id == quotes.c.id,
        )
    )


def _load_categories(connection: Connection, quote_ids: Iterable[int]) -> dict:
    ids = list(quote_ids)
    if not ids:
        return {}
    rows = connection.execute(
        select(
            quote_categories.c.quote_id,
            categories.c.id,
            categories.c.name,
            categories.c.slug,
        )
        .select_from(
            quote_categories.join(
                categories, categories.c.id == quote_categories.c.category_id
            )
        )
        .where(quote_categories.c.quote_id.in_(ids))
        .order_by(categories.c.sort_order, categories.c.id)
    ).mappings()
    result: dict[int, list[dict]] = {quote_id: [] for quote_id in ids}
    for row in rows:
        result[row["quote_id"]].append(
            {"id": row["id"], "name": row["name"], "slug": row["slug"]}
        )
    return result


def _load_author_details(connection: Connection, author_ids: Iterable[int]) -> dict:
    ids = list({author_id for author_id in author_ids if author_id is not None})
    result = {author_id: {"professions": [], "countries": []} for author_id in ids}
    if not ids:
        return result

    profession_rows = connection.execute(
        select(
            author_professions.c.author_id,
            professions.c.id,
            professions.c.name,
            professions.c.slug,
        )
        .select_from(
            author_professions.join(
                professions, professions.c.id == author_professions.c.profession_id
            )
        )
        .where(author_professions.c.author_id.in_(ids))
        .order_by(author_professions.c.display_order)
    ).mappings()
    for row in profession_rows:
        result[row["author_id"]]["professions"].append(
            {"id": row["id"], "name": row["name"], "slug": row["slug"]}
        )

    country_rows = connection.execute(
        select(
            author_country.c.author_id,
            countries.c.id,
            countries.c.name,
            countries.c.slug,
            author_country.c.is_birth_country,
        )
        .select_from(
            author_country.join(
                countries, countries.c.id == author_country.c.country_id
            )
        )
        .where(author_country.c.author_id.in_(ids))
        .order_by(author_country.c.is_birth_country.desc(), countries.c.id)
    ).mappings()
    for row in country_rows:
        result[row["author_id"]]["countries"].append(
            {
                "id": row["id"],
                "name": row["name"],
                "slug": row["slug"],
                "is_birth_country": bool(row["is_birth_country"]),
            }
        )
    return result


def _present_quotes(connection: Connection, rows: Iterable[Mapping]) -> list[dict]:
    raw_rows = list(rows)
    category_map = _load_categories(connection, (row["id"] for row in raw_rows))
    author_details = _load_author_details(
        connection, (row["author_id"] for row in raw_rows)
    )
    result = []
    for row in raw_rows:
        display = resolve_quote_display(row)
        author = None
        if row["author_id"] is not None:
            details = author_details.get(
                row["author_id"], {"professions": [], "countries": []}
            )
            author = {
                "id": row["author_id"],
                "name": row["author_name"],
                "slug": row["author_slug"],
                "description": row["author_description"],
                **details,
            }
        source = (
            {
                "id": row["source_id"],
                "title": row["source_title"],
                "slug": row["source_slug"],
                "published_year": row["source_published_year"],
            }
            if row["source_id"] is not None
            else None
        )
        character = (
            {
                "id": row["character_id"],
                "name": row["character_name"],
                "slug": row["character_slug"],
            }
            if row["character_id"] is not None
            else None
        )
        created_at = parse_instant(row["created_at"])
        updated_at = parse_instant(row["updated_at"])
        result.append(
            {
                "id": row["id"],
                "slug": row["slug"],
                "path": quote_path(row),
                "text": row["text"],
                "text_en": row["text_en"],
                "display_language_preference": row["display_language_preference"],
                "display_text": display.text,
                "display_language": display.language,
                "alternate_text": display.alternate_text,
                "alternate_language": display.alternate_language,
                "context_note": row["context_note"],
                "created_at": created_at,
                "updated_at": updated_at,
                "created_date": created_at.strftime("%Y.%m.%d"),
                "likes": row["likes"],
                "ranking_score": row["ranking_score"],
                "author": author,
                "source": source,
                "character": character,
                "categories": category_map.get(row["id"], []),
            }
        )
    return result


def list_quotes(
    connection: Connection,
    *,
    page: int = 1,
    author_id: int | None = None,
    category_id: int | None = None,
    profession_id: int | None = None,
    latest: bool = False,
    per_page: int = QUOTES_PER_PAGE,
) -> dict:
    conditions = _public_conditions(
        author_id=author_id,
        category_id=category_id,
        profession_id=profession_id,
    )
    total = connection.execute(
        select(func.count()).select_from(quotes).where(*conditions)
    ).scalar_one()
    total_pages = ceil(total / per_page) if total else 0

    # Do not calculate or bind an OFFSET for an out-of-range page. Python's
    # integers are unbounded, while SQLite INTEGER parameters are signed 64-bit.
    if page > 1 and (total_pages == 0 or page > total_pages):
        return {
            "quotes": [],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }

    statement = _quote_select().where(*conditions)
    if latest:
        statement = statement.order_by(quotes.c.created_at.desc(), quotes.c.id.desc())
    else:
        statement = statement.order_by(
            func.coalesce(quote_ranking_scores.c.score_total, 0).desc(), quotes.c.id
        )
    rows = connection.execute(
        statement.limit(per_page).offset((page - 1) * per_page)
    ).mappings()
    return {
        "quotes": _present_quotes(connection, rows),
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


def get_quote(connection: Connection, identifier: str) -> dict | None:
    qid = parse_qid(identifier)
    condition = quotes.c.id == qid if qid is not None else quotes.c.slug == identifier
    row = (
        connection.execute(_quote_select().where(quotes.c.enable == 1, condition))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    quote = _present_quotes(connection, [row])[0]

    if quote["author"] is not None:
        quote["author"]["quote_count"] = connection.execute(
            select(func.count())
            .select_from(quotes)
            .where(quotes.c.enable == 1, quotes.c.author_id == quote["author"]["id"])
        ).scalar_one()
        related_rows = connection.execute(
            _quote_select()
            .where(
                quotes.c.enable == 1,
                quotes.c.author_id == quote["author"]["id"],
                quotes.c.id != quote["id"],
            )
            .order_by(
                func.coalesce(quote_ranking_scores.c.score_total, 0).desc(),
                quotes.c.id,
            )
            .limit(6)
        ).mappings()
        quote["related"] = _present_quotes(connection, related_rows)
    else:
        quote["related"] = []
    return quote


def homepage_data(connection: Connection) -> dict:
    latest = list_quotes(connection, latest=True, per_page=6)["quotes"]
    top_categories = connection.execute(
        select(categories.c.id, categories.c.name, categories.c.slug)
        .where(categories.c.level == 1)
        .order_by(categories.c.sort_order, categories.c.id)
        .limit(12)
    ).mappings()
    return {"latest": latest, "top_categories": [dict(row) for row in top_categories]}
