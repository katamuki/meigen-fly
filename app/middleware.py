from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

NO_STORE = "private, no-store"
ROOT_CACHE = "public, s-maxage=300, max-age=60"
AUTHOR_LIST_CACHE = "public, s-maxage=3600, max-age=300"
AUTHOR_DETAIL_CACHE = "public, s-maxage=86400, max-age=3600"

CACHE_RULES = (
    ("/static/", "public, max-age=31536000, immutable"),
    ("/quotes", "public, s-maxage=600, max-age=60"),
    ("/categories", "public, s-maxage=3600, max-age=600"),
    ("/characters", "public, s-maxage=3600, max-age=600"),
    ("/professions", "public, s-maxage=3600, max-age=600"),
    ("/sources", "public, s-maxage=3600, max-age=600"),
    ("/ranking", "public, s-maxage=600, max-age=60"),
    ("/about", "public, s-maxage=604800, max-age=86400"),
    ("/privacy", "public, s-maxage=604800, max-age=86400"),
    ("/terms", "public, s-maxage=604800, max-age=86400"),
)

NO_STORE_PATHS = frozenset({"/admin", "/healthz", "/login", "/random", "/search"})
NO_STORE_PREFIXES = ("/admin/", "/api/likes/", "/search/")

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
    "form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; font-src 'self'; connect-src 'self'"
)


def cache_control_for(request: Request, response: Response) -> str:
    """Select the cache policy defined by ADR 001."""
    path = request.url.path
    if request.method not in {"GET", "HEAD"} or response.status_code >= 400:
        return NO_STORE
    if path in NO_STORE_PATHS or path.startswith(NO_STORE_PREFIXES):
        return NO_STORE
    if path == "/":
        return ROOT_CACHE
    if path == "/authors":
        return AUTHOR_LIST_CACHE
    if path.startswith("/authors/"):
        return AUTHOR_DETAIL_CACHE
    for prefix, value in CACHE_RULES:
        if path.startswith(prefix):
            return value
    return NO_STORE


async def response_headers_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Apply cache and baseline security headers in one central place."""
    response = await call_next(request)
    cache_control = cache_control_for(request, response)
    if cache_control == NO_STORE:
        response.headers["Cache-Control"] = NO_STORE
    else:
        response.headers.setdefault("Cache-Control", cache_control)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    return response
