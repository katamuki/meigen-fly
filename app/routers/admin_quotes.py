"""Quote administration screens."""

import re
from datetime import UTC, datetime
from math import ceil
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.admin import (
    issue_csrf_token,
    log_admin_operation,
    read_urlencoded_form,
    require_admin,
    require_csrf,
)
from app.db import get_connection
from app.instants import format_instant
from app.routers.admin import templates
from app.schema import (
    authors,
    categories,
    characters,
    quote_categories,
    quote_likes,
    quotes,
    sources,
)
from app.services.cache_purge import CachePurgeStatus, purge_cache
from app.services.quotes import quote_path

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
Notice = Annotated[str | None, Query(max_length=200)]

router = APIRouter(prefix="/admin/quotes", dependencies=[Depends(require_admin)])
PER_PAGE = 20
_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_STRICT_QID_PATTERN = re.compile(r"q[1-9][0-9]*\Z")
_FOUR_DIGIT_PATTERN = re.compile(r"[0-9]{4}\Z")
_RESERVED_SLUGS = {"latest", "page"}


class QuoteForm(BaseModel):
    text: str = Field(max_length=10000)
    text_en: str | None = Field(default=None, max_length=10000)
    author_id: int | None = None
    source_id: int | None = None
    character_id: int | None = None
    weight: int = Field(default=5, ge=1, le=10)
    slug: str | None = Field(default=None, max_length=255)
    enable: bool = True
    context_note: str | None = Field(default=None, max_length=50000)
    display_language_preference: Literal["ja", "en"] = "ja"
    legacy_vote_count: int = Field(default=0, ge=0)
    category_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_content_and_slug(self) -> QuoteForm:
        self.text = self.text.strip()
        self.text_en = _optional_text(self.text_en)
        self.context_note = _optional_text(self.context_note)
        self.slug = _optional_text(self.slug)
        if self.slug is not None:
            self.slug = self.slug.lower()
            if not _SLUG_PATTERN.fullmatch(self.slug):
                raise ValueError("slugは小文字の英数字とハイフンで入力してください。")
            if _STRICT_QID_PATTERN.fullmatch(self.slug):
                raise ValueError(
                    "qの後に正の整数が続く形式は名言ID用に予約されています。"
                )
            if _FOUR_DIGIT_PATTERN.fullmatch(self.slug):
                raise ValueError("4桁の数字だけのslugは旧URL用に予約されています。")
            if self.slug in _RESERVED_SLUGS:
                raise ValueError("latestとpageは公開ページ用に予約されています。")
        if not self.text and not self.text_en:
            raise ValueError("日本語本文または英語本文のどちらかを入力してください。")
        self.category_ids = list(dict.fromkeys(self.category_ids))
        return self


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _one(form: dict[str, list[str]], name: str, default: str = "") -> str:
    values = form.get(name, [])
    return values[0] if len(values) == 1 else default


def _nullable(value: str) -> str | None:
    return value if value != "" else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except TypeError, ValueError:
        return None


def _quote_input(form: dict[str, list[str]]) -> dict:
    return {
        "text": _one(form, "text"),
        "text_en": _nullable(_one(form, "text_en")),
        "author_id": _nullable(_one(form, "author_id")),
        "source_id": _nullable(_one(form, "source_id")),
        "character_id": _nullable(_one(form, "character_id")),
        "weight": _one(form, "weight", "5"),
        "slug": _nullable(_one(form, "slug")),
        "enable": _one(form, "enable") == "1",
        "context_note": _nullable(_one(form, "context_note")),
        "display_language_preference": _one(form, "display_language_preference", "ja"),
        "legacy_vote_count": _one(form, "legacy_vote_count", "0"),
        "category_ids": form.get("category_ids", []),
    }


def _error_message(error: ValidationError) -> str:
    message = error.errors()[0].get("ctx", {}).get("error")
    if message:
        return str(message)
    labels = {
        "weight": "重みは1〜10の整数で入力してください。",
        "legacy_vote_count": "旧票数は0以上の整数で入力してください。",
        "author_id": "著者の選択が不正です。",
        "source_id": "出典の選択が不正です。",
        "character_id": "登場人物の選択が不正です。",
        "category_ids": "カテゴリの選択が不正です。",
        "display_language_preference": "表示言語を選択してください。",
    }
    field = str(error.errors()[0]["loc"][-1])
    return labels.get(field, "入力内容を確認してください。")


