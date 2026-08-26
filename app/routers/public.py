"""Public pages."""

from ipaddress import ip_address
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.engine import Connection
from starlette.concurrency import run_in_threadpool

from app.config import get_public_origin
from app.db import get_connection
from app.services.entities import (
    get_author,
    get_category,
    get_character,
    get_country,
    get_profession,
    get_source,
    list_authors,
    list_categories,
    list_characters,
    list_countries,
    list_professions,
    list_source_types,
    list_sources,
)
from app.services.likes import (
    LikeWriteUnavailableError,
    QuoteNotLikeableError,
    like_rate_limiter,
    record_like,
    validate_client_uuid,
)
from app.services.quotes import (
    SQLITE_MAX_INTEGER,
    get_quote,
    homepage_data,
    list_quotes,
    list_ranked_quotes,
    parse_qid,
    random_quotes,
)
from app.services.rankings import list_author_rankings, list_category_rankings

APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["comma"] = lambda value: f"{value:,}"

router = APIRouter()
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
PositiveId = Annotated[int | None, Query(ge=1, le=SQLITE_MAX_INTEGER)]
PageNumber = Annotated[int, Query(ge=1, le=SQLITE_MAX_INTEGER)]


def _page_url(base_path: str, page: int, query: dict[str, int]) -> str:
    path = base_path if page == 1 else f"{base_path}/page/{page}"
    return f"{path}?{urlencode(query)}" if query else path


def _parse_paginated_page(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise HTTPException(status_code=404)
    try:
        page = int(value)
    except ValueError as error:
        raise HTTPException(status_code=404) from error
    if page < 2:
        raise HTTPException(status_code=404)
    return page


def _pagination(base_path: str, result: dict, query: dict[str, int]) -> dict:
    current = result["page"]
    total_pages = result["total_pages"]
    start = max(1, current - 2)
    end = min(total_pages, current + 2)
    pages = [
        {"number": number, "url": _page_url(base_path, number, query)}
        for number in range(start, end + 1)
    ]
    return {
        "number": current,
        "has_prev": current > 1,
        "has_next": current < total_pages,
        "prev_url": _page_url(base_path, current - 1, query) if current > 1 else None,
        "next_url": (
            _page_url(base_path, current + 1, query) if current < total_pages else None
        ),
        "pages": pages,
    }


def _query_pagination(base_path: str, result: dict, query: dict[str, object]) -> dict:
    def url(page: int) -> str:
        params = {**query}
        if page > 1:
            params["page"] = page
        return f"{base_path}?{urlencode(params)}" if params else base_path

    current = result["page"]
    total_pages = result["total_pages"]
    start = max(1, current - 2)
    end = min(total_pages, current + 2)
    return {
        "number": current,
        "has_prev": current > 1,
        "has_next": current < total_pages,
        "prev_url": url(current - 1) if current > 1 else None,
        "next_url": url(current + 1) if current < total_pages else None,
        "pages": [
            {"number": number, "url": url(number)} for number in range(start, end + 1)
        ],
    }


def _render_entity_quotes(
    request: Request,
    connection: Connection,
    *,
    entity: dict,
    entity_type: str,
    base_path: str,
    page: int,
    query_pagination: bool = False,
    **filters: int,
) -> HTMLResponse:
    result = list_quotes(connection, page=page, **filters)
    if page > 1 and (result["total_pages"] == 0 or page > result["total_pages"]):
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="entity_detail.html",
        context={
            "entity": entity,
            "entity_type": entity_type,
            **result,
            "pagination": (
                _query_pagination(base_path, result, {})
                if query_pagination
                else _pagination(base_path, result, {})
            ),
        },
    )


def _render_quote_list(
    request: Request,
    connection: Connection,
    *,
    page: int,
    latest: bool,
    author_id: int | None,
    category_id: int | None,
    profession_id: int | None,
) -> HTMLResponse:
    result = list_quotes(
        connection,
        page=page,
        latest=latest,
        author_id=author_id,
        category_id=category_id,
        profession_id=profession_id,
    )
    if page > 1 and (result["total_pages"] == 0 or page > result["total_pages"]):
        raise HTTPException(status_code=404)
    query = {
        key: value
        for key, value in {
            "author_id": author_id,
            "category_id": category_id,
            "profession_id": profession_id,
        }.items()
        if value is not None
    }
    base_path = "/quotes/latest" if latest else "/quotes"
    return templates.TemplateResponse(
        request=request,
        name="quote_list.html",
        context={
            **result,
            "latest": latest,
            "pagination": _pagination(base_path, result, query),
            "filters_active": bool(query),
        },
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request, connection: ConnectionDependency) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context=homepage_data(connection),
    )


