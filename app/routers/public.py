"""Public home and quote pages for phase 3-A."""

from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.engine import Connection

from app.db import get_connection
from app.services.quotes import (
    SQLITE_MAX_INTEGER,
    get_quote,
    homepage_data,
    list_quotes,
    parse_qid,
)

APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["comma"] = lambda value: f"{value:,}"

router = APIRouter()
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
PositiveId = Annotated[int | None, Query(ge=1, le=SQLITE_MAX_INTEGER)]


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
