"""Legacy URL redirects carried over from the previous site (ADR 008).

The table mirrors the 23 static redirects of the old ``next.config.js``. Two of
them need the database to reach the final canonical in one hop, so they live in
the public router instead: ``/quotations/view/{id}.html`` and the four-digit
``/quotes/{id}`` form both resolve straight to the quote's canonical path.

``docs/url-contract.md`` is the release checklist built from this module.
"""

from urllib.parse import parse_qs, urlencode

PAGE_ONE_SUFFIX = "/page/1"
SEARCH_QUOTATIONS_PATHS = frozenset({"/search/quotations", "/search/quotations/"})

# ``/prefix`` and everything under it collapse onto one page. Next.js wrote
# these as ``:path*``, which also matches the bare prefix. More specific
# prefixes come first because the first match wins.
PREFIX_REDIRECTS = (
    ("/tools", "/"),
    ("/m", "/"),
    ("/countries", "/"),
    ("/jobs", "/professions"),
    ("/sources/view", "/sources"),
    ("/quotations/latest", "/quotes/latest"),
    ("/quotations/ranking", "/ranking"),
    ("/quotations/index", "/quotes"),
    ("/tags/view/1104", "/categories/friendship"),
    ("/tags/view/1115", "/categories/youth"),
    ("/tags/view/1111", "/categories/money"),
    ("/tags/view/1130", "/categories/hope"),
    ("/authors/view/1976", "/authors/mushanokoji-saneatsu"),
    ("/authors/view", "/authors"),
    ("/tags/view", "/categories"),
)


def resolve_legacy_redirect(path: str, query: str) -> str | None:
    """Return the 301 target for a legacy path, or None to keep routing.

    Prefix redirects are checked before ``/page/1`` so that a path such as
    ``/quotations/latest/page/1`` reaches ``/quotes/latest`` in one hop instead
    of chaining through ``/quotations/latest``.
    """
    for prefix, destination in PREFIX_REDIRECTS:
        if path == prefix or path.startswith(f"{prefix}/"):
            return destination

    # The old site kept only ``q`` and dropped the legacy ``p`` page parameter.
    if path in SEARCH_QUOTATIONS_PATHS:
        terms = parse_qs(query).get("q")
        return "/search?" + urlencode({"q": terms[0]}) if terms else None

    # Page 1 is never its own URL: /quotes/page/1 -> /quotes. Filters live in
    # the query string, so they are carried over.
    if path.endswith(PAGE_ONE_SUFFIX):
        base = path[: -len(PAGE_ONE_SUFFIX)] or "/"
        return f"{base}?{query}" if query else base

    return None
