"""Profession administration screen."""

import re
from datetime import UTC, datetime
from math import ceil
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.admin import (
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
from app.schema import author_professions, professions
from app.services.cache_purge import purge_cache

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
Notice = Annotated[str | None, Query(max_length=200)]
router = APIRouter(prefix="/admin/professions", dependencies=[Depends(require_admin)])
PER_PAGE = 20
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class ProfessionForm(BaseModel):
    name: str = Field(max_length=1000)
    slug: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=50000)
    display_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_profession(self) -> ProfessionForm:
        self.name = self.name.strip()
        self.slug = self.slug.strip().lower()
        self.description = optional_text(self.description)
        if not self.name:
            raise ValueError("職業名を入力してください。")
        if not self.slug or not SLUG_PATTERN.fullmatch(self.slug):
            raise ValueError("slugは小文字の英数字とハイフンで入力してください。")
        return self


def _input(form: dict[str, list[str]]) -> dict[str, object]:
    return {
        "name": one(form, "name"),
        "slug": one(form, "slug"),
        "description": nullable(one(form, "description")),
        "display_order": one(form, "display_order", "0"),
    }


def _error(error: ValidationError) -> str:
    custom = error.errors()[0].get("ctx", {}).get("error")
    if custom:
        return str(custom)
    if str(error.errors()[0]["loc"][-1]) == "display_order":
        return "表示順は0以上の整数で入力してください。"
    return "入力内容を確認してください。"