@router.get("/random", response_class=HTMLResponse)
def random_page(request: Request, connection: ConnectionDependency) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="random.html",
        context={"quotes": random_quotes(connection)},
    )


def _ranking_response(
    request: Request, connection: Connection, tab: str
) -> HTMLResponse:
    if tab == "quotes":
        items = list_ranked_quotes(connection)
    elif tab == "authors":
        items = list_author_rankings(connection)
    elif tab == "categories":
        items = list_category_rankings(connection)
    else:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="ranking.html",
        context={"tab": tab, "items": items},
    )


@router.get("/ranking", response_class=HTMLResponse)
def ranking_index(request: Request, connection: ConnectionDependency) -> HTMLResponse:
    return _ranking_response(request, connection, "quotes")


@router.get("/ranking/{tab}", response_class=HTMLResponse)
def ranking_tab(
    request: Request, tab: str, connection: ConnectionDependency
) -> HTMLResponse:
    return _ranking_response(request, connection, tab)


def _validate_like_headers(request: Request) -> None:
    if request.headers.get("origin") != get_public_origin():
        raise HTTPException(status_code=403, detail="invalid origin")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site != "same-origin":
        raise HTTPException(status_code=403, detail="invalid fetch metadata")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if media_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="unsupported content type")


async def _like_client_uuid(request: Request) -> str:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 256:
            raise HTTPException(status_code=413, detail="request body too large")
        body.extend(chunk)
    try:
        fields = parse_qs(
            bytes(body).decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=2,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="invalid form body") from error
    if set(fields) != {"client_uuid"} or len(fields["client_uuid"]) != 1:
        raise HTTPException(status_code=422, detail="client_uuid is required")
    try:
        return validate_client_uuid(fields["client_uuid"][0])
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _like_source_ip(request: Request) -> str:
    forwarded = request.headers.get("cf-connecting-ip")
    if forwarded is not None:
        try:
            return str(ip_address(forwarded))
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid source IP") from error
    return request.client.host if request.client is not None else "unknown"


@router.post("/api/likes/{quote_id}", response_class=HTMLResponse)
async def like_quote(
    request: Request, quote_id: int, connection: ConnectionDependency
) -> HTMLResponse:
    if quote_id < 1 or quote_id > SQLITE_MAX_INTEGER:
        raise HTTPException(status_code=404)
    _validate_like_headers(request)
    allowed, retry_after = like_rate_limiter.allow(_like_source_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="too many like requests",
            headers={"Retry-After": str(retry_after)},
        )
    client_uuid = await _like_client_uuid(request)
    try:
        like_count = await run_in_threadpool(
            record_like, connection, quote_id, client_uuid
        )
    except QuoteNotLikeableError as error:
        raise HTTPException(status_code=404) from error
    except LikeWriteUnavailableError as error:
        raise HTTPException(status_code=503, detail="like write unavailable") from error
    return templates.TemplateResponse(
        request=request,
        name="partials/like_button.html",
        context={
            "quote": {"id": quote_id, "likes": like_count},
            "liked": True,
            "client_uuid": client_uuid,
            "size": request.query_params.get("size"),
        },
    )


@router.get("/quotes", response_class=HTMLResponse)
def quotes_index(
    request: Request,
    connection: ConnectionDependency,
    author_id: PositiveId = None,
    category_id: PositiveId = None,
    profession_id: PositiveId = None,
) -> HTMLResponse:
    return _render_quote_list(
        request,
        connection,
        page=1,
        latest=False,
        author_id=author_id,
        category_id=category_id,
        profession_id=profession_id,
    )


@router.get("/quotes/page/{page}", response_class=HTMLResponse)
def quotes_page(
    request: Request,
    page: str,
    connection: ConnectionDependency,
    author_id: PositiveId = None,
    category_id: PositiveId = None,
    profession_id: PositiveId = None,
) -> HTMLResponse:
    page_number = _parse_paginated_page(page)
    return _render_quote_list(
        request,
        connection,
        page=page_number,
        latest=False,
        author_id=author_id,
        category_id=category_id,
        profession_id=profession_id,
    )


@router.get("/quotes/latest", response_class=HTMLResponse)
def quotes_latest(request: Request, connection: ConnectionDependency) -> HTMLResponse:
    return _render_quote_list(
        request,
        connection,
        page=1,
        latest=True,
        author_id=None,
        category_id=None,
        profession_id=None,
    )


@router.get("/quotes/latest/page/{page}", response_class=HTMLResponse)
def quotes_latest_page(
    request: Request,
    page: str,
    connection: ConnectionDependency,
) -> HTMLResponse:
    page_number = _parse_paginated_page(page)
    return _render_quote_list(
        request,
        connection,
        page=page_number,
        latest=True,
        author_id=None,
        category_id=None,
        profession_id=None,
    )


