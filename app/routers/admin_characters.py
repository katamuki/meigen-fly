"""Character administration screens."""

import re
from datetime import UTC, datetime
from math import ceil
from typing import Annotated, Any, Literal
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
from app.schema import characters, quotes, sources
from app.services.cache_purge import purge_cache

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
Notice = Annotated[str | None, Query(max_length=200)]
router = APIRouter(prefix="/admin/characters", dependencies=[Depends(require_admin)])
PER_PAGE = 20
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class CharacterForm(BaseModel):
    name: str = Field(max_length=1000)
    slug: str = Field(max_length=255)
    source_id: int | None = None
    description: str | None = Field(default=None, max_length=50000)
    character_type: Literal["character", "narrator", "author_voice"] = "character"

    @model_validator(mode="after")
    def validate_character(self) -> CharacterForm:
        self.name = self.name.strip()
        self.slug = self.slug.strip().lower()
        self.description = optional_text(self.description)
        if not self.name:
            raise ValueError("登場人物名を入力してください。")
        if not self.slug or not SLUG_PATTERN.fullmatch(self.slug):
            raise ValueError("slugは小文字の英数字とハイフンで入力してください。")
        return self


def _input(form: dict[str, list[str]]) -> dict[str, object]:
    return {
        "name": one(form, "name"),
        "slug": one(form, "slug"),
        "source_id": nullable(one(form, "source_id")),
        "description": nullable(one(form, "description")),
        "character_type": one(form, "character_type", "character"),
    }


def _error(error: ValidationError) -> str:
    custom = error.errors()[0].get("ctx", {}).get("error")
    if custom:
        return str(custom)
    return {
        "source_id": "出典の選択が不正です。",
        "character_type": "種別を選択してください。",
    }.get(str(error.errors()[0]["loc"][-1]), "入力内容を確認してください。")