def _choices(connection: Connection) -> dict:
    return {
        "authors": connection.execute(
            select(authors.c.id, authors.c.name, authors.c.slug).order_by(
                authors.c.name_reading, authors.c.id
            )
        ).mappings(),
        "sources": connection.execute(
            select(sources.c.id, sources.c.title, sources.c.slug).order_by(
                sources.c.title, sources.c.id
            )
        ).mappings(),
        "characters": connection.execute(
            select(characters.c.id, characters.c.name, characters.c.slug).order_by(
                characters.c.name, characters.c.id
            )
        ).mappings(),
        "categories": connection.execute(
            select(categories.c.id, categories.c.name, categories.c.slug)
            .where(categories.c.level == 2)
            .order_by(categories.c.parent_id, categories.c.sort_order, categories.c.id)
        ).mappings(),
    }


def _form_context(
    request: Request,
    admin_email: str,
    connection: Connection,
    *,
    values: dict,
    quote_id: int | None = None,
    error: str | None = None,
) -> dict:
    selected_categories = {
        parsed
        for value in values.get("category_ids", [])
        if (parsed := _int_or_none(value)) is not None
    }
    return {
        "request": request,
        "admin_email": admin_email,
        "csrf_token": issue_csrf_token(admin_email),
        "values": values,
        "selected_categories": selected_categories,
        "selected_author_id": _int_or_none(values.get("author_id")),
        "selected_source_id": _int_or_none(values.get("source_id")),
        "selected_character_id": _int_or_none(values.get("character_id")),
        "quote_id": quote_id,
        "error": error,
        **_choices(connection),
    }


def _validate_references(connection: Connection, data: QuoteForm) -> str | None:
    checks = (
        (data.author_id, authors, "選択した著者が見つかりません。"),
        (data.source_id, sources, "選択した出典が見つかりません。"),
        (data.character_id, characters, "選択した登場人物が見つかりません。"),
    )
    for value, table, message in checks:
        if (
            value is not None
            and connection.execute(
                select(table.c.id).where(table.c.id == value)
            ).scalar_one_or_none()
            is None
        ):
            return message
    if data.category_ids:
        valid = set(
            connection.execute(
                select(categories.c.id).where(
                    categories.c.id.in_(data.category_ids), categories.c.level == 2
                )
            ).scalars()
        )
        if valid != set(data.category_ids):
            return "カテゴリにはlevel 2だけを選択してください。"
    return None


def _slug_exists(
    connection: Connection, slug: str | None, *, excluding_id: int | None = None
) -> bool:
    if slug is None:
        return False
    query = select(quotes.c.id).where(quotes.c.slug == slug)
    if excluding_id is not None:
        query = query.where(quotes.c.id != excluding_id)
    return connection.execute(query).first() is not None


