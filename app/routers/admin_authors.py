"""Author administration screens."""

import calendar
import re
from datetime import UTC, date, datetime
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
    author_country,
    author_professions,
    authors,
    countries,
    professions,
    quotes,
    sources,
)
from app.services.cache_purge import purge_cache

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
Notice = Annotated[str | None, Query(max_length=200)]

router = APIRouter(prefix="/admin/authors", dependencies=[Depends(require_admin)])
PER_PAGE = 20
_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_DATE_PATTERN = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
_RESERVED_SLUGS = {"places"}


class AuthorForm(BaseModel):
    name: str = Field(max_length=1000)
    slug: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=50000)
    image_url: str | None = Field(default=None, max_length=2000)
    name_kana: str | None = Field(default=None, max_length=255)
    name_foreign: str | None = Field(default=None, max_length=255)
    name_reading: str | None = Field(default=None, max_length=255)
    birth_date: str | None = None
    birth_era: Literal["bc", "ad"] = "ad"
    birth_precision: Literal["day", "month", "year", "unknown"] = "unknown"
    death_date: str | None = None
    death_era: Literal["bc", "ad"] = "ad"
    death_precision: Literal["day", "month", "year", "unknown"] = "unknown"
    profession_ids: list[int] = Field(default_factory=list)
    country_ids: list[int] = Field(default_factory=list)
    birth_country_id: int | None = None

    @model_validator(mode="after")
    def validate_author(self) -> AuthorForm:
        self.name = self.name.strip()
        self.slug = self.slug.strip().lower()
        for field in (
            "description",
            "image_url",
            "name_kana",
            "name_foreign",
            "name_reading",
            "birth_date",
            "death_date",
        ):
            setattr(self, field, optional_text(getattr(self, field)))
        if not self.name:
            raise ValueError("著者名を入力してください。")
        if not self.slug or not _SLUG_PATTERN.fullmatch(self.slug):
            raise ValueError("slugは小文字の英数字とハイフンで入力してください。")
        if self.slug in _RESERVED_SLUGS:
            raise ValueError("placesは公開ページ用に予約されています。")
        _validate_life_date("生年月日", self.birth_date, self.birth_precision)
        _validate_life_date("没年月日", self.death_date, self.death_precision)
        if self.birth_date and self.death_date:
            birth_start, _birth_end = _date_interval(
                self.birth_date, self.birth_era, self.birth_precision
            )
            _death_start, death_end = _date_interval(
                self.death_date, self.death_era, self.death_precision
            )
            if birth_start > death_end:
                raise ValueError("生年月日は没年月日以前にしてください。")
        self.profession_ids = list(dict.fromkeys(self.profession_ids))
        self.country_ids = list(dict.fromkeys(self.country_ids))
        if (
            self.birth_country_id is not None
            and self.birth_country_id not in self.country_ids
        ):
            raise ValueError("生誕国は選択した国の中から指定してください。")
        return self


def _validate_life_date(label: str, value: str | None, precision: str) -> None:
    if precision == "unknown":
        if value is not None:
            raise ValueError(f"{label}が不明の場合は日付を空欄にしてください。")
        return
    if value is None:
        raise ValueError(f"{label}の精度を指定した場合は日付も入力してください。")
    match = _DATE_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"{label}はYYYY-MM-DD形式で入力してください。")
    year, month, day = (int(part) for part in match.groups())
    try:
        date(year, month, day)
    except ValueError as error:
        raise ValueError(f"{label}に存在する日付を入力してください。") from error


def _date_interval(value: str, era: str, precision: str) -> tuple[tuple, tuple]:
    year, month, day = (int(part) for part in value.split("-"))
    signed_year = -year if era == "bc" else year
    if precision == "year":
        return (signed_year, 1, 1), (signed_year, 12, 31)
    if precision == "month":
        return (signed_year, month, 1), (
            signed_year,
            month,
            calendar.monthrange(year, month)[1],
        )
    point = (signed_year, month, day)
    return point, point


def _profession_ids(form: dict[str, list[str]]) -> list[str]:
    ids = form.get("profession_ids", [])
    ordered: list[tuple[int, str]] = []
    used_orders: set[int] = set()
    for profession_id in ids:
        order_text = one(form, f"profession_order_{profession_id}")
        try:
            order = int(order_text)
        except ValueError as error:
            raise ValueError("選択した職業の表示順を入力してください。") from error
        if order < 1 or order in used_orders:
            raise ValueError("職業の表示順は重複しない1以上の整数にしてください。")
        used_orders.add(order)
        ordered.append((order, profession_id))
    return [profession_id for _order, profession_id in sorted(ordered)]


