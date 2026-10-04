"""Category administration screens."""

import re
from collections.abc import Mapping
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
from app.schema import categories, quote_categories
from app.services.cache_purge import purge_cache

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
Notice = Annotated[str | None, Query(max_length=200)]
router = APIRouter(prefix="/admin/categories", dependencies=[Depends(require_admin)])
PER_PAGE = 20
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class CategoryForm(BaseModel):
    name: str = Field(max_length=1000)
    slug: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=50000)
    sort_order: int = Field(default=0, ge=0)
    level: int = Field(default=1, ge=1, le=2)
    parent_id: int | None = None
    color: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_category(self) -> CategoryForm:
        self.name = self.name.strip()
        self.slug = self.slug.strip().lower()
        self.description = optional_text(self.description)
        self.color = optional_text(self.color)
        if not self.name:
            raise ValueError("カテゴリ名を入力してください。")
        if not self.slug or not SLUG_PATTERN.fullmatch(self.slug):
            raise ValueError("slugは小文字の英数字とハイフンで入力してください。")
        if self.level == 1 and self.parent_id is not None:
            raise ValueError("level 1のカテゴリには親を指定できません。")
        if self.level == 2 and self.parent_id is None:
            raise ValueError("level 2のカテゴリには親カテゴリを指定してください。")
        return self


def _input(form: dict[str, list[str]]) -> dict[str, object]:
    return {
        "name": one(form, "name"),
        "slug": one(form, "slug"),
        "description": nullable(one(form, "description")),
        "sort_order": one(form, "sort_order", "0"),
        "level": one(form, "level", "1"),
        "parent_id": nullable(one(form, "parent_id")),
        "color": nullable(one(form, "color")),
    }


def _error(error: ValidationError) -> str:
    custom = error.errors()[0].get("ctx", {}).get("error")
    if custom:
        return str(custom)
    field = str(error.errors()[0]["loc"][-1])
    return {
        "sort_order": "表示順は0以上の整数で入力してください。",
        "level": "levelは1または2を選択してください。",
        "parent_id": "親カテゴリの選択が不正です。",
    }.get(field, "入力内容を確認してください。")


def _parents(
    connection: Connection, excluding_id: int | None = None
) -> list[Mapping[str, Any]]:
    query = select(categories.c.id, categories.c.name).where(categories.c.level == 1)
    if excluding_id is not None:
        query = query.where(categories.c.id != excluding_id)
    return list(
        connection.execute(
            query.order_by(categories.c.sort_order, categories.c.id)
        ).mappings()
    )


def _context(
    request: Request,
    email: str,
    connection: Connection,
    *,
    values: dict[str, Any],
    category_id: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "request": request,
        "admin_email": email,
        "csrf_token": issue_csrf_token(email),
        "values": values,
        "category_id": category_id,
        "selected_parent_id": int_or_none(values.get("parent_id")),
        "parents": _parents(connection, category_id),
        "error": error,
    }