def _load_quote_snapshot(connection: Connection, quote_id: int) -> dict | None:
    row = (
        connection.execute(
            select(
                quotes,
                authors.c.slug.label("author_slug"),
                sources.c.slug.label("source_slug"),
                characters.c.slug.label("character_slug"),
            )
            .select_from(
                quotes.outerjoin(authors, authors.c.id == quotes.c.author_id)
                .outerjoin(sources, sources.c.id == quotes.c.source_id)
                .outerjoin(characters, characters.c.id == quotes.c.character_id)
            )
            .where(quotes.c.id == quote_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    result["category_slugs"] = list(
        connection.execute(
            select(categories.c.slug)
            .select_from(
                quote_categories.join(
                    categories, categories.c.id == quote_categories.c.category_id
                )
            )
            .where(quote_categories.c.quote_id == quote_id)
        ).scalars()
    )
    return result


def _quote_purge_paths(old: dict | None, new: dict | None, quote_id: int) -> list[str]:
    paths = {"/", "/quotes", "/quotes/latest", "/sitemap.xml"}
    for snapshot in (old, new):
        if snapshot is None:
            continue
        detail = quote_path(snapshot)
        paths.update({detail, f"{detail}/og.png"})
        if snapshot.get("author_slug"):
            paths.add(f"/authors/{snapshot['author_slug']}")
        if snapshot.get("source_slug"):
            paths.add(f"/sources/{snapshot['source_slug']}")
        if snapshot.get("character_slug"):
            paths.add(f"/characters/{snapshot['character_slug']}")
        paths.update(f"/categories/{slug}" for slug in snapshot["category_slugs"])
    old_slug = old.get("slug") if old else None
    new_slug = new.get("slug") if new else None
    if new is not None and old_slug != new_slug:
        paths.add(f"/quotes/q{quote_id}")
    return sorted(paths)


def _purge_notice(action: str, paths: list[str]) -> str:
    result = purge_cache(paths)
    suffix = {
        CachePurgeStatus.SUCCESS: "キャッシュパージ成功。",
        CachePurgeStatus.FAILED: "キャッシュパージ失敗（TTL待ち）。",
        CachePurgeStatus.SKIPPED: "キャッシュパージ未設定のためスキップ。",
    }[result.status]
    return f"名言を{action}しました。{suffix}"


@router.get("", response_class=HTMLResponse)
def quote_list(
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
    q: Annotated[str, Query(max_length=200)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    notice: Notice = None,
) -> HTMLResponse:
    term = q.strip()
    conditions = []
    if term:
        matches = [quotes.c.text.contains(term, autoescape=True)]
        if term.isdecimal():
            matches.append(quotes.c.id == int(term))
        conditions.append(or_(*matches))
    total = connection.execute(
        select(func.count()).select_from(quotes).where(*conditions)
    ).scalar_one()
    total_pages = max(1, ceil(total / PER_PAGE))
    rows = connection.execute(
        select(
            quotes.c.id,
            quotes.c.text,
            quotes.c.text_en,
            quotes.c.slug,
            quotes.c.enable,
            quotes.c.weight,
            authors.c.name.label("author_name"),
        )
        .select_from(quotes.outerjoin(authors, authors.c.id == quotes.c.author_id))
        .where(*conditions)
        .order_by(quotes.c.id.desc())
        .limit(PER_PAGE)
        .offset((page - 1) * PER_PAGE)
    ).mappings()
    query_base = {"q": term} if term else {}
    return templates.TemplateResponse(
        request=request,
        name="admin/quotes/list.html",
        context={
            "admin_email": admin_email,
            "rows": rows,
            "q": term,
            "page": page,
            "total": total,
            "previous_url": (
                f"/admin/quotes?{urlencode({**query_base, 'page': page - 1})}"
                if page > 1
                else None
            ),
            "next_url": (
                f"/admin/quotes?{urlencode({**query_base, 'page': page + 1})}"
                if page < total_pages
                else None
            ),
            "notice": notice,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def quote_new(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    values = {
        "text": "",
        "text_en": None,
        "author_id": None,
        "source_id": None,
        "character_id": None,
        "weight": 5,
        "slug": None,
        "enable": True,
        "context_note": None,
        "display_language_preference": "ja",
        "legacy_vote_count": 0,
        "category_ids": [],
    }
    return templates.TemplateResponse(
        request=request,
        name="admin/quotes/form.html",
        context=_form_context(
            request, admin_email, connection, values=values, quote_id=None
        ),
    )


@router.post("")
async def quote_create(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    raw = _quote_input(form)
    try:
        data = QuoteForm.model_validate(raw)
    except ValidationError as error:
        context = _form_context(
            request,
            admin_email,
            connection,
            values=raw,
            error=_error_message(error),
        )
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/form.html",
            context=context,
            status_code=422,
        )
    reference_error = _validate_references(connection, data)
    if reference_error:
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/form.html",
            context=_form_context(
                request,
                admin_email,
                connection,
                values=data.model_dump(),
                error=reference_error,
            ),
            status_code=422,
        )
    if _slug_exists(connection, data.slug):
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/form.html",
            context=_form_context(
                request,
                admin_email,
                connection,
                values=data.model_dump(),
                error="このslugは既に使われています。",
            ),
            status_code=422,
        )
    now = datetime.now(UTC)
    values = data.model_dump(exclude={"category_ids"})
    values.update(created_at=format_instant(now), updated_at=format_instant(now))
    try:
        with connection.engine.begin() as write_connection:
            quote_id = write_connection.execute(
                insert(quotes).values(**values)
            ).inserted_primary_key[0]
            if data.category_ids:
                write_connection.execute(
                    insert(quote_categories),
                    [
                        {"quote_id": quote_id, "category_id": category_id}
                        for category_id in data.category_ids
                    ],
                )
    except IntegrityError:
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/form.html",
            context=_form_context(
                request,
                admin_email,
                connection,
                values=data.model_dump(),
                error="slugの重複または入力内容の制約違反があります。",
            ),
            status_code=422,
        )
    with connection.engine.connect() as read_connection:
        new = _load_quote_snapshot(read_connection, quote_id)
    log_admin_operation(admin_email, "create", f"quotes:{quote_id}", now=now)
    notice = _purge_notice("作成", _quote_purge_paths(None, new, quote_id))
    return RedirectResponse(
        f"/admin/quotes?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{quote_id}/edit", response_class=HTMLResponse)
def quote_edit(
    quote_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _load_quote_snapshot(connection, quote_id)
    if row is None:
        raise HTTPException(status_code=404, detail="名言が見つかりません")
    values = {key: row[key] for key in QuoteForm.model_fields if key != "category_ids"}
    values["category_ids"] = list(
        connection.execute(
            select(quote_categories.c.category_id).where(
                quote_categories.c.quote_id == quote_id
            )
        ).scalars()
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/quotes/form.html",
        context=_form_context(
            request, admin_email, connection, values=values, quote_id=quote_id
        ),
    )


@router.post("/{quote_id}")
async def quote_update(
    quote_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _load_quote_snapshot(connection, quote_id)
    if old is None:
        raise HTTPException(status_code=404, detail="名言が見つかりません")
    raw = _quote_input(form)
    try:
        data = QuoteForm.model_validate(raw)
    except ValidationError as error:
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/form.html",
            context=_form_context(
                request,
                admin_email,
                connection,
                values=raw,
                quote_id=quote_id,
                error=_error_message(error),
            ),
            status_code=422,
        )
    reference_error = _validate_references(connection, data)
    if reference_error:
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/form.html",
            context=_form_context(
                request,
                admin_email,
                connection,
                values=data.model_dump(),
                quote_id=quote_id,
                error=reference_error,
            ),
            status_code=422,
        )
    if _slug_exists(connection, data.slug, excluding_id=quote_id):
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/form.html",
            context=_form_context(
                request,
                admin_email,
                connection,
                values=data.model_dump(),
                quote_id=quote_id,
                error="このslugは既に使われています。",
            ),
            status_code=422,
        )
    now = datetime.now(UTC)
    values = data.model_dump(exclude={"category_ids"})
    values["updated_at"] = format_instant(now)
    try:
        with connection.engine.begin() as write_connection:
            write_connection.execute(
                update(quotes).where(quotes.c.id == quote_id).values(**values)
            )
            write_connection.execute(
                delete(quote_categories).where(quote_categories.c.quote_id == quote_id)
            )
            if data.category_ids:
                write_connection.execute(
                    insert(quote_categories),
                    [
                        {"quote_id": quote_id, "category_id": category_id}
                        for category_id in data.category_ids
                    ],
                )
    except IntegrityError:
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/form.html",
            context=_form_context(
                request,
                admin_email,
                connection,
                values=data.model_dump(),
                quote_id=quote_id,
                error="slugの重複または入力内容の制約違反があります。",
            ),
            status_code=422,
        )
    with connection.engine.connect() as read_connection:
        new = _load_quote_snapshot(read_connection, quote_id)
    log_admin_operation(admin_email, "update", f"quotes:{quote_id}", now=now)
    notice = _purge_notice("更新", _quote_purge_paths(old, new, quote_id))
    return RedirectResponse(
        f"/admin/quotes?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{quote_id}/delete", response_class=HTMLResponse)
def quote_delete_confirm(
    quote_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _load_quote_snapshot(connection, quote_id)
    if row is None:
        raise HTTPException(status_code=404, detail="名言が見つかりません")
    category_count = connection.execute(
        select(func.count())
        .select_from(quote_categories)
        .where(quote_categories.c.quote_id == quote_id)
    ).scalar_one()
    like_count = connection.execute(
        select(func.count())
        .select_from(quote_likes)
        .where(quote_likes.c.quote_id == quote_id)
    ).scalar_one()
    return templates.TemplateResponse(
        request=request,
        name="admin/quotes/delete.html",
        context={
            "admin_email": admin_email,
            "csrf_token": issue_csrf_token(admin_email),
            "quote": row,
            "category_count": category_count,
            "like_count": like_count,
        },
    )


@router.post("/{quote_id}/delete")
async def quote_delete(
    quote_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> RedirectResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _load_quote_snapshot(connection, quote_id)
    if old is None:
        raise HTTPException(status_code=404, detail="名言が見つかりません")
    with connection.engine.begin() as write_connection:
        write_connection.execute(delete(quotes).where(quotes.c.id == quote_id))
    now = datetime.now(UTC)
    log_admin_operation(admin_email, "delete", f"quotes:{quote_id}", now=now)
    notice = _purge_notice("削除", _quote_purge_paths(old, None, quote_id))
    return RedirectResponse(
        f"/admin/quotes?{urlencode({'notice': notice})}", status_code=303
    )