@router.get("/quotes/{identifier}", response_class=HTMLResponse)
def quote_detail(
    request: Request,
    identifier: str,
    connection: ConnectionDependency,
) -> HTMLResponse:
    quote = get_quote(connection, identifier)
    if quote is None:
        raise HTTPException(status_code=404)
    if parse_qid(identifier) is not None and quote["slug"]:
        return RedirectResponse(quote["path"], status_code=301)
    return templates.TemplateResponse(
        request=request,
        name="quote_detail.html",
        context={"quote": quote, "related": quote["related"]},
    )


def _render_authors(
    request: Request,
    connection: Connection,
    *,
    page: int,
    profession_id: int | None,
    country_id: int | None,
) -> HTMLResponse:
    result = list_authors(
        connection,
        page=page,
        profession_id=profession_id,
        country_id=country_id,
    )
    if page > 1 and (result["total_pages"] == 0 or page > result["total_pages"]):
        raise HTTPException(status_code=404)
    query = {
        key: value
        for key, value in {
            "profession_id": profession_id,
            "country_id": country_id,
        }.items()
        if value is not None
    }
    return templates.TemplateResponse(
        request=request,
        name="author_list.html",
        context={
            **result,
            "professions": list_professions(connection),
            "countries": list_countries(connection),
            "pagination": _query_pagination("/authors", result, query),
        },
    )


@router.get("/authors", response_class=HTMLResponse)
def authors_index(
    request: Request,
    connection: ConnectionDependency,
    profession_id: PositiveId = None,
    country_id: PositiveId = None,
    page: PageNumber = 1,
) -> HTMLResponse:
    return _render_authors(
        request,
        connection,
        page=page,
        profession_id=profession_id,
        country_id=country_id,
    )


@router.get("/authors/places/{slug}", response_class=HTMLResponse)
def country_detail(
    request: Request,
    slug: str,
    connection: ConnectionDependency,
    page: PageNumber = 1,
) -> HTMLResponse:
    country = get_country(connection, slug)
    if country is None:
        raise HTTPException(status_code=404)
    authors_result = list_authors(connection, country_id=country["id"], page=page)
    if page > 1 and (
        authors_result["total_pages"] == 0 or page > authors_result["total_pages"]
    ):
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="country_detail.html",
        context={
            "country": country,
            "authors": authors_result["items"],
            "pagination": _query_pagination(
                f"/authors/places/{slug}", authors_result, {}
            ),
        },
    )


@router.get("/authors/{slug}", response_class=HTMLResponse)
def author_detail(
    request: Request, slug: str, connection: ConnectionDependency
) -> HTMLResponse:
    author = get_author(connection, slug)
    if author is None:
        raise HTTPException(status_code=404)
    return _render_entity_quotes(
        request,
        connection,
        entity=author,
        entity_type="author",
        base_path=f"/authors/{slug}",
        page=1,
        author_id=author["id"],
    )


@router.get("/authors/{slug}/page/{page}", response_class=HTMLResponse)
def author_detail_page(
    request: Request, slug: str, page: str, connection: ConnectionDependency
) -> HTMLResponse:
    author = get_author(connection, slug)
    if author is None:
        raise HTTPException(status_code=404)
    return _render_entity_quotes(
        request,
        connection,
        entity=author,
        entity_type="author",
        base_path=f"/authors/{slug}",
        page=_parse_paginated_page(page),
        author_id=author["id"],
    )


@router.get("/categories", response_class=HTMLResponse)
def categories_index(
    request: Request, connection: ConnectionDependency
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="category_list.html",
        context={"categories": list_categories(connection)},
    )


def _category_detail_response(
    request: Request,
    connection: Connection,
    *,
    slug: str,
    page: int,
) -> HTMLResponse:
    category = get_category(connection, slug)
    if category is None:
        raise HTTPException(status_code=404)
    return _render_entity_quotes(
        request,
        connection,
        entity=category,
        entity_type="category",
        base_path=f"/categories/{slug}",
        page=page,
        category_id=category["id"],
    )


@router.get("/categories/{slug}", response_class=HTMLResponse)
def category_detail(
    request: Request, slug: str, connection: ConnectionDependency
) -> HTMLResponse:
    return _category_detail_response(request, connection, slug=slug, page=1)


@router.get("/categories/{slug}/page/{page}", response_class=HTMLResponse)
def category_detail_page(
    request: Request, slug: str, page: str, connection: ConnectionDependency
) -> HTMLResponse:
    return _category_detail_response(
        request, connection, slug=slug, page=_parse_paginated_page(page)
    )