def _author_input_values(form: dict[str, list[str]]) -> dict:
    return {
        "name": one(form, "name"),
        "slug": one(form, "slug"),
        "description": nullable(one(form, "description")),
        "image_url": nullable(one(form, "image_url")),
        "name_kana": nullable(one(form, "name_kana")),
        "name_foreign": nullable(one(form, "name_foreign")),
        "name_reading": nullable(one(form, "name_reading")),
        "birth_date": nullable(one(form, "birth_date")),
        "birth_era": one(form, "birth_era", "ad"),
        "birth_precision": one(form, "birth_precision", "unknown"),
        "death_date": nullable(one(form, "death_date")),
        "death_era": one(form, "death_era", "ad"),
        "death_precision": one(form, "death_precision", "unknown"),
        "profession_ids": form.get("profession_ids", []),
        "country_ids": form.get("country_ids", []),
        "birth_country_id": nullable(one(form, "birth_country_id")),
        "_profession_orders": {
            int_or_none(profession_id): one(form, f"profession_order_{profession_id}")
            for profession_id in form.get("profession_ids", [])
            if int_or_none(profession_id) is not None
        },
    }


def _parse_author_input(form: dict[str, list[str]], values: dict) -> AuthorForm:
    if len(form.get("birth_country_id", [])) > 1:
        raise ValueError("生誕国は1件だけ指定してください。")
    values["profession_ids"] = _profession_ids(form)
    return AuthorForm.model_validate(values)


def _error_message(error: ValidationError) -> str:
    message = error.errors()[0].get("ctx", {}).get("error")
    if message:
        return str(message)
    return "入力内容を確認してください。"


def _choices(connection: Connection) -> dict:
    return {
        "professions": list(
            connection.execute(
                select(
                    professions.c.id, professions.c.name, professions.c.slug
                ).order_by(professions.c.display_order, professions.c.id)
            ).mappings()
        ),
        "countries": list(
            connection.execute(
                select(countries.c.id, countries.c.name, countries.c.slug).order_by(
                    countries.c.name, countries.c.id
                )
            ).mappings()
        ),
    }


def _form_context(
    request: Request,
    admin_email: str,
    connection: Connection,
    *,
    values: dict,
    author_id: int | None = None,
    error: str | None = None,
) -> dict:
    profession_ids = [
        parsed
        for value in values.get("profession_ids", [])
        if (parsed := int_or_none(value)) is not None
    ]
    country_ids = {
        parsed
        for value in values.get("country_ids", [])
        if (parsed := int_or_none(value)) is not None
    }
    submitted_orders = values.get("_profession_orders", {})
    return {
        "request": request,
        "admin_email": admin_email,
        "csrf_token": issue_csrf_token(admin_email),
        "values": values,
        "selected_professions": set(profession_ids),
        "profession_orders": submitted_orders
        or {
            profession_id: order
            for order, profession_id in enumerate(profession_ids, start=1)
        },
        "selected_countries": country_ids,
        "selected_birth_country_id": int_or_none(values.get("birth_country_id")),
        "author_id": author_id,
        "error": error,
        **_choices(connection),
    }


def _validate_references(connection: Connection, data: AuthorForm) -> str | None:
    if data.profession_ids:
        valid_professions = set(
            connection.execute(
                select(professions.c.id).where(
                    professions.c.id.in_(data.profession_ids)
                )
            ).scalars()
        )
        if valid_professions != set(data.profession_ids):
            return "選択した職業が見つかりません。"
    if data.country_ids:
        valid_countries = set(
            connection.execute(
                select(countries.c.id).where(countries.c.id.in_(data.country_ids))
            ).scalars()
        )
        if valid_countries != set(data.country_ids):
            return "選択した国が見つかりません。"
    return None


def _slug_exists(
    connection: Connection, slug: str, *, excluding_id: int | None = None
) -> bool:
    query = select(authors.c.id).where(authors.c.slug == slug)
    if excluding_id is not None:
        query = query.where(authors.c.id != excluding_id)
    return connection.execute(query).first() is not None


