"""Source administration screens."""

import re
from datetime import UTC, datetime
from math import ceil
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.admin import (
    int_or_none,
    issue_csrf_token,
    log_admin_operation,
    nullable,
    one,
    optional_text,
    purge_notice,
    read_urlencoded_form,
    require_admin,
    require_csrf,
)
from app.db import get_connection
from app.instants import format_instant
from app.routers.admin import templates
from app.schema import (
    authors,
    characters,
    quotes,
    source_type_assignments,
    source_types,
    sources,
)
from app.services.cache_purge import purge_cache

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
Notice = Annotated[str | None, Query(max_length=200)]
router = APIRouter(prefix="/admin/sources", dependencies=[Depends(require_admin)])
PER_PAGE = 20
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class SourceForm(BaseModel):
    title: str = Field(max_length=1000)
    slug: str = Field(max_length=255)
    author_id: int | None = None
    published_year: int | None = Field(default=None, ge=1)
    description: str | None = Field(default=None, max_length=50000)
    type_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source(self) -> SourceForm:
        self.title = self.title.strip()
        self.slug = self.slug.strip().lower()
        self.description = optional_text(self.description)
        if not self.title:
            raise ValueError("出典名を入力してください。")
        if not self.slug or not SLUG_PATTERN.fullmatch(self.slug):
            raise ValueError("slugは小文字の英数字とハイフンで入力してください。")
        self.type_ids = list(dict.fromkeys(self.type_ids))
        return self


def _input(form: dict[str, list[str]]) -> dict[str, object]:
    return {
        "title": one(form, "title"),
        "slug": one(form, "slug"),
        "author_id": nullable(one(form, "author_id")),
        "published_year": nullable(one(form, "published_year")),
        "description": nullable(one(form, "description")),
        "type_ids": form.get("type_ids", []),
    }


def _error(error: ValidationError) -> str:
    custom = error.errors()[0].get("ctx", {}).get("error")
    if custom:
        return str(custom)
    return {
        "author_id": "著者の選択が不正です。",
        "published_year": "発表年は1以上の整数で入力してください。",
        "type_ids": "出典種別の選択が不正です。",
    }.get(str(error.errors()[0]["loc"][-1]), "入力内容を確認してください。")


