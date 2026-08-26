"""Queries for public phase 3-B entity pages."""

from collections.abc import Iterable, Mapping
from math import ceil

from sqlalchemy import func, literal, select
from sqlalchemy.engine import Connection

from app.instants import parse_instant
from app.presentation import format_lifespan
from app.schema import (
    author_country,
    author_professions,
    author_rankings,
    authors,
    categories,
    characters,
    countries,
    professions,
    quote_categories,
    quotes,
    source_type_assignments,
    source_types,
    sources,
)

ENTITIES_PER_PAGE = 20
RANK_LAST = 2**63 - 1


def _page(rows: Iterable[Mapping], *, page: int, total: int, per_page: int) -> dict:
    total_pages = ceil(total / per_page) if total else 0
    return {
        "items": [dict(row) for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


def _public_quote_count(condition) -> object:
    return (
        select(func.count(func.distinct(quotes.c.id)))
        .where(quotes.c.enable == 1, condition)
        .scalar_subquery()
    )


def list_authors(
    connection: Connection,
    *,
    page: int = 1,
    profession_id: int | None = None,
    country_id: int | None = None,
    per_page: int = ENTITIES_PER_PAGE,
) -> dict:
    conditions = []
    if profession_id is not None:
        conditions.append(
            select(literal(1))
            .select_from(author_professions)
            .where(
                author_professions.c.author_id == authors.c.id,
                author_professions.c.profession_id == profession_id,
            )
            .exists()
        )
    if country_id is not None:
        conditions.append(
            select(literal(1))
            .select_from(author_country)
            .where(
                author_country.c.author_id == authors.c.id,
                author_country.c.country_id == country_id,
            )
            .exists()
        )
    total = connection.execute(
        select(func.count()).select_from(authors).where(*conditions)
    ).scalar_one()
    total_pages = ceil(total / per_page) if total else 0
    if page > 1 and (not total_pages or page > total_pages):
        return _page([], page=page, total=total, per_page=per_page)

    statement = (
        select(
            authors.c.id,
            authors.c.name,
            authors.c.slug,
            authors.c.description,
            authors.c.name_reading,
            author_rankings.c.rank,
            _public_quote_count(quotes.c.author_id == authors.c.id).label(
                "quote_count"
            ),
        )
        .select_from(
            authors.outerjoin(
                author_rankings, author_rankings.c.author_id == authors.c.id
            )
        )
        .where(*conditions)
        .order_by(
            func.coalesce(author_rankings.c.rank, RANK_LAST),
            authors.c.name_reading,
            authors.c.id,
        )
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    return _page(
        connection.execute(statement).mappings(),
        page=page,
        total=total,
        per_page=per_page,
    )


def _author_links(connection: Connection, author_id: int) -> dict:
    profession_rows = connection.execute(
        select(professions.c.id, professions.c.name, professions.c.slug)
        .select_from(
            author_professions.join(
                professions, professions.c.id == author_professions.c.profession_id
            )
        )
        .where(author_professions.c.author_id == author_id)
        .order_by(author_professions.c.display_order, professions.c.id)
    ).mappings()
    country_rows = connection.execute(
        select(
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
        .where(author_country.c.author_id == author_id)
        .order_by(author_country.c.is_birth_country.desc(), countries.c.name)
    ).mappings()
    return {
        "professions": [dict(row) for row in profession_rows],
        "countries": [dict(row) for row in country_rows],
    }


def get_author(connection: Connection, slug: str) -> dict | None:
    row = (
        connection.execute(
            select(
                authors,
                _public_quote_count(quotes.c.author_id == authors.c.id).label(
                    "quote_count"
                ),
            ).where(authors.c.slug == slug)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result.update(_author_links(connection, result["id"]))
    result["lifespan"] = format_lifespan(
        result["birth_date"],
        result["birth_precision"],
        result["birth_era"],
        result["death_date"],
        result["death_precision"],
        result["death_era"],
    )
    result["created_at"] = parse_instant(result["created_at"])
    result["updated_at"] = parse_instant(result["updated_at"])
    return result


def list_categories(connection: Connection) -> list[dict]:
    child = categories.alias("child")
    parent_count = (
        select(func.count(func.distinct(quotes.c.id)))
        .select_from(
            child.outerjoin(
                quote_categories, quote_categories.c.category_id == child.c.id
            ).outerjoin(
                quotes,
                (quotes.c.id == quote_categories.c.quote_id) & (quotes.c.enable == 1),
            )
        )
        .where(child.c.parent_id == categories.c.id)
        .correlate(categories)
        .scalar_subquery()
    )
    parent_rows = connection.execute(
        select(
            categories.c.id,
            categories.c.name,
            categories.c.slug,
            categories.c.description,
            parent_count.label("quote_count"),
        )
        .where(categories.c.level == 1)
        .order_by(categories.c.sort_order, categories.c.id)
    ).mappings()
    parents = [dict(row) | {"children": []} for row in parent_rows]
    by_id = {row["id"]: row for row in parents}

    child_rows = connection.execute(
        select(
            categories.c.id,
            categories.c.name,
            categories.c.slug,
            categories.c.parent_id,
            (
                select(func.count(func.distinct(quotes.c.id)))
                .select_from(
                    quote_categories.join(
                        quotes, quotes.c.id == quote_categories.c.quote_id
                    )
                )
                .where(
                    quote_categories.c.category_id == categories.c.id,
                    quotes.c.enable == 1,
                )
                .correlate(categories)
                .scalar_subquery()
            ).label("quote_count"),
        )
        .where(categories.c.level == 2)
        .order_by(categories.c.parent_id, categories.c.sort_order, categories.c.id)
    ).mappings()
    for row in child_rows:
        if row["parent_id"] in by_id:
            by_id[row["parent_id"]]["children"].append(dict(row))
    return parents


def get_category(connection: Connection, slug: str) -> dict | None:
    category = (
        connection.execute(select(categories).where(categories.c.slug == slug))
        .mappings()
        .one_or_none()
    )
    if category is None:
        return None
    result = dict(category)
    if result["level"] == 1:
        child = categories.alias("child")
        count = connection.execute(
            select(func.count(func.distinct(quotes.c.id)))
            .select_from(
                child.join(
                    quote_categories, quote_categories.c.category_id == child.c.id
                ).join(quotes, quotes.c.id == quote_categories.c.quote_id)
            )
            .where(child.c.parent_id == result["id"], quotes.c.enable == 1)
        ).scalar_one()
    else:
        count = connection.execute(
            select(func.count(func.distinct(quotes.c.id)))
            .select_from(
                quote_categories.join(
                    quotes, quotes.c.id == quote_categories.c.quote_id
                )
            )
            .where(quote_categories.c.category_id == result["id"], quotes.c.enable == 1)
        ).scalar_one()
    result["quote_count"] = count
    result["created_at"] = parse_instant(result["created_at"])
    result["updated_at"] = parse_instant(result["updated_at"])
    return result


def list_source_types(connection: Connection) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            select(
                source_types.c.id,
                source_types.c.name,
                source_types.c.slug,
            ).order_by(source_types.c.display_order, source_types.c.id)
        ).mappings()
    ]


def list_sources(
    connection: Connection,
    *,
    page: int = 1,
    source_type_slug: str | None = None,
    per_page: int = ENTITIES_PER_PAGE,
) -> dict:
    conditions = []
    if source_type_slug is not None:
        conditions.append(
            select(literal(1))
            .select_from(
                source_type_assignments.join(
                    source_types, source_types.c.id == source_type_assignments.c.type_id
                )
            )
            .where(
                source_type_assignments.c.source_id == sources.c.id,
                source_types.c.slug == source_type_slug,
            )
            .exists()
        )
    total = connection.execute(
        select(func.count()).select_from(sources).where(*conditions)
    ).scalar_one()
    total_pages = ceil(total / per_page) if total else 0
    if page > 1 and (not total_pages or page > total_pages):
        return _page([], page=page, total=total, per_page=per_page)
    rows = connection.execute(
        select(
            sources.c.id,
            sources.c.title.label("name"),
            sources.c.slug,
            sources.c.description,
            sources.c.published_year,
            authors.c.name.label("author_name"),
            _public_quote_count(quotes.c.source_id == sources.c.id).label(
                "quote_count"
            ),
        )
        .select_from(sources.outerjoin(authors, authors.c.id == sources.c.author_id))
        .where(*conditions)
        .order_by(sources.c.title, sources.c.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).mappings()
    return _page(rows, page=page, total=total, per_page=per_page)


def get_source(connection: Connection, slug: str) -> dict | None:
    row = (
        connection.execute(
            select(
                sources,
                authors.c.name.label("author_name"),
                authors.c.slug.label("author_slug"),
                _public_quote_count(quotes.c.source_id == sources.c.id).label(
                    "quote_count"
                ),
            )
            .select_from(
                sources.outerjoin(authors, authors.c.id == sources.c.author_id)
            )
            .where(sources.c.slug == slug)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result["types"] = list(
        connection.execute(
            select(source_types.c.name, source_types.c.slug)
            .select_from(
                source_type_assignments.join(
                    source_types, source_types.c.id == source_type_assignments.c.type_id
                )
            )
            .where(source_type_assignments.c.source_id == result["id"])
            .order_by(source_types.c.display_order, source_types.c.id)
        ).mappings()
    )
    result["created_at"] = parse_instant(result["created_at"])
    result["updated_at"] = parse_instant(result["updated_at"])
    return result


def list_characters(
    connection: Connection,
    *,
    page: int = 1,
    per_page: int = ENTITIES_PER_PAGE,
) -> dict:
    total = connection.execute(
        select(func.count()).select_from(characters)
    ).scalar_one()
    total_pages = ceil(total / per_page) if total else 0
    if page > 1 and (not total_pages or page > total_pages):
        return _page([], page=page, total=total, per_page=per_page)
    rows = connection.execute(
        select(
            characters.c.id,
            characters.c.name,
            characters.c.slug,
            characters.c.description,
            characters.c.character_type,
            sources.c.title.label("source_title"),
            _public_quote_count(quotes.c.character_id == characters.c.id).label(
                "quote_count"
            ),
        )
        .select_from(
            characters.outerjoin(sources, sources.c.id == characters.c.source_id)
        )
        .order_by(characters.c.name, characters.c.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).mappings()
    return _page(rows, page=page, total=total, per_page=per_page)


def get_character(connection: Connection, slug: str) -> dict | None:
    row = (
        connection.execute(
            select(
                characters,
                sources.c.title.label("source_title"),
                sources.c.slug.label("source_slug"),
                _public_quote_count(quotes.c.character_id == characters.c.id).label(
                    "quote_count"
                ),
            )
            .select_from(
                characters.outerjoin(sources, sources.c.id == characters.c.source_id)
            )
            .where(characters.c.slug == slug)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result["created_at"] = parse_instant(result["created_at"])
    result["updated_at"] = parse_instant(result["updated_at"])
    return result


def list_professions(connection: Connection) -> list[dict]:
    quote_count = (
        select(func.count(func.distinct(quotes.c.id)))
        .select_from(
            author_professions.join(
                quotes, quotes.c.author_id == author_professions.c.author_id
            )
        )
        .where(
            author_professions.c.profession_id == professions.c.id,
            quotes.c.enable == 1,
        )
        .correlate(professions)
        .scalar_subquery()
    )
    rows = connection.execute(
        select(
            professions.c.id,
            professions.c.name,
            professions.c.slug,
            professions.c.description,
            quote_count.label("quote_count"),
        ).order_by(professions.c.display_order, professions.c.id)
    ).mappings()
    return [dict(row) for row in rows]


def get_profession(connection: Connection, slug: str) -> dict | None:
    row = (
        connection.execute(select(professions).where(professions.c.slug == slug))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result["quote_count"] = connection.execute(
        select(func.count(func.distinct(quotes.c.id)))
        .select_from(
            author_professions.join(
                quotes, quotes.c.author_id == author_professions.c.author_id
            )
        )
        .where(author_professions.c.profession_id == result["id"], quotes.c.enable == 1)
    ).scalar_one()
    result["created_at"] = parse_instant(result["created_at"])
    result["updated_at"] = parse_instant(result["updated_at"])
    return result


def list_countries(connection: Connection) -> list[dict]:
    quote_count = (
        select(func.count(func.distinct(quotes.c.id)))
        .select_from(
            author_country.join(
                quotes, quotes.c.author_id == author_country.c.author_id
            )
        )
        .where(
            author_country.c.country_id == countries.c.id,
            quotes.c.enable == 1,
        )
        .correlate(countries)
        .scalar_subquery()
    )
    rows = connection.execute(
        select(
            countries.c.id,
            countries.c.name,
            countries.c.slug,
            countries.c.code,
            quote_count.label("quote_count"),
        ).order_by(countries.c.name, countries.c.id)
    ).mappings()
    return [dict(row) for row in rows]


def get_country(connection: Connection, slug: str) -> dict | None:
    row = (
        connection.execute(select(countries).where(countries.c.slug == slug))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result["quote_count"] = connection.execute(
        select(func.count(func.distinct(quotes.c.id)))
        .select_from(
            author_country.join(
                quotes, quotes.c.author_id == author_country.c.author_id
            )
        )
        .where(author_country.c.country_id == result["id"], quotes.c.enable == 1)
    ).scalar_one()
    result["created_at"] = parse_instant(result["created_at"])
    result["updated_at"] = parse_instant(result["updated_at"])
    return result