def _snapshot(connection: Connection, character_id: int) -> dict[str, Any] | None:
    row = (
        connection.execute(
            select(characters, sources.c.slug.label("source_slug"))
            .select_from(
                characters.outerjoin(sources, sources.c.id == characters.c.source_id)
            )
            .where(characters.c.id == character_id)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def _context(
    request: Request,
    email: str,
    connection: Connection,
    *,
    values: dict[str, Any],
    character_id: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "request": request,
        "admin_email": email,
        "csrf_token": issue_csrf_token(email),
        "values": values,
        "character_id": character_id,
        "selected_source_id": int_or_none(values.get("source_id")),
        "error": error,
        "sources": list(
            connection.execute(
                select(sources.c.id, sources.c.title).order_by(
                    sources.c.title, sources.c.id
                )
            ).mappings()
        ),
    }


def _slug_exists(
    connection: Connection, slug: str, excluding_id: int | None = None
) -> bool:
    query = select(characters.c.id).where(characters.c.slug == slug)
    if excluding_id is not None:
        query = query.where(characters.c.id != excluding_id)
    return connection.execute(query).first() is not None


def _reference_error(connection: Connection, data: CharacterForm) -> str | None:
    if (
        data.source_id is not None
        and connection.execute(
            select(sources.c.id).where(sources.c.id == data.source_id)
        ).scalar_one_or_none()
        is None
    ):
        return "選択した出典が見つかりません。"
    return None


def _paths(old: dict[str, Any] | None, new: dict[str, Any] | None) -> list[str]:
    paths = {"/characters"}
    for item in (old, new):
        if item:
            paths.add(f"/characters/{item['slug']}")
            if item.get("source_slug"):
                paths.add(f"/sources/{item['source_slug']}")
    return sorted(paths)


def _form_error(
    request: Request,
    email: str,
    connection: Connection,
    values: dict[str, Any],
    message: str,
    character_id: int | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/characters/form.html",
        context=_context(
            request,
            email,
            connection,
            values=values,
            character_id=character_id,
            error=message,
        ),
        status_code=422,
    )


@router.get("", response_class=HTMLResponse)
def character_list(
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
                characters.c.name.contains(term, autoescape=True),
                characters.c.slug.contains(term, autoescape=True),
            )
        ]
        if term
        else []
    )
    total = connection.execute(
        select(func.count()).select_from(characters).where(*conditions)
    ).scalar_one()
    pages = max(1, ceil(total / PER_PAGE))
    rows = connection.execute(
        select(
            characters.c.id,
            characters.c.name,
            characters.c.slug,
            characters.c.character_type,
            sources.c.title.label("source_title"),
        )
        .select_from(
            characters.outerjoin(sources, sources.c.id == characters.c.source_id)
        )
        .where(*conditions)
        .order_by(characters.c.name, characters.c.id)
        .limit(PER_PAGE)
        .offset((page - 1) * PER_PAGE)
    ).mappings()
    base = {"q": term} if term else {}
    return templates.TemplateResponse(
        request=request,
        name="admin/characters/list.html",
        context={
            "admin_email": admin_email,
            "rows": rows,
            "q": term,
            "page": page,
            "total": total,
            "notice": notice,
            "previous_url": f"/admin/characters?{urlencode({**base, 'page': page - 1})}"
            if page > 1
            else None,
            "next_url": f"/admin/characters?{urlencode({**base, 'page': page + 1})}"
            if page < pages
            else None,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def character_new(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/characters/form.html",
        context=_context(
            request,
            admin_email,
            connection,
            values={
                "name": "",
                "slug": "",
                "source_id": None,
                "description": None,
                "character_type": "character",
            },
        ),
    )


@router.post("")
async def character_create(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    raw = _input(form)
    try:
        data = CharacterForm.model_validate(raw)
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
    values = data.model_dump()
    values.update(created_at=format_instant(now), updated_at=format_instant(now))
    try:
        with connection.engine.begin() as write:
            character_id = write.execute(
                insert(characters).values(**values)
            ).inserted_primary_key[0]
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "slugの重複または入力内容の制約違反があります。",
        )
    with connection.engine.connect() as read:
        new = _snapshot(read, character_id)
    log_admin_operation(admin_email, "create", f"characters:{character_id}", now=now)
    notice = purge_notice("登場人物", "作成", _paths(None, new), purger=purge_cache)
    return RedirectResponse(
        f"/admin/characters?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{character_id}/edit", response_class=HTMLResponse)
def character_edit(
    character_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _snapshot(connection, character_id)
    if row is None:
        raise HTTPException(status_code=404, detail="登場人物が見つかりません")
    return templates.TemplateResponse(
        request=request,
        name="admin/characters/form.html",
        context=_context(
            request,
            admin_email,
            connection,
            values={key: row[key] for key in CharacterForm.model_fields},
            character_id=character_id,
        ),
    )


@router.post("/{character_id}")
async def character_update(
    character_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _snapshot(connection, character_id)
    if old is None:
        raise HTTPException(status_code=404, detail="登場人物が見つかりません")
    raw = _input(form)
    try:
        data = CharacterForm.model_validate(raw)
    except ValidationError as error:
        return _form_error(
            request, admin_email, connection, raw, _error(error), character_id
        )
    message = _reference_error(connection, data)
    if message:
        return _form_error(
            request, admin_email, connection, data.model_dump(), message, character_id
        )
    if _slug_exists(connection, data.slug, character_id):
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "このslugは既に使われています。",
            character_id,
        )
    now = datetime.now(UTC)
    values = data.model_dump()
    values["updated_at"] = format_instant(now)
    try:
        with connection.engine.begin() as write:
            write.execute(
                update(characters)
                .where(characters.c.id == character_id)
                .values(**values)
            )
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "slugの重複または入力内容の制約違反があります。",
            character_id,
        )
    with connection.engine.connect() as read:
        new = _snapshot(read, character_id)
    log_admin_operation(admin_email, "update", f"characters:{character_id}", now=now)
    notice = purge_notice("登場人物", "更新", _paths(old, new), purger=purge_cache)
    return RedirectResponse(
        f"/admin/characters?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{character_id}/delete", response_class=HTMLResponse)
def character_delete_confirm(
    character_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _snapshot(connection, character_id)
    if row is None:
        raise HTTPException(status_code=404, detail="登場人物が見つかりません")
    count = connection.execute(
        select(func.count())
        .select_from(quotes)
        .where(quotes.c.character_id == character_id)
    ).scalar_one()
    return templates.TemplateResponse(
        request=request,
        name="admin/characters/delete.html",
        context={
            "request": request,
            "admin_email": admin_email,
            "csrf_token": issue_csrf_token(admin_email),
            "character": row,
            "quote_count": count,
        },
    )


@router.post("/{character_id}/delete")
async def character_delete(
    character_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> RedirectResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _snapshot(connection, character_id)
    if old is None:
        raise HTTPException(status_code=404, detail="登場人物が見つかりません")
    with connection.engine.begin() as write:
        write.execute(delete(characters).where(characters.c.id == character_id))
    now = datetime.now(UTC)
    log_admin_operation(admin_email, "delete", f"characters:{character_id}", now=now)
    notice = purge_notice("登場人物", "削除", _paths(old, None), purger=purge_cache)
    return RedirectResponse(
        f"/admin/characters?{urlencode({'notice': notice})}", status_code=303
    )