def _snapshot(connection: Connection, source_id: int) -> dict[str, Any] | None:
    row = (
        connection.execute(
            select(sources, authors.c.slug.label("author_slug"))
            .select_from(
                sources.outerjoin(authors, authors.c.id == sources.c.author_id)
            )
            .where(sources.c.id == source_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result["type_ids"] = list(
        connection.execute(
            select(source_type_assignments.c.type_id).where(
                source_type_assignments.c.source_id == source_id
            )
        ).scalars()
    )
    result["type_slugs"] = list(
        connection.execute(
            select(source_types.c.slug)
            .select_from(
                source_type_assignments.join(
                    source_types, source_types.c.id == source_type_assignments.c.type_id
                )
            )
            .where(source_type_assignments.c.source_id == source_id)
        ).scalars()
    )
    result["character_slugs"] = list(
        connection.execute(
            select(characters.c.slug).where(characters.c.source_id == source_id)
        ).scalars()
    )
    return result


def _context(
    request: Request,
    email: str,
    connection: Connection,
    *,
    values: dict[str, Any],
    source_id: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    selected = {
        parsed
        for value in values.get("type_ids", [])
        if (parsed := int_or_none(value)) is not None
    }
    return {
        "request": request,
        "admin_email": email,
        "csrf_token": issue_csrf_token(email),
        "values": values,
        "source_id": source_id,
        "selected_author_id": int_or_none(values.get("author_id")),
        "selected_types": selected,
        "error": error,
        "authors": list(
            connection.execute(
                select(authors.c.id, authors.c.name).order_by(
                    authors.c.name_reading, authors.c.id
                )
            ).mappings()
        ),
        "source_types": list(
            connection.execute(
                select(source_types.c.id, source_types.c.name).order_by(
                    source_types.c.display_order, source_types.c.id
                )
            ).mappings()
        ),
    }


def _slug_exists(
    connection: Connection, slug: str, excluding_id: int | None = None
) -> bool:
    query = select(sources.c.id).where(sources.c.slug == slug)
    if excluding_id is not None:
        query = query.where(sources.c.id != excluding_id)
    return connection.execute(query).first() is not None


def _reference_error(connection: Connection, data: SourceForm) -> str | None:
    if (
        data.author_id is not None
        and connection.execute(
            select(authors.c.id).where(authors.c.id == data.author_id)
        ).scalar_one_or_none()
        is None
    ):
        return "選択した著者が見つかりません。"
    if data.type_ids:
        valid = set(
            connection.execute(
                select(source_types.c.id).where(source_types.c.id.in_(data.type_ids))
            ).scalars()
        )
        if valid != set(data.type_ids):
            return "選択した出典種別が見つかりません。"
    return None


def _write_types(
    connection: Connection,
    source_id: int,
    type_ids: list[int],
    now: datetime,
) -> None:
    if type_ids:
        connection.execute(
            insert(source_type_assignments),
            [
                {
                    "source_id": source_id,
                    "type_id": type_id,
                    "created_at": format_instant(now),
                }
                for type_id in type_ids
            ],
        )


def _paths(old: dict[str, Any] | None, new: dict[str, Any] | None) -> list[str]:
    paths = {"/sources", "/sitemap.xml"}
    for item in (old, new):
        if item:
            paths.add(f"/sources/{item['slug']}")
            if item.get("author_slug"):
                paths.add(f"/authors/{item['author_slug']}")
            paths.update(
                f"/sources?{urlencode({'type': slug})}" for slug in item["type_slugs"]
            )
            paths.update(f"/characters/{slug}" for slug in item["character_slugs"])
    return sorted(paths)


def _form_error(
    request: Request,
    email: str,
    connection: Connection,
    values: dict[str, Any],
    message: str,
    source_id: int | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/sources/form.html",
        context=_context(
            request,
            email,
            connection,
            values=values,
            source_id=source_id,
            error=message,
        ),
        status_code=422,
    )


@router.get("", response_class=HTMLResponse)
def source_list(
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
    q: Annotated[str, Query(max_length=200)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    notice: Notice = None,
) -> HTMLResponse:
    term = q.strip()
    conditions = (
        [
            or_(
                sources.c.title.contains(term, autoescape=True),
                sources.c.slug.contains(term, autoescape=True),
            )
        ]
        if term
        else []
    )
    total = connection.execute(
        select(func.count()).select_from(sources).where(*conditions)
    ).scalar_one()
    pages = max(1, ceil(total / PER_PAGE))
    rows = connection.execute(
        select(
            sources.c.id,
            sources.c.title,
            sources.c.slug,
            sources.c.published_year,
            authors.c.name.label("author_name"),
        )
        .select_from(sources.outerjoin(authors, authors.c.id == sources.c.author_id))
        .where(*conditions)
        .order_by(sources.c.title, sources.c.id)
        .limit(PER_PAGE)
        .offset((page - 1) * PER_PAGE)
    ).mappings()
    base = {"q": term} if term else {}
    return templates.TemplateResponse(
        request=request,
        name="admin/sources/list.html",
        context={
            "admin_email": admin_email,
            "rows": rows,
            "q": term,
            "page": page,
            "total": total,
            "notice": notice,
            "previous_url": f"/admin/sources?{urlencode({**base, 'page': page - 1})}"
            if page > 1
            else None,
            "next_url": f"/admin/sources?{urlencode({**base, 'page': page + 1})}"
            if page < pages
            else None,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def source_new(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/sources/form.html",
        context=_context(
            request,
            admin_email,
            connection,
            values={
                "title": "",
                "slug": "",
                "author_id": None,
                "published_year": None,
                "description": None,
                "type_ids": [],
            },
        ),
    )


@router.post("")
async def source_create(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    raw = _input(form)
    try:
        data = SourceForm.model_validate(raw)
    except ValidationError as error:
        return _form_error(request, admin_email, connection, raw, _error(error))
    message = _reference_error(connection, data)
    if message:
        return _form_error(request, admin_email, connection, data.model_dump(), message)
    if _slug_exists(connection, data.slug):
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "このslugは既に使われています。",
        )
    now = datetime.now(UTC)
    values = data.model_dump(exclude={"type_ids"})
    values.update(created_at=format_instant(now), updated_at=format_instant(now))
    try:
        with connection.engine.begin() as write:
            source_id = write.execute(
                insert(sources).values(**values)
            ).inserted_primary_key[0]
            _write_types(write, source_id, data.type_ids, now)
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "slugの重複または入力内容・関連付けの制約違反があります。",
        )
    with connection.engine.connect() as read:
        new = _snapshot(read, source_id)
    log_admin_operation(admin_email, "create", f"sources:{source_id}", now=now)
    notice = purge_notice("出典", "作成", _paths(None, new), purger=purge_cache)
    return RedirectResponse(
        f"/admin/sources?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{source_id}/edit", response_class=HTMLResponse)
def source_edit(
    source_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _snapshot(connection, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="出典が見つかりません")
    return templates.TemplateResponse(
        request=request,
        name="admin/sources/form.html",
        context=_context(
            request,
            admin_email,
            connection,
            values={key: row[key] for key in SourceForm.model_fields},
            source_id=source_id,
        ),
    )


@router.post("/{source_id}")
async def source_update(
    source_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _snapshot(connection, source_id)
    if old is None:
        raise HTTPException(status_code=404, detail="出典が見つかりません")
    raw = _input(form)
    try:
        data = SourceForm.model_validate(raw)
    except ValidationError as error:
        return _form_error(
            request, admin_email, connection, raw, _error(error), source_id
        )
    message = _reference_error(connection, data)
    if message:
        return _form_error(
            request, admin_email, connection, data.model_dump(), message, source_id
        )
    if _slug_exists(connection, data.slug, source_id):
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "このslugは既に使われています。",
            source_id,
        )
    now = datetime.now(UTC)
    values = data.model_dump(exclude={"type_ids"})
    values["updated_at"] = format_instant(now)
    try:
        with connection.engine.begin() as write:
            write.execute(
                update(sources).where(sources.c.id == source_id).values(**values)
            )
            write.execute(
                delete(source_type_assignments).where(
                    source_type_assignments.c.source_id == source_id
                )
            )
            _write_types(write, source_id, data.type_ids, now)
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "slugの重複または入力内容・関連付けの制約違反があります。",
            source_id,
        )
    with connection.engine.connect() as read:
        new = _snapshot(read, source_id)
    log_admin_operation(admin_email, "update", f"sources:{source_id}", now=now)
    notice = purge_notice("出典", "更新", _paths(old, new), purger=purge_cache)
    return RedirectResponse(
        f"/admin/sources?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{source_id}/delete", response_class=HTMLResponse)
def source_delete_confirm(
    source_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _snapshot(connection, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="出典が見つかりません")
    quote_count = connection.execute(
        select(func.count()).select_from(quotes).where(quotes.c.source_id == source_id)
    ).scalar_one()
    character_count = connection.execute(
        select(func.count())
        .select_from(characters)
        .where(characters.c.source_id == source_id)
    ).scalar_one()
    return templates.TemplateResponse(
        request=request,
        name="admin/sources/delete.html",
        context={
            "request": request,
            "admin_email": admin_email,
            "csrf_token": issue_csrf_token(admin_email),
            "source": row,
            "quote_count": quote_count,
            "character_count": character_count,
        },
    )


@router.post("/{source_id}/delete")
async def source_delete(
    source_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> RedirectResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _snapshot(connection, source_id)
    if old is None:
        raise HTTPException(status_code=404, detail="出典が見つかりません")
    with connection.engine.begin() as write:
        write.execute(delete(sources).where(sources.c.id == source_id))
    now = datetime.now(UTC)
    log_admin_operation(admin_email, "delete", f"sources:{source_id}", now=now)
    notice = purge_notice("出典", "削除", _paths(old, None), purger=purge_cache)
    return RedirectResponse(
        f"/admin/sources?{urlencode({'notice': notice})}", status_code=303
    )