def _snapshot(connection: Connection, profession_id: int) -> dict[str, Any] | None:
    row = (
        connection.execute(select(professions).where(professions.c.id == profession_id))
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _duplicate(
    connection: Connection,
    field: Any,
    value: str,
    excluding_id: int | None = None,
) -> bool:
    query = select(professions.c.id).where(field == value)
    if excluding_id is not None:
        query = query.where(professions.c.id != excluding_id)
    return connection.execute(query).first() is not None


def _paths(old: dict[str, Any] | None, new: dict[str, Any] | None) -> list[str]:
    paths = {"/professions"}
    for item in (old, new):
        if item:
            paths.add(f"/professions/{item['slug']}")
    return sorted(paths)


def _form_context(
    request: Request,
    email: str,
    *,
    values: dict[str, object],
    profession_id: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "request": request,
        "admin_email": email,
        "csrf_token": issue_csrf_token(email),
        "values": values,
        "profession_id": profession_id,
        "error": error,
    }


def _form_error(
    request: Request,
    email: str,
    values: dict[str, object],
    message: str,
    profession_id: int | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/professions/form.html",
        context=_form_context(
            request, email, values=values, profession_id=profession_id, error=message
        ),
        status_code=422,
    )


@router.get("", response_class=HTMLResponse)
def profession_list(
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
    q: Annotated[str, Query(max_length=200)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    notice: Notice = None,
) -> HTMLResponse:
    term = q.strip()
    conditions = [professions.c.name.contains(term, autoescape=True)] if term else []
    total = connection.execute(
        select(func.count()).select_from(professions).where(*conditions)
    ).scalar_one()
    total_pages = max(1, ceil(total / PER_PAGE))
    rows = connection.execute(
        select(
            professions,
            func.count(author_professions.c.author_id).label("author_count"),
        )
        .select_from(
            professions.outerjoin(
                author_professions,
                author_professions.c.profession_id == professions.c.id,
            )
        )
        .where(*conditions)
        .group_by(professions.c.id)
        .order_by(professions.c.display_order, professions.c.id)
        .limit(PER_PAGE)
        .offset((page - 1) * PER_PAGE)
    ).mappings()
    query_base = {"q": term} if term else {}
    return templates.TemplateResponse(
        request=request,
        name="admin/professions/list.html",
        context={
            "request": request,
            "admin_email": admin_email,
            "rows": rows,
            "q": term,
            "page": page,
            "total": total,
            "previous_url": (
                f"/admin/professions?{urlencode({**query_base, 'page': page - 1})}"
                if page > 1
                else None
            ),
            "next_url": (
                f"/admin/professions?{urlencode({**query_base, 'page': page + 1})}"
                if page < total_pages
                else None
            ),
            "notice": notice,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def profession_new(request: Request, admin_email: AdminEmail) -> HTMLResponse:
    values = {"name": "", "slug": "", "description": None, "display_order": 0}
    return templates.TemplateResponse(
        request=request,
        name="admin/professions/form.html",
        context=_form_context(request, admin_email, values=values),
    )


@router.post("")
async def profession_create(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    raw = _input(form)
    try:
        data = ProfessionForm.model_validate(raw)
    except ValidationError as error:
        return _form_error(request, admin_email, raw, _error(error))
    if _duplicate(connection, professions.c.name, data.name):
        return _form_error(
            request,
            admin_email,
            data.model_dump(),
            "この名称は既に使われています。",
        )
    if _duplicate(connection, professions.c.slug, data.slug):
        return _form_error(
            request,
            admin_email,
            data.model_dump(),
            "このslugは既に使われています。",
        )
    now = datetime.now(UTC)
    values = data.model_dump()
    values.update(created_at=format_instant(now), updated_at=format_instant(now))
    try:
        with connection.engine.begin() as write:
            profession_id = write.execute(
                insert(professions).values(**values)
            ).inserted_primary_key[0]
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            data.model_dump(),
            "名称またはslugの重複、入力内容の制約違反があります。",
        )
    with connection.engine.connect() as read:
        new = _snapshot(read, profession_id)
    log_admin_operation(admin_email, "create", f"professions:{profession_id}", now=now)
    notice = purge_notice("職業", "作成", _paths(None, new), purger=purge_cache)
    return RedirectResponse(
        f"/admin/professions?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{profession_id}/edit", response_class=HTMLResponse)
def profession_edit(
    profession_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _snapshot(connection, profession_id)
    if row is None:
        raise HTTPException(status_code=404, detail="職業が見つかりません")
    values = {key: row[key] for key in ProfessionForm.model_fields}
    return templates.TemplateResponse(
        request=request,
        name="admin/professions/form.html",
        context=_form_context(
            request, admin_email, values=values, profession_id=profession_id
        ),
    )


@router.post("/{profession_id}")
async def profession_update(
    profession_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _snapshot(connection, profession_id)
    if old is None:
        raise HTTPException(status_code=404, detail="職業が見つかりません")
    raw = _input(form)
    try:
        data = ProfessionForm.model_validate(raw)
    except ValidationError as error:
        return _form_error(request, admin_email, raw, _error(error), profession_id)
    if _duplicate(connection, professions.c.name, data.name, profession_id):
        return _form_error(
            request,
            admin_email,
            data.model_dump(),
            "この名称は既に使われています。",
            profession_id,
        )
    if _duplicate(connection, professions.c.slug, data.slug, profession_id):
        return _form_error(
            request,
            admin_email,
            data.model_dump(),
            "このslugは既に使われています。",
            profession_id,
        )
    now = datetime.now(UTC)
    values = data.model_dump()
    values["updated_at"] = format_instant(now)
    try:
        with connection.engine.begin() as write:
            write.execute(
                update(professions)
                .where(professions.c.id == profession_id)
                .values(**values)
            )
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            data.model_dump(),
            "名称またはslugの重複、入力内容の制約違反があります。",
            profession_id,
        )
    with connection.engine.connect() as read:
        new = _snapshot(read, profession_id)
    log_admin_operation(admin_email, "update", f"professions:{profession_id}", now=now)
    notice = purge_notice("職業", "更新", _paths(old, new), purger=purge_cache)
    return RedirectResponse(
        f"/admin/professions?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{profession_id}/delete", response_class=HTMLResponse)
def profession_delete_confirm(
    profession_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _snapshot(connection, profession_id)
    if row is None:
        raise HTTPException(status_code=404, detail="職業が見つかりません")
    count = connection.execute(
        select(func.count())
        .select_from(author_professions)
        .where(author_professions.c.profession_id == profession_id)
    ).scalar_one()
    return templates.TemplateResponse(
        request=request,
        name="admin/professions/delete.html",
        context={
            "request": request,
            "admin_email": admin_email,
            "csrf_token": issue_csrf_token(admin_email),
            "profession": row,
            "author_count": count,
        },
    )


@router.post("/{profession_id}/delete")
async def profession_delete(
    profession_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> RedirectResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _snapshot(connection, profession_id)
    if old is None:
        raise HTTPException(status_code=404, detail="職業が見つかりません")
    with connection.engine.begin() as write:
        write.execute(delete(professions).where(professions.c.id == profession_id))
    now = datetime.now(UTC)
    log_admin_operation(admin_email, "delete", f"professions:{profession_id}", now=now)
    notice = purge_notice("職業", "削除", _paths(old, None), purger=purge_cache)
    return RedirectResponse(
        f"/admin/professions?{urlencode({'notice': notice})}", status_code=303
    )
