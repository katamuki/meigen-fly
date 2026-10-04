"""Profession administration screen."""

import re
from datetime import UTC, datetime
from typing import Annotated
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
from app.schema import author_professions, authors, professions
from app.services.cache_purge import purge_cache

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
Notice = Annotated[str | None, Query(max_length=200)]
router = APIRouter(prefix="/admin/professions", dependencies=[Depends(require_admin)])
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


def _input(form):
    return {
        "name": one(form, "name"),
        "slug": one(form, "slug"),
        "description": nullable(one(form, "description")),
        "display_order": one(form, "display_order", "0"),
    }


def _error(error):
    custom = error.errors()[0].get("ctx", {}).get("error")
    if custom:
        return str(custom)
    if str(error.errors()[0]["loc"][-1]) == "display_order":
        return "表示順は0以上の整数で入力してください。"
    return "入力内容を確認してください。"


def _snapshot(connection, profession_id):
    row = (
        connection.execute(select(professions).where(professions.c.id == profession_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result["author_slugs"] = list(
        connection.execute(
            select(authors.c.slug)
            .select_from(
                author_professions.join(
                    authors, authors.c.id == author_professions.c.author_id
                )
            )
            .where(author_professions.c.profession_id == profession_id)
        ).scalars()
    )
    return result


def _duplicate(connection, field, value, excluding_id=None):
    query = select(professions.c.id).where(field == value)
    if excluding_id is not None:
        query = query.where(professions.c.id != excluding_id)
    return connection.execute(query).first() is not None


def _paths(old, new):
    paths = {"/professions"}
    for item in (old, new):
        if item:
            paths.add(f"/professions/{item['slug']}")
            paths.update(f"/authors/{slug}" for slug in item["author_slugs"])
    return sorted(paths)


def _list_context(
    request, email, connection, *, notice=None, error=None, values=None, editing_id=None
):
    rows = list(
        connection.execute(
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
            .group_by(professions.c.id)
            .order_by(professions.c.display_order, professions.c.id)
        ).mappings()
    )
    defaults = {"name": "", "slug": "", "description": None, "display_order": 0}
    return {
        "request": request,
        "admin_email": email,
        "csrf_token": issue_csrf_token(email),
        "rows": rows,
        "notice": notice,
        "error": error,
        "create_values": values if editing_id is None and values else defaults,
        "edit_values": values if editing_id is not None else None,
        "editing_id": editing_id,
    }


def _form_error(request, email, connection, values, message, editing_id=None):
    return templates.TemplateResponse(
        request=request,
        name="admin/professions/list.html",
        context=_list_context(
            request,
            email,
            connection,
            error=message,
            values=values,
            editing_id=editing_id,
        ),
        status_code=422,
    )


@router.get("", response_class=HTMLResponse)
def profession_list(
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
    notice: Notice = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/professions/list.html",
        context=_list_context(request, admin_email, connection, notice=notice),
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
        return _form_error(request, admin_email, connection, raw, _error(error))
    if _duplicate(connection, professions.c.name, data.name):
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "この名称は既に使われています。",
        )
    if _duplicate(connection, professions.c.slug, data.slug):
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
            profession_id = write.execute(
                insert(professions).values(**values)
            ).inserted_primary_key[0]
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            connection,
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
        return _form_error(
            request, admin_email, connection, raw, _error(error), profession_id
        )
    if _duplicate(connection, professions.c.name, data.name, profession_id):
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "この名称は既に使われています。",
            profession_id,
        )
    if _duplicate(connection, professions.c.slug, data.slug, profession_id):
        return _form_error(
            request,
            admin_email,
            connection,
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
            connection,
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
