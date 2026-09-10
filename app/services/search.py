"""Public LIKE search over quotes and authors (ADR 002, ADR 015, §9.6)."""

from collections.abc import Iterable

from markupsafe import Markup, escape
from sqlalchemy import func, or_, select
from sqlalchemy.engine import Connection

from app.config import get_search_rate_limit
from app.schema import (
    author_professions,
    authors,
    professions,
    quotes,
    sources,
)
from app.services.quotes import _present_quotes, _quote_select
from app.services.rate_limit import RateLimiter

MAX_TERM_LENGTH = 100
QUOTE_RESULT_LIMIT = 50
AUTHOR_RESULT_LIMIT = 20
SEARCH_SCOPES = ("quotes", "authors")

search_rate_limiter = RateLimiter(*get_search_rate_limit())

# SQLite's LIKE is case-insensitive for ASCII only, so fold just those letters.
# A wider fold would also change string lengths and break the <mark> offsets.
_ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def normalize_term(value: str | None) -> str:
    """Collapse surrounding and repeated whitespace, then bound the length.

    A term longer than the limit is truncated instead of rejected so that the
    HTMX fragment never has to render an error in place of results (ADR 015).
    """
    if not value:
        return ""
    return " ".join(value.split())[:MAX_TERM_LENGTH].strip()


def normalize_scope(value: str | None) -> str | None:
    """Return a supported scope, treating anything else as the default."""
    return value if value in SEARCH_SCOPES else None


def highlight(value: str | None, term: str) -> Markup:
    """Escape text and wrap each match of the term in a <mark> element.

    Every fragment is escaped before it becomes Markup, so quote text and the
    search term itself can never inject markup.
    """
    if not value:
        return Markup("")
    if not term:
        return escape(value)
    haystack = value.translate(_ASCII_FOLD)
    needle = term.translate(_ASCII_FOLD)
    parts: list[Markup] = []
    start = 0
    while (found := haystack.find(needle, start)) >= 0:
        end = found + len(needle)
        parts.append(escape(value[start:found]))
        parts.append(Markup("<mark>") + escape(value[found:end]) + Markup("</mark>"))
        start = end
    parts.append(escape(value[start:]))
    return Markup("").join(parts)


def _quote_match(term: str):
    return or_(
        quotes.c.text.contains(term, autoescape=True),
        quotes.c.text_en.contains(term, autoescape=True),
        quotes.c.context_note.contains(term, autoescape=True),
        authors.c.name.contains(term, autoescape=True),
        sources.c.title.contains(term, autoescape=True),
    )


def _author_match(term: str):
    return or_(
        authors.c.name.contains(term, autoescape=True),
        authors.c.name_kana.contains(term, autoescape=True),
        authors.c.name_foreign.contains(term, autoescape=True),
        authors.c.name_reading.contains(term, autoescape=True),
    )


def _count_quotes(connection: Connection, term: str) -> int:
    return connection.execute(
        select(func.count())
        .select_from(
            quotes.outerjoin(authors, authors.c.id == quotes.c.author_id).outerjoin(
                sources, sources.c.id == quotes.c.source_id
            )
        )
        .where(quotes.c.enable == 1, _quote_match(term))
    ).scalar_one()


def _count_authors(connection: Connection, term: str) -> int:
    return connection.execute(
        select(func.count()).select_from(authors).where(_author_match(term))
    ).scalar_one()


def _search_quotes(connection: Connection, term: str) -> list[dict]:
    rows = connection.execute(
        _quote_select()
        .where(quotes.c.enable == 1, _quote_match(term))
        .order_by(quotes.c.id)
        .limit(QUOTE_RESULT_LIMIT)
    ).mappings()
    results = _present_quotes(connection, rows)
    for quote in results:
        quote["highlighted"] = highlight(quote["display_text"], term)
    return results


def _first_professions(
    connection: Connection, author_ids: Iterable[int]
) -> dict[int, str]:
    ids = list(author_ids)
    if not ids:
        return {}
    rows = connection.execute(
        select(author_professions.c.author_id, professions.c.name)
        .select_from(
            author_professions.join(
                professions, professions.c.id == author_professions.c.profession_id
            )
        )
        .where(author_professions.c.author_id.in_(ids))
        .order_by(author_professions.c.display_order, professions.c.id)
    )
    first: dict[int, str] = {}
    for author_id, name in rows:
        first.setdefault(author_id, name)
    return first


def _search_authors(connection: Connection, term: str) -> list[dict]:
    quote_count = (
        select(func.count())
        .select_from(quotes)
        .where(quotes.c.enable == 1, quotes.c.author_id == authors.c.id)
        .correlate(authors)
        .scalar_subquery()
    )
    rows = connection.execute(
        select(
            authors.c.id,
            authors.c.name,
            authors.c.slug,
            quote_count.label("quote_count"),
        )
        .where(_author_match(term))
        .order_by(authors.c.id)
        .limit(AUTHOR_RESULT_LIMIT)
    ).mappings()
    results = [dict(row) for row in rows]
    professions_by_author = _first_professions(
        connection, (row["id"] for row in results)
    )
    for author in results:
        author["profession"] = professions_by_author.get(author["id"])
        author["highlighted"] = highlight(author["name"], term)
    return results


def search(connection: Connection, *, term: str, scope: str | None = None) -> dict:
    """Run the one search shared by GET /search and GET /search/partial."""
    if not term:
        return {
            "q": "",
            "scope": scope,
            "searched": False,
            "counts": {"all": 0, "quotes": 0, "authors": 0},
            "quotes": [],
            "authors": [],
        }

    quote_count = _count_quotes(connection, term)
    author_count = _count_authors(connection, term)
    return {
        "q": term,
        "scope": scope,
        "searched": True,
        "counts": {
            "all": quote_count + author_count,
            "quotes": quote_count,
            "authors": author_count,
        },
        "quotes": (
            _search_quotes(connection, term) if scope in (None, "quotes") else []
        ),
        "authors": (
            _search_authors(connection, term) if scope in (None, "authors") else []
        ),
    }