def _snapshot(connection: Connection, category_id: int) -> dict[str, Any] | None:
    parent = categories.alias("parent")
    row = (
        connection.execute(
            select(categories, parent.c.slug.label("parent_slug"))
            .select_from(
                categories.outerjoin(parent, parent.c.id == categories.c.parent_id)
            )
            .where(categories.c.id == category_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result["child_slugs"] = list(
        connection.execute(
            select(categories.c.slug).where(categories.c.parent_id == category_id)
        ).scalars()
    )
    return result


def _slug_exists(
    connection: Connection, slug: str, excluding_id: int | None = None
) -> bool:
    query = select(categories.c.id).where(categories.c.slug == slug)
    if excluding_id is not None:
        query = query.where(categories.c.id != excluding_id)
    return connection.execute(query).first() is not None


def _hierarchy_error(
    connection: Connection,
    data: CategoryForm,
    category_id: int | None = None,
    old: dict[str, Any] | None = None,
) -> str | None:
    if data.level == 2:
        if category_id is not None and data.parent_id == category_id:
            return "level 2カテゴリ自身を親には指定できません。"
        parent = connection.execute(
            select(categories.c.level).where(categories.c.id == data.parent_id)
        ).scalar_one_or_none()
        if parent != 1:
            return "level 2カテゴリの親にはlevel 1カテゴリを指定してください。"
    if category_id is not None and old and data.level != old["level"]:
        child_count = connection.execute(
            select(func.count())
            .select_from(categories)
            .where(categories.c.parent_id == category_id)
        ).scalar_one()
        quote_count = connection.execute(
            select(func.count())
            .select_from(quote_categories)
            .where(quote_categories.c.category_id == category_id)
        ).scalar_one()
        if child_count:
            return "子カテゴリがあるためlevel 2へ変更できません。"
        if quote_count:
            return "名言が関連付いているためlevel 1へ変更できません。"
    return None


def _paths(old: dict[str, Any] | None, new: dict[str, Any] | None) -> list[str]:
    paths = {"/categories", "/sitemap.xml"}
    for snapshot in (old, new):
        if snapshot:
            paths.add(f"/categories/{snapshot['slug']}")
            if snapshot.get("parent_slug"):
                paths.add(f"/categories/{snapshot['parent_slug']}")
            paths.update(
                f"/categories/{slug}" for slug in snapshot.get("child_slugs", [])
            )
    return sorted(paths)


def _form_error(
    request: Request,
    email: str,
    connection: Connection,
    values: dict[str, Any],
    message: str,
    category_id: int | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/categories/form.html",
        context=_context(
            request,
            email,
            connection,
            values=values,
            category_id=category_id,
            error=message,
        ),
        status_code=422,
    )


@router.get("", response_class=HTMLResponse)
def category_list(
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
                categories.c.name.contains(term, autoescape=True),
                categories.c.slug.contains(term, autoescape=True),
            )
        ]
        if term
        else []
    )
    total = connection.execute(
        select(func.count()).select_from(categories).where(*conditions)
    ).scalar_one()
    total_pages = max(1, ceil(total / PER_PAGE))
    parent = categories.alias("parent")
    rows = connection.execute(
        select(
            categories.c.id,
            categories.c.name,
            categories.c.slug,
            categories.c.level,
            categories.c.sort_order,
            parent.c.name.label("parent_name"),
        )
        .select_from(
            categories.outerjoin(parent, parent.c.id == categories.c.parent_id)
        )
        .where(*conditions)
        .order_by(
            categories.c.level,
            categories.c.parent_id,
            categories.c.sort_order,
            categories.c.id,
        )
        .limit(PER_PAGE)
        .offset((page - 1) * PER_PAGE)
    ).mappings()
    base = {"q": term} if term else {}
    return templates.TemplateResponse(
        request=request,
        name="admin/categories/list.html",
        context={
            "admin_email": admin_email,
            "rows": rows,
            "q": term,
            "page": page,
            "total": total,
            "notice": notice,
            "previous_url": f"/admin/categories?{urlencode({**base, 'page': page - 1})}"
            if page > 1
            else None,
            "next_url": f"/admin/categories?{urlencode({**base, 'page': page + 1})}"
            if page < total_pages
            else None,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def category_new(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/categories/form.html",
        context=_context(
            request,
            admin_email,
            connection,
            values={
                "name": "",
                "slug": "",
                "description": None,
                "sort_order": 0,
                "level": 1,
                "parent_id": None,
                "color": None,
            },
        ),
    )


@router.post("")
async def category_create(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    raw = _input(form)
    try:
        data = CategoryForm.model_validate(raw)
    except ValidationError as error:
        return _form_error(request, admin_email, connection, raw, _error(error))
    hierarchy_error = _hierarchy_error(connection, data)
    if hierarchy_error:
        return _form_error(
            request, admin_email, connection, data.model_dump(), hierarchy_error
        )
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
            category_id = write.execute(
                insert(categories).values(**values)
            ).inserted_primary_key[0]
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "カテゴリ階層または入力内容の制約違反があります。",
        )
    with connection.engine.connect() as read:
        new = _snapshot(read, category_id)
    log_admin_operation(admin_email, "create", f"categories:{category_id}", now=now)
    notice = purge_notice("カテゴリ", "作成", _paths(None, new), purger=purge_cache)
    return RedirectResponse(
        f"/admin/categories?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{category_id}/edit", response_class=HTMLResponse)
def category_edit(
    category_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _snapshot(connection, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="カテゴリが見つかりません")
    return templates.TemplateResponse(
        request=request,
        name="admin/categories/form.html",
        context=_context(
            request,
            admin_email,
            connection,
            values={key: row[key] for key in CategoryForm.model_fields},
            category_id=category_id,
        ),
    )


@router.post("/{category_id}")
async def category_update(
    category_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _snapshot(connection, category_id)
    if old is None:
        raise HTTPException(status_code=404, detail="カテゴリが見つかりません")
    raw = _input(form)
    try:
        data = CategoryForm.model_validate(raw)
    except ValidationError as error:
        return _form_error(
            request, admin_email, connection, raw, _error(error), category_id
        )
    message = _hierarchy_error(connection, data, category_id, old)
    if message:
        return _form_error(
            request, admin_email, connection, data.model_dump(), message, category_id
        )
    if _slug_exists(connection, data.slug, category_id):
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "このslugは既に使われています。",
            category_id,
        )
    now = datetime.now(UTC)
    values = data.model_dump()
    values["updated_at"] = format_instant(now)
    try:
        with connection.engine.begin() as write:
            write.execute(
                update(categories)
                .where(categories.c.id == category_id)
                .values(**values)
            )
    except IntegrityError:
        return _form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "カテゴリ階層または入力内容の制約違反があります。",
            category_id,
        )
    with connection.engine.connect() as read:
        new = _snapshot(read, category_id)
    log_admin_operation(admin_email, "update", f"categories:{category_id}", now=now)
    notice = purge_notice("カテゴリ", "更新", _paths(old, new), purger=purge_cache)
    return RedirectResponse(
        f"/admin/categories?{urlencode({'notice': notice})}", status_code=303
    )


def _delete_context(
    request: Request,
    email: str,
    row: dict[str, Any],
    quote_count: int,
    child_count: int,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "request": request,
        "admin_email": email,
        "csrf_token": issue_csrf_token(email),
        "category": row,
        "quote_count": quote_count,
        "child_count": child_count,
        "error": error,
    }


@router.get("/{category_id}/delete", response_class=HTMLResponse)
def category_delete_confirm(
    category_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _snapshot(connection, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="カテゴリが見つかりません")
    quote_count = connection.execute(
        select(func.count())
        .select_from(quote_categories)
        .where(quote_categories.c.category_id == category_id)
    ).scalar_one()
    child_count = connection.execute(
        select(func.count())
        .select_from(categories)
        .where(categories.c.parent_id == category_id)
    ).scalar_one()
    return templates.TemplateResponse(
        request=request,
        name="admin/categories/delete.html",
        context=_delete_context(request, admin_email, row, quote_count, child_count),
    )


@router.post("/{category_id}/delete")
async def category_delete(
    category_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _snapshot(connection, category_id)
    if old is None:
        raise HTTPException(status_code=404, detail="カテゴリが見つかりません")
    child_count = connection.execute(
        select(func.count())
        .select_from(categories)
        .where(categories.c.parent_id == category_id)
    ).scalar_one()
    quote_count = connection.execute(
        select(func.count())
        .select_from(quote_categories)
        .where(quote_categories.c.category_id == category_id)
    ).scalar_one()
    if child_count:
        return templates.TemplateResponse(
            request=request,
            name="admin/categories/delete.html",
            context=_delete_context(
                request,
                admin_email,
                old,
                quote_count,
                child_count,
                "子カテゴリがあるため削除できません。",
            ),
            status_code=422,
        )
    try:
        with connection.engine.begin() as write:
            write.execute(delete(categories).where(categories.c.id == category_id))
    except IntegrityError:
        return templates.TemplateResponse(
            request=request,
            name="admin/categories/delete.html",
            context=_delete_context(
                request,
                admin_email,
                old,
                quote_count,
                child_count,
                "関連データがあるため削除できません。",
            ),
            status_code=422,
        )
    now = datetime.now(UTC)
    log_admin_operation(admin_email, "delete", f"categories:{category_id}", now=now)
    notice = purge_notice("カテゴリ", "削除", _paths(old, None), purger=purge_cache)
    return RedirectResponse(
        f"/admin/categories?{urlencode({'notice': notice})}", status_code=303
    )
