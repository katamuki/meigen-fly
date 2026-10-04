"""Bulk quote and author administration screens."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import insert, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.admin import (
    int_or_none,
    issue_csrf_token,
    log_admin_operation,
    one,
    purge_notice,
    read_urlencoded_form,
    require_admin,
    require_csrf,
)
from app.db import get_connection
from app.instants import format_instant
from app.routers.admin import templates
from app.routers.admin_authors import AuthorForm, author_values, write_author_relations
from app.routers.admin_quotes import (
    QuoteForm,
    quote_choices,
    validate_quote_references,
)
from app.schema import (
    authors,
    characters,
    countries,
    professions,
    quotes,
    sources,
)
from app.services.cache_purge import purge_cache

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
MAX_BULK_QUOTES = 500
MAX_BULK_AUTHORS = 10
AUTHOR_BULK_FIELDS = {
    "name",
    "slug",
    "description",
    "image_url",
    "name_kana",
    "name_foreign",
    "name_reading",
    "birth_date",
    "birth_era",
    "birth_precision",
    "death_date",
    "death_era",
    "death_precision",
    "professions",
    "countries",
    "birth_country",
}


@dataclass(frozen=True)
class ParsedQuote:
    line: int
    data: QuoteForm


@dataclass(frozen=True)
class ParsedAuthor:
    number: int
    data: AuthorForm
    profession_names: list[str]
    country_names: list[str]
    birth_country_name: str | None
    warnings: list[str]


def _validation_messages(error: ValidationError, labels: dict[str, str]) -> list[str]:
    messages: list[str] = []
    for detail in error.errors():
        field = str(detail["loc"][-1]) if detail["loc"] else "入力"
        label = labels.get(field, field)
        custom = detail.get("ctx", {}).get("error")
        if custom:
            messages.append(str(custom))
        elif detail["type"] == "missing":
            messages.append(f"{label}は必須です。")
        elif field == "weight":
            messages.append(f"{label}は1〜10の整数で入力してください。")
        elif detail["type"].startswith("string_too_long"):
            messages.append(f"{label}が長すぎます。")
        else:
            messages.append(f"{label}の形式が不正です。")
    return messages


def _quote_raw_values(form: dict[str, list[str]]) -> dict[str, object]:
    return {
        "bulk_input": one(form, "bulk_input"),
        "author_id": one(form, "author_id"),
        "source_id": one(form, "source_id"),
        "character_id": one(form, "character_id"),
        "weight": one(form, "weight", "5"),
        "enable": one(form, "enable", "0"),
        "display_language_preference": one(form, "display_language_preference", "ja"),
    }


def _quote_input_context(
    request: Request,
    admin_email: str,
    connection: Connection,
    *,
    values: dict[str, object],
    errors: list[str] | None = None,
) -> dict[str, object]:
    choices = {name: list(rows) for name, rows in quote_choices(connection).items()}
    return {
        "request": request,
        "admin_email": admin_email,
        "csrf_token": issue_csrf_token(admin_email),
        "values": values,
        "selected_author_id": int_or_none(values.get("author_id")),
        "selected_source_id": int_or_none(values.get("source_id")),
        "selected_character_id": int_or_none(values.get("character_id")),
        "errors": errors or [],
        "max_entries": MAX_BULK_QUOTES,
        **choices,
    }


def _parse_bulk_quotes(
    connection: Connection, values: dict[str, object]
) -> tuple[list[ParsedQuote], list[str]]:
    errors: list[str] = []
    parsed: list[ParsedQuote] = []
    author_id = values.get("author_id") or None
    source_id = values.get("source_id") or None
    character_id = values.get("character_id") or None
    if not any((author_id, source_id, character_id)):
        errors.append("著者・出典・登場人物のいずれかを最低1つ選択してください。")

    shared = {
        "text": "仮の本文",
        "author_id": author_id,
        "source_id": source_id,
        "character_id": character_id,
        "weight": values.get("weight", "5"),
        "slug": None,
        "enable": values.get("enable") == "1",
        "display_language_preference": values.get("display_language_preference", "ja"),
    }
    try:
        shared_data = QuoteForm.model_validate(shared)
    except ValidationError as error:
        errors.extend(
            _validation_messages(
                error,
                {
                    "author_id": "著者",
                    "source_id": "出典",
                    "character_id": "登場人物",
                    "weight": "既定の重み",
                    "display_language_preference": "表示言語",
                },
            )
        )
        shared_data = None
    row_shared: dict[str, object]
    if shared_data is not None:
        reference_error = validate_quote_references(connection, shared_data)
        if reference_error:
            errors.append(reference_error)
        row_shared = shared_data.model_dump()
    else:
        row_shared = {
            "text": "仮の本文",
            "author_id": None,
            "source_id": None,
            "character_id": None,
            "weight": 5,
            "slug": None,
            "enable": True,
            "display_language_preference": "ja",
        }

    bulk_input = str(values.get("bulk_input", ""))
    rows = bulk_input.splitlines()
    nonblank_count = sum(bool(row.strip(" \t\r\n\u3000")) for row in rows)
    if nonblank_count == 0:
        errors.append("有効な行がありません。空行以外を入力してください。")
    if nonblank_count > MAX_BULK_QUOTES:
        errors.append(f"一度に登録できる件数は最大{MAX_BULK_QUOTES}件です。")

    for line_number, row in enumerate(rows, start=1):
        if not row.strip(" \t\r\n\u3000"):
            continue
        columns = row.split("\t")
        if len(columns) > 3:
            errors.append(f"{line_number}行目: タブ区切りは3列までです。")
            continue
        text = columns[0].strip()
        text_en = columns[1].strip() if len(columns) >= 2 else None
        weight = columns[2].strip() if len(columns) >= 3 else ""
        if not text:
            errors.append(f"{line_number}行目: 日本語本文を入力してください。")
        row_values = {
            **row_shared,
            "text": text or "仮の本文",
            "text_en": text_en or None,
            "weight": weight or row_shared["weight"],
        }
        try:
            data = QuoteForm.model_validate(row_values)
        except ValidationError as error:
            for message in _validation_messages(
                error, {"text": "本文", "text_en": "英文", "weight": "重み"}
            ):
                errors.append(f"{line_number}行目: {message}")
            continue
        if text:
            parsed.append(ParsedQuote(line_number, data))
    return parsed, errors


def _quote_purge_paths(connection: Connection, data: QuoteForm) -> list[str]:
    paths = {"/", "/quotes", "/quotes/latest", "/sitemap.xml"}
    selections = (
        (data.author_id, authors, "/authors/"),
        (data.source_id, sources, "/sources/"),
        (data.character_id, characters, "/characters/"),
    )
    for entity_id, table, prefix in selections:
        if entity_id is None:
            continue
        slug = connection.execute(
            select(table.c.slug).where(table.c.id == entity_id)
        ).scalar_one_or_none()
        if slug:
            paths.add(f"{prefix}{slug}")
    return sorted(paths)


def _quote_selection_labels(
    connection: Connection, data: QuoteForm
) -> dict[str, str | None]:
    selections = (
        ("author", data.author_id, authors.c.name, authors.c.id),
        ("source", data.source_id, sources.c.title, sources.c.id),
        ("character", data.character_id, characters.c.name, characters.c.id),
    )
    labels: dict[str, str | None] = {}
    for key, entity_id, label_column, id_column in selections:
        labels[key] = (
            connection.execute(
                select(label_column).where(id_column == entity_id)
            ).scalar_one_or_none()
            if entity_id is not None
            else None
        )
    return labels


@router.get("/quotes/bulk", response_class=HTMLResponse)
def quote_bulk_input(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    values = {
        "bulk_input": "",
        "author_id": "",
        "source_id": "",
        "character_id": "",
        "weight": "5",
        "enable": "1",
        "display_language_preference": "ja",
    }
    return templates.TemplateResponse(
        request=request,
        name="admin/quotes/bulk_input.html",
        context=_quote_input_context(request, admin_email, connection, values=values),
    )


@router.post("/quotes/bulk/confirm")
async def quote_bulk_confirm(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    values = _quote_raw_values(form)
    entries, errors = _parse_bulk_quotes(connection, values)
    if errors:
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/bulk_input.html",
            context=_quote_input_context(
                request, admin_email, connection, values=values, errors=errors
            ),
            status_code=422,
        )
    return templates.TemplateResponse(
        request=request,
        name="admin/quotes/bulk_confirm.html",
        context={
            "admin_email": admin_email,
            "csrf_token": issue_csrf_token(admin_email),
            "values": values,
            "entries": entries,
            "selection_labels": _quote_selection_labels(connection, entries[0].data),
        },
    )


@router.post("/quotes/bulk/edit")
async def quote_bulk_edit(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    values = _quote_raw_values(form)
    return templates.TemplateResponse(
        request=request,
        name="admin/quotes/bulk_input.html",
        context=_quote_input_context(request, admin_email, connection, values=values),
    )


@router.post("/quotes/bulk")
async def quote_bulk_create(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    values = _quote_raw_values(form)
    entries, errors = _parse_bulk_quotes(connection, values)
    if errors:
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/bulk_input.html",
            context=_quote_input_context(
                request, admin_email, connection, values=values, errors=errors
            ),
            status_code=422,
        )
    now = datetime.now(UTC)
    instant = format_instant(now)
    rows = []
    for entry in entries:
        row = entry.data.model_dump(exclude={"category_ids"})
        row.update(slug=None, context_note=None, legacy_vote_count=0)
        row.update(created_at=instant, updated_at=instant)
        rows.append(row)
    try:
        with connection.engine.begin() as write_connection:
            write_connection.execute(insert(quotes), rows)
    except IntegrityError:
        return templates.TemplateResponse(
            request=request,
            name="admin/quotes/bulk_input.html",
            context=_quote_input_context(
                request,
                admin_email,
                connection,
                values=values,
                errors=["登録中に入力内容または関連先の制約違反が見つかりました。"],
            ),
            status_code=422,
        )
    count = len(entries)
    log_admin_operation(admin_email, "bulk_create", f"quotes:count={count}", now=now)
    notice = purge_notice(
        f"名言{count}件",
        "一括登録",
        _quote_purge_paths(connection, entries[0].data),
        purger=purge_cache,
    )
    return RedirectResponse(
        f"/admin/quotes?{urlencode({'notice': notice})}", status_code=303
    )


def _author_input_context(
    request: Request,
    admin_email: str,
    *,
    json_input: str,
    errors: list[str] | None = None,
) -> dict[str, object]:
    return {
        "request": request,
        "admin_email": admin_email,
        "csrf_token": issue_csrf_token(admin_email),
        "json_input": json_input,
        "errors": errors or [],
        "max_entries": MAX_BULK_AUTHORS,
    }


def _string_list(
    raw: dict[str, object], field: str, label: str, number: int, errors: list[str]
) -> list[str]:
    value = raw.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{number}件目: {label}は文字列の配列で指定してください。")
        return []
    return value


def _parse_bulk_authors(
    connection: Connection, json_input: str
) -> tuple[list[ParsedAuthor], list[str]]:
    errors: list[str] = []
    try:
        raw_items = json.loads(json_input)
    except JSONDecodeError:
        return [], ["JSONの形式が不正です。構文を確認してください。"]
    if not isinstance(raw_items, list):
        return [], ["JSONの最上位は著者の配列にしてください。"]
    if not raw_items:
        errors.append("登録件数は1件以上必要です。")
    if len(raw_items) > MAX_BULK_AUTHORS:
        errors.append(f"登録件数は{MAX_BULK_AUTHORS}件以内にしてください。")

    profession_map = dict(
        connection.execute(select(professions.c.name, professions.c.id)).all()
    )
    country_map = dict(
        connection.execute(select(countries.c.name, countries.c.id)).all()
    )
    parsed: list[ParsedAuthor] = []
    entry_errors: dict[int, list[str]] = {}
    for number, item in enumerate(raw_items, start=1):
        current: list[str] = []
        entry_errors[number] = current
        if not isinstance(item, dict):
            current.append("各要素は著者オブジェクトにしてください。")
            continue
        for field in sorted(set(item) - AUTHOR_BULK_FIELDS):
            current.append(f"不明な項目「{field}」があります。")
        profession_names = _string_list(item, "professions", "職業", number, errors)
        country_names = _string_list(item, "countries", "国", number, errors)
        birth_country_name = item.get("birth_country")
        if birth_country_name is not None and not isinstance(birth_country_name, str):
            current.append("生誕国は文字列またはnullで指定してください。")
            birth_country_name = None
        for name in dict.fromkeys(profession_names):
            if profession_names.count(name) > 1:
                current.append(f"職業「{name}」が重複しています。")
            if name not in profession_map:
                current.append(f"職業「{name}」は登録されていません。")
        for name in dict.fromkeys(country_names):
            if country_names.count(name) > 1:
                current.append(f"国「{name}」が重複しています。")
            if name not in country_map:
                current.append(f"国「{name}」は登録されていません。")
        if birth_country_name and birth_country_name not in country_names:
            current.append("生誕国は国リストに含めてください。")
        values = {
            field: item[field]
            for field in (
                "name",
                "slug",
                "description",
                "image_url",
                "name_kana",
                "name_foreign",
                "name_reading",
                "birth_date",
                "birth_era",
                "birth_precision",
                "death_date",
                "death_era",
                "death_precision",
            )
            if field in item
        }
        values.update(
            profession_ids=[
                profession_map[name]
                for name in profession_names
                if name in profession_map
            ],
            country_ids=[
                country_map[name] for name in country_names if name in country_map
            ],
            birth_country_id=(
                country_map.get(birth_country_name) if birth_country_name else None
            ),
        )
        try:
            data = AuthorForm.model_validate(values)
        except ValidationError as error:
            current.extend(
                _validation_messages(
                    error,
                    {
                        "name": "著者名",
                        "slug": "slug",
                        "description": "説明",
                        "image_url": "画像URL",
                        "name_kana": "カナ",
                        "name_foreign": "外国語名",
                        "name_reading": "読み",
                        "birth_date": "生年月日",
                        "birth_era": "生年のera",
                        "birth_precision": "生年のprecision",
                        "death_date": "没年月日",
                        "death_era": "没年のera",
                        "death_precision": "没年のprecision",
                    },
                )
            )
            continue
        parsed.append(
            ParsedAuthor(
                number,
                data,
                profession_names,
                country_names,
                birth_country_name,
                [],
            )
        )

    slugs: dict[str, list[int]] = {}
    names: dict[str, list[int]] = {}
    for entry in parsed:
        slugs.setdefault(entry.data.slug, []).append(entry.number)
        names.setdefault(entry.data.name, []).append(entry.number)
    for slug, numbers in slugs.items():
        if len(numbers) > 1:
            for number in numbers:
                entry_errors[number].append(f"slug「{slug}」が入力内で重複しています。")
    if slugs:
        existing_slugs = set(
            connection.execute(
                select(authors.c.slug).where(authors.c.slug.in_(slugs))
            ).scalars()
        )
        for entry in parsed:
            if entry.data.slug in existing_slugs:
                entry_errors[entry.number].append(
                    f"slug「{entry.data.slug}」は既に使われています。"
                )
    existing_names: dict[str, list[str]] = {}
    if names:
        for name, slug in connection.execute(
            select(authors.c.name, authors.c.slug).where(authors.c.name.in_(names))
        ):
            existing_names.setdefault(name, []).append(slug)
    for entry in parsed:
        if entry.data.name in existing_names:
            entry.warnings.append(
                f"同名の著者が既にいます（slug: {', '.join(existing_names[entry.data.name])}）。"
            )
        if len(names[entry.data.name]) > 1:
            numbers = "、".join(str(number) for number in names[entry.data.name])
            entry.warnings.append(f"同名の著者が入力内の{numbers}件目にあります。")
    for number, messages in entry_errors.items():
        errors.extend(f"{number}件目: {message}" for message in messages)
    return parsed, errors


@router.get("/authors/bulk", response_class=HTMLResponse)
def author_bulk_input(request: Request, admin_email: AdminEmail) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin/authors/bulk_input.html",
        context=_author_input_context(request, admin_email, json_input=""),
    )


@router.post("/authors/bulk/confirm")
async def author_bulk_confirm(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> HTMLResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    json_input = one(form, "json_input")
    entries, errors = _parse_bulk_authors(connection, json_input)
    if errors:
        return templates.TemplateResponse(
            request=request,
            name="admin/authors/bulk_input.html",
            context=_author_input_context(
                request, admin_email, json_input=json_input, errors=errors
            ),
            status_code=422,
        )
    return templates.TemplateResponse(
        request=request,
        name="admin/authors/bulk_confirm.html",
        context={
            "admin_email": admin_email,
            "csrf_token": issue_csrf_token(admin_email),
            "json_input": json_input,
            "entries": entries,
        },
    )


@router.post("/authors/bulk/edit")
async def author_bulk_edit(request: Request, admin_email: AdminEmail) -> HTMLResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    json_input = one(form, "json_input")
    return templates.TemplateResponse(
        request=request,
        name="admin/authors/bulk_input.html",
        context=_author_input_context(request, admin_email, json_input=json_input),
    )


@router.post("/authors/bulk")
async def author_bulk_create(
    request: Request, admin_email: AdminEmail, connection: ConnectionDependency
) -> Response:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    json_input = one(form, "json_input")
    entries, errors = _parse_bulk_authors(connection, json_input)
    if errors:
        return templates.TemplateResponse(
            request=request,
            name="admin/authors/bulk_input.html",
            context=_author_input_context(
                request, admin_email, json_input=json_input, errors=errors
            ),
            status_code=422,
        )
    now = datetime.now(UTC)
    try:
        with connection.engine.begin() as write_connection:
            for entry in entries:
                author_id = write_connection.execute(
                    insert(authors).values(
                        **author_values(entry.data, now, create=True)
                    )
                ).inserted_primary_key[0]
                write_author_relations(write_connection, author_id, entry.data, now)
    except IntegrityError:
        return templates.TemplateResponse(
            request=request,
            name="admin/authors/bulk_input.html",
            context=_author_input_context(
                request,
                admin_email,
                json_input=json_input,
                errors=["登録中にslugまたは関連付けの制約違反が見つかりました。"],
            ),
            status_code=422,
        )
    count = len(entries)
    log_admin_operation(admin_email, "bulk_create", f"authors:count={count}", now=now)
    notice = purge_notice(
        f"著者{count}件",
        "一括登録",
        ["/authors", "/sitemap.xml"],
        purger=purge_cache,
    )
    return RedirectResponse(
        f"/admin/authors?{urlencode({'notice': notice})}", status_code=303
    )