def _load_author_snapshot(connection: Connection, author_id: int) -> dict | None:
    row = (
        connection.execute(select(authors).where(authors.c.id == author_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    result = dict(row)
    profession_rows = list(
        connection.execute(
            select(
                author_professions.c.profession_id,
                author_professions.c.display_order,
                professions.c.slug,
            )
            .select_from(
                author_professions.join(
                    professions,
                    professions.c.id == author_professions.c.profession_id,
                )
            )
            .where(author_professions.c.author_id == author_id)
            .order_by(author_professions.c.display_order)
        ).mappings()
    )
    country_rows = list(
        connection.execute(
            select(
                author_country.c.country_id,
                author_country.c.is_birth_country,
                countries.c.slug,
            )
            .select_from(
                author_country.join(
                    countries, countries.c.id == author_country.c.country_id
                )
            )
            .where(author_country.c.author_id == author_id)
        ).mappings()
    )
    result["profession_ids"] = [row["profession_id"] for row in profession_rows]
    result["profession_slugs"] = [row["slug"] for row in profession_rows]
    result["country_ids"] = [row["country_id"] for row in country_rows]
    result["country_slugs"] = [row["slug"] for row in country_rows]
    result["birth_country_id"] = next(
        (row["country_id"] for row in country_rows if row["is_birth_country"]),
        None,
    )
    return result


def _author_purge_paths(old: dict | None, new: dict | None) -> list[str]:
    paths = {"/authors", "/sitemap.xml"}
    for snapshot in (old, new):
        if snapshot is None:
            continue
        detail = f"/authors/{snapshot['slug']}"
        paths.update({detail, f"{detail}/og.png"})
        paths.update(f"/authors/places/{slug}" for slug in snapshot["country_slugs"])
        paths.update(f"/professions/{slug}" for slug in snapshot["profession_slugs"])
    return sorted(paths)


@router.get("", response_class=HTMLResponse)
def author_list(
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
        conditions.append(
            or_(
                authors.c.name.contains(term, autoescape=True),
                authors.c.name_kana.contains(term, autoescape=True),
                authors.c.name_foreign.contains(term, autoescape=True),
            )
        )
    total = connection.execute(
        select(func.count()).select_from(authors).where(*conditions)
    ).scalar_one()
    total_pages = max(1, ceil(total / PER_PAGE))
    quote_count = (
        select(func.count())
        .select_from(quotes)
        .where(quotes.c.author_id == authors.c.id)
        .correlate(authors)
        .scalar_subquery()
    )
    rows = connection.execute(
        select(
            authors.c.id,
            authors.c.name,
            authors.c.slug,
            authors.c.name_reading,
            quote_count.label("quote_count"),
        )
        .where(*conditions)
        .order_by(authors.c.id.desc())
        .limit(PER_PAGE)
        .offset((page - 1) * PER_PAGE)
    ).mappings()
    query_base = {"q": term} if term else {}
    return templates.TemplateResponse(
        request=request,
        name="admin/authors/list.html",
        context={
            "admin_email": admin_email,
            "rows": rows,
            "q": term,
            "page": page,
            "total": total,
            "previous_url": (
                f"/admin/authors?{urlencode({**query_base, 'page': page - 1})}"
                if page > 1
                else None
            ),
            "next_url": (
                f"/admin/authors?{urlencode({**query_base, 'page': page + 1})}"
                if page < total_pages
                else None
            ),
            "notice": notice,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def author_new(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    values = {
        "name": "",
        "slug": "",
        "description": None,
        "image_url": None,
        "name_kana": None,
        "name_foreign": None,
        "name_reading": None,
        "birth_date": None,
        "birth_era": "ad",
        "birth_precision": "unknown",
        "death_date": None,
        "death_era": "ad",
        "death_precision": "unknown",
        "profession_ids": [],
        "country_ids": [],
        "birth_country_id": None,
    }
    return templates.TemplateResponse(
        request=request,
        name="admin/authors/form.html",
        context=_form_context(request, admin_email, connection, values=values),
    )


def _author_values(data: AuthorForm, now: datetime, *, create: bool) -> dict:
    values = data.model_dump(
        exclude={"profession_ids", "country_ids", "birth_country_id"}
    )
    values["updated_at"] = format_instant(now)
    if create:
        values["created_at"] = format_instant(now)
    return values


def _write_relations(
    connection: Connection, author_id: int, data: AuthorForm, now: datetime
) -> None:
    instant = format_instant(now)
    if data.profession_ids:
        connection.execute(
            insert(author_professions),
            [
                {
                    "author_id": author_id,
                    "profession_id": profession_id,
                    "display_order": order,
                    "created_at": instant,
                }
                for order, profession_id in enumerate(data.profession_ids, start=1)
            ],
        )
    if data.country_ids:
        connection.execute(
            insert(author_country),
            [
                {
                    "author_id": author_id,
                    "country_id": country_id,
                    "is_birth_country": int(country_id == data.birth_country_id),
                    "created_at": instant,
                }
                for country_id in data.country_ids
            ],
        )


def _author_form_error(
    request: Request,
    admin_email: str,
    connection: Connection,
    values: dict,
    message: str,
    author_id: int | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/authors/form.html",
        context=_form_context(
            request,
            admin_email,
            connection,
            values=values,
            author_id=author_id,
            error=message,
        ),
        status_code=422,
    )


@router.post("")
async def author_create(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    raw = _author_input_values(form)
    try:
        data = _parse_author_input(form, raw)
    except ValueError as error:
        message = (
            _error_message(error) if isinstance(error, ValidationError) else str(error)
        )
        return _author_form_error(request, admin_email, connection, raw, message)
    reference_error = _validate_references(connection, data)
    if reference_error:
        return _author_form_error(
            request, admin_email, connection, data.model_dump(), reference_error
        )
    if _slug_exists(connection, data.slug):
        return _author_form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "このslugは既に使われています。",
        )
    now = datetime.now(UTC)
    try:
        with connection.engine.begin() as write_connection:
            author_id = write_connection.execute(
                insert(authors).values(**_author_values(data, now, create=True))
            ).inserted_primary_key[0]
            _write_relations(write_connection, author_id, data, now)
    except IntegrityError:
        return _author_form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "slugの重複または日付・生誕国・関連付けの制約違反があります。",
        )
    with connection.engine.connect() as read_connection:
        new = _load_author_snapshot(read_connection, author_id)
    log_admin_operation(admin_email, "create", f"authors:{author_id}", now=now)
    notice = purge_notice(
        "著者", "作成", _author_purge_paths(None, new), purger=purge_cache
    )
    return RedirectResponse(
        f"/admin/authors?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{author_id}/edit", response_class=HTMLResponse)
def author_edit(
    author_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _load_author_snapshot(connection, author_id)
    if row is None:
        raise HTTPException(status_code=404, detail="著者が見つかりません")
    values = {key: row[key] for key in AuthorForm.model_fields}
    return templates.TemplateResponse(
        request=request,
        name="admin/authors/form.html",
        context=_form_context(
            request, admin_email, connection, values=values, author_id=author_id
        ),
    )


@router.post("/{author_id}")
async def author_update(
    author_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _load_author_snapshot(connection, author_id)
    if old is None:
        raise HTTPException(status_code=404, detail="著者が見つかりません")
    raw = _author_input_values(form)
    try:
        data = _parse_author_input(form, raw)
    except ValueError as error:
        message = (
            _error_message(error) if isinstance(error, ValidationError) else str(error)
        )
        return _author_form_error(
            request, admin_email, connection, raw, message, author_id
        )
    reference_error = _validate_references(connection, data)
    if reference_error:
        return _author_form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            reference_error,
            author_id,
        )
    if _slug_exists(connection, data.slug, excluding_id=author_id):
        return _author_form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "このslugは既に使われています。",
            author_id,
        )
    now = datetime.now(UTC)
    try:
        with connection.engine.begin() as write_connection:
            write_connection.execute(
                update(authors)
                .where(authors.c.id == author_id)
                .values(**_author_values(data, now, create=False))
            )
            write_connection.execute(
                delete(author_professions).where(
                    author_professions.c.author_id == author_id
                )
            )
            write_connection.execute(
                delete(author_country).where(author_country.c.author_id == author_id)
            )
            _write_relations(write_connection, author_id, data, now)
    except IntegrityError:
        return _author_form_error(
            request,
            admin_email,
            connection,
            data.model_dump(),
            "slugの重複または日付・生誕国・関連付けの制約違反があります。",
            author_id,
        )
    with connection.engine.connect() as read_connection:
        new = _load_author_snapshot(read_connection, author_id)
    log_admin_operation(admin_email, "update", f"authors:{author_id}", now=now)
    notice = purge_notice(
        "著者", "更新", _author_purge_paths(old, new), purger=purge_cache
    )
    return RedirectResponse(
        f"/admin/authors?{urlencode({'notice': notice})}", status_code=303
    )


@router.get("/{author_id}/delete", response_class=HTMLResponse)
def author_delete_confirm(
    author_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> HTMLResponse:
    row = _load_author_snapshot(connection, author_id)
    if row is None:
        raise HTTPException(status_code=404, detail="著者が見つかりません")
    quote_count = connection.execute(
        select(func.count()).select_from(quotes).where(quotes.c.author_id == author_id)
    ).scalar_one()
    source_count = connection.execute(
        select(func.count())
        .select_from(sources)
        .where(sources.c.author_id == author_id)
    ).scalar_one()
    return templates.TemplateResponse(
        request=request,
        name="admin/authors/delete.html",
        context={
            "admin_email": admin_email,
            "csrf_token": issue_csrf_token(admin_email),
            "author": row,
            "quote_count": quote_count,
            "source_count": source_count,
        },
    )


@router.post("/{author_id}/delete")
async def author_delete(
    author_id: int,
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> RedirectResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    old = _load_author_snapshot(connection, author_id)
    if old is None:
        raise HTTPException(status_code=404, detail="著者が見つかりません")
    with connection.engine.begin() as write_connection:
        write_connection.execute(delete(authors).where(authors.c.id == author_id))
    now = datetime.now(UTC)
    log_admin_operation(admin_email, "delete", f"authors:{author_id}", now=now)
    notice = purge_notice(
        "著者", "削除", _author_purge_paths(old, None), purger=purge_cache
    )
    return RedirectResponse(
        f"/admin/authors?{urlencode({'notice': notice})}", status_code=303
    )