def _render_sources(
    request: Request,
    connection: Connection,
    *,
    page: int,
    source_type: str | None,
) -> HTMLResponse:
    result = list_sources(connection, page=page, source_type_slug=source_type)
    if page > 1 and (result["total_pages"] == 0 or page > result["total_pages"]):
        raise HTTPException(status_code=404)
    query = {"type": source_type} if source_type else {}
    return templates.TemplateResponse(
        request=request,
        name="master_list.html",
        context={
            **result,
            "title": "出典から探す",
            "entity_type": "source",
            "base_path": "/sources",
            "source_types": list_source_types(connection),
            "active_source_type": source_type,
            "pagination": _query_pagination("/sources", result, query),
        },
    )


@router.get("/sources", response_class=HTMLResponse)
def sources_index(
    request: Request,
    connection: ConnectionDependency,
    source_type: Annotated[str | None, Query(alias="type")] = None,
    page: PageNumber = 1,
) -> HTMLResponse:
    return _render_sources(
        request,
        connection,
        page=page,
        source_type=source_type,
    )


def _source_detail_response(
    request: Request,
    connection: Connection,
    *,
    slug: str,
    page: int,
) -> HTMLResponse:
    source = get_source(connection, slug)
    if source is None:
        raise HTTPException(status_code=404)
    return _render_entity_quotes(
        request,
        connection,
        entity=source,
        entity_type="source",
        base_path=f"/sources/{slug}",
        page=page,
        source_id=source["id"],
    )


@router.get("/sources/{slug}", response_class=HTMLResponse)
def source_detail(
    request: Request, slug: str, connection: ConnectionDependency
) -> HTMLResponse:
    return _source_detail_response(request, connection, slug=slug, page=1)


@router.get("/sources/{slug}/page/{page}", response_class=HTMLResponse)
def source_detail_page(
    request: Request, slug: str, page: str, connection: ConnectionDependency
) -> HTMLResponse:
    return _source_detail_response(
        request, connection, slug=slug, page=_parse_paginated_page(page)
    )


@router.get("/characters", response_class=HTMLResponse)
def characters_index(
    request: Request, connection: ConnectionDependency, page: PageNumber = 1
) -> HTMLResponse:
    result = list_characters(connection, page=page)
    if page > 1 and (result["total_pages"] == 0 or page > result["total_pages"]):
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="master_list.html",
        context={
            **result,
            "title": "登場人物から探す",
            "entity_type": "character",
            "base_path": "/characters",
            "pagination": _query_pagination("/characters", result, {}),
        },
    )


@router.get("/characters/{slug}", response_class=HTMLResponse)
def character_detail(
    request: Request, slug: str, connection: ConnectionDependency
) -> HTMLResponse:
    character = get_character(connection, slug)
    if character is None:
        raise HTTPException(status_code=404)
    return _render_entity_quotes(
        request,
        connection,
        entity=character,
        entity_type="character",
        base_path=f"/characters/{slug}",
        page=1,
        character_id=character["id"],
    )


@router.get("/characters/{slug}/page/{page}", response_class=HTMLResponse)
def character_detail_page(
    request: Request, slug: str, page: str, connection: ConnectionDependency
) -> HTMLResponse:
    character = get_character(connection, slug)
    if character is None:
        raise HTTPException(status_code=404)
    return _render_entity_quotes(
        request,
        connection,
        entity=character,
        entity_type="character",
        base_path=f"/characters/{slug}",
        page=_parse_paginated_page(page),
        character_id=character["id"],
    )


@router.get("/professions", response_class=HTMLResponse)
def professions_index(
    request: Request, connection: ConnectionDependency
) -> HTMLResponse:
    items = list_professions(connection)
    return templates.TemplateResponse(
        request=request,
        name="master_list.html",
        context={
            "items": items,
            "title": "職業から探す",
            "entity_type": "profession",
            "base_path": "/professions",
            "total": len(items),
            "pagination": None,
        },
    )


def _profession_detail_response(
    request: Request, connection: Connection, *, slug: str, page: int = 1
) -> HTMLResponse:
    profession = get_profession(connection, slug)
    if profession is None:
        raise HTTPException(status_code=404)
    return _render_entity_quotes(
        request,
        connection,
        entity=profession,
        entity_type="profession",
        base_path=f"/professions/{slug}/quotes",
        page=page,
        query_pagination=True,
        profession_id=profession["id"],
    )


@router.get("/professions/{slug}", response_class=HTMLResponse)
def profession_detail(
    request: Request, slug: str, connection: ConnectionDependency
) -> HTMLResponse:
    return _profession_detail_response(request, connection, slug=slug)


@router.get("/professions/{slug}/quotes", response_class=HTMLResponse)
def profession_quotes(
    request: Request,
    slug: str,
    connection: ConnectionDependency,
    page: PageNumber = 1,
) -> HTMLResponse:
    return _profession_detail_response(request, connection, slug=slug, page=page)
