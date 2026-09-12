from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import normalize_authority
from app.services.redirects import resolve_legacy_redirect

NO_STORE = "private, no-store"
ROOT_CACHE = "public, s-maxage=300, max-age=60"
AUTHOR_LIST_CACHE = "public, s-maxage=3600, max-age=300"
AUTHOR_DETAIL_CACHE = "public, s-maxage=86400, max-age=3600"
OG_IMAGE_CACHE = "public, s-maxage=2592000, max-age=86400"
REDIRECT_CACHE = "public, s-maxage=86400, max-age=3600"

CACHE_RULES = (
    ("/static/", "public, max-age=31536000, immutable"),
    ("/quotes", "public, s-maxage=600, max-age=60"),
    ("/categories", "public, s-maxage=3600, max-age=600"),
    ("/characters", "public, s-maxage=3600, max-age=600"),
    ("/professions", "public, s-maxage=3600, max-age=600"),
    ("/sources", "public, s-maxage=3600, max-age=600"),
    ("/ranking", "public, s-maxage=600, max-age=60"),
    ("/sitemap.xml", "public, s-maxage=3600, max-age=600"),
    ("/robots.txt", "public, s-maxage=86400, max-age=3600"),
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


class ExactHostMiddleware:
    """Reject requests whose Host authority differs from PUBLIC_ORIGIN."""

    def __init__(self, app: ASGIApp, allowed_authority: str) -> None:
        self.app = app
        self.allowed_authority = normalize_authority(allowed_authority)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host_values = Headers(scope=scope).getlist("host")
        try:
            request_authority = normalize_authority(host_values[0])
        except IndexError, ValueError:
            request_authority = None

        if len(host_values) != 1 or request_authority != self.allowed_authority:
            response = PlainTextResponse("Invalid host header", status_code=400)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def cache_control_for(request: Request, response: Response) -> str:
    """Select the cache policy defined by ADR 001."""
    path = request.url.path
    if request.method not in {"GET", "HEAD"} or response.status_code >= 400:
        return NO_STORE
    if path in NO_STORE_PATHS or path.startswith(NO_STORE_PREFIXES):
        return NO_STORE
    if response.status_code in {301, 308}:
        # Permanent legacy, trailing-slash and canonical redirects are stable
        # enough to cache. Anything temporary keeps the path policy instead.
        return REDIRECT_CACHE
    if path == "/":
        return ROOT_CACHE
    if (
        path.startswith(("/quotes/", "/authors/"))
        and path.endswith("/og.png")
        and path.count("/") == 3
    ):
        return OG_IMAGE_CACHE
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


async def legacy_redirect_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Answer the old site's URLs with one permanent redirect (ADR 008)."""
    if request.method in {"GET", "HEAD"}:
        target = resolve_legacy_redirect(request.url.path, request.url.query)
        if target is not None:
            return RedirectResponse(target, status_code=301)
    return await call_next(request)
