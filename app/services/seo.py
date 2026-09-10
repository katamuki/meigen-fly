"""sitemap.xml and robots.txt.

The four sitemap sources are fixed by inventory-4 §9.8: public quotes follow the
slug/qid contract of ADR 008, and authors, sources and categories use their
``updated_at`` as lastmod. Characters and professions stay out because §9.8 does
not list them, matching the previous site.
"""

from collections.abc import Iterator
from xml.sax.saxutils import escape

from sqlalchemy import Table, select
from sqlalchemy.engine import Connection

from app.instants import parse_instant
from app.schema import authors, categories, quotes, sources
from app.services.quotes import quote_path

# Listing pages that exist as routes. /search is left out on purpose: it is
# noindex and disallowed below.
STATIC_PATHS = (
    "/",
    "/quotes",
    "/quotes/latest",
    "/random",
    "/ranking",
    "/authors",
    "/categories",
    "/sources",
    "/characters",
    "/professions",
)

SLUG_SOURCES = (
    (authors, "/authors"),
    (sources, "/sources"),
    (categories, "/categories"),
)

ROBOTS_DISALLOW = ("/admin", "/api/", "/search")


def _lastmod(instant: str) -> str:
    """Sitemaps only need the UTC date part of an ADR 011 instant."""
    return parse_instant(instant).date().isoformat()


def sitemap_entries(connection: Connection) -> Iterator[tuple[str, str | None]]:
    """Yield every indexable path with its lastmod, listing pages first."""
    for path in STATIC_PATHS:
        yield path, None
    quote_rows = connection.execute(
        select(quotes.c.id, quotes.c.slug, quotes.c.updated_at)
        .where(quotes.c.enable == 1)
        .order_by(quotes.c.id)
    ).mappings()
    for row in quote_rows:
        yield quote_path(row), _lastmod(row["updated_at"])
    for table, prefix in SLUG_SOURCES:
        yield from _slug_entries(connection, table, prefix)


def _slug_entries(
    connection: Connection, table: Table, prefix: str
) -> Iterator[tuple[str, str | None]]:
    rows = connection.execute(
        select(table.c.slug, table.c.updated_at).order_by(table.c.id)
    ).mappings()
    for row in rows:
        if row["slug"]:
            yield f"{prefix}/{row['slug']}", _lastmod(row["updated_at"])


def render_sitemap(connection: Connection, origin: str) -> str:
    """Build the whole sitemap; the site is far below the 50,000 URL limit."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for path, lastmod in sitemap_entries(connection):
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(origin + path)}</loc>")
        if lastmod is not None:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def render_robots(origin: str) -> str:
    """Allow the public pages, keep admin, API and search out of the index."""
    lines = ["User-agent: *", "Allow: /"]
    lines.extend(f"Disallow: {path}" for path in ROBOTS_DISALLOW)
    lines.append("")
    lines.append(f"Sitemap: {origin}/sitemap.xml")
    return "\n".join(lines) + "\n"


def _breadcrumb(origin: str, trail: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": position,
                "name": name,
                "item": origin + path,
            }
            for position, (name, path) in enumerate(trail, start=1)
        ],
    }


def _linked(
    entity: dict | None, schema_type: str, prefix: str, key: str
) -> dict | None:
    if entity is None:
        return None
    node = {"@type": schema_type, "name": entity[key]}
    if entity["slug"]:
        node["url"] = f"{prefix}/{entity['slug']}"
    return node


def quote_structured_data(quote: dict, origin: str) -> list[dict]:
    """Describe one quote as schema.org Quotation plus its breadcrumb trail."""
    url = origin + quote["path"]
    quotation: dict = {
        "@context": "https://schema.org",
        "@type": "Quotation",
        "text": quote["display_text"],
        "inLanguage": quote["display_language"],
        "url": url,
    }
    author = _linked(quote["author"], "Person", f"{origin}/authors", "name")
    source = _linked(quote["source"], "CreativeWork", f"{origin}/sources", "title")
    character = _linked(quote["character"], "Person", f"{origin}/characters", "name")
    if author is not None:
        quotation["author"] = author
    if source is not None:
        quotation["isPartOf"] = source
    if character is not None:
        quotation["spokenByCharacter"] = character
    trail = [
        ("ホーム", "/"),
        ("名言一覧", "/quotes"),
        (quote["display_text"][:15], quote["path"]),
    ]
    return [quotation, _breadcrumb(origin, trail)]


def author_structured_data(author: dict, origin: str) -> list[dict]:
    """Describe one author as schema.org Person plus its breadcrumb trail."""
    person: dict = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": author["name"],
        "url": f"{origin}/authors/{author['slug']}",
    }
    if author.get("description"):
        person["description"] = author["description"]
    trail = [
        ("ホーム", "/"),
        ("著者", "/authors"),
        (author["name"], f"/authors/{author['slug']}"),
    ]
    return [person, _breadcrumb(origin, trail)]
