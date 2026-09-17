"""Administration routes protected by Cloudflare Access."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.admin import (
    issue_csrf_token,
    log_admin_operation,
    read_urlencoded_form,
    require_admin,
    require_csrf,
)
from app.db import get_connection
from app.instants import parse_instant
from app.schema import authors, quote_ranking_scores, quotes
from app.services.cache_purge import CachePurgeStatus, purge_cache
from app.services.ranking_refresh import refresh_rankings

APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["comma"] = lambda value: f"{value:,}"
logger = logging.getLogger("app.routers.admin")
JST = ZoneInfo("Asia/Tokyo")
RANKING_PURGE_PATHS = [
    "/",
    "/ranking",
    "/ranking/authors",
    "/ranking/categories",
]

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
login_router = APIRouter()

AdminEmail = Annotated[str, Depends(require_admin)]
ConnectionDependency = Annotated[Connection, Depends(get_connection)]
Notice = Annotated[str | None, Query(max_length=200)]


@router.get("", response_class=HTMLResponse)
def dashboard(
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
    notice: Notice = None,
) -> HTMLResponse:
    counts = connection.execute(
        select(
            func.count().filter(quotes.c.enable == 1).label("published_quotes"),
            func.count().filter(quotes.c.enable == 0).label("private_quotes"),
        ).select_from(quotes)
    ).one()
    author_count = connection.execute(
        select(func.count()).select_from(authors)
    ).scalar_one()
    refreshed_at = connection.execute(
        select(func.max(quote_ranking_scores.c.refreshed_at))
    ).scalar_one()
    refreshed_at_jst = (
        parse_instant(refreshed_at).astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST")
        if refreshed_at
        else None
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "admin_email": admin_email,
            "published_quotes": counts.published_quotes,
            "private_quotes": counts.private_quotes,
            "author_count": author_count,
            "ranking_refreshed_at": refreshed_at_jst,
            "csrf_token": issue_csrf_token(admin_email),
            "notice": notice,
        },
    )


@router.post("/rankings/refresh")
async def refresh_ranking_snapshots(
    request: Request,
    admin_email: AdminEmail,
    connection: ConnectionDependency,
) -> RedirectResponse:
    form = await read_urlencoded_form(request)
    require_csrf(form, admin_email)
    now = datetime.now(UTC)
    try:
        result = refresh_rankings(connection.engine, now=now)
    except Exception:
        logger.exception("ranking refresh failed")
        log_admin_operation(admin_email, "refresh_failed", "rankings", now=now)
        notice = "ランキング再計算に失敗しました。前回の結果を維持しています。"
    else:
        log_admin_operation(admin_email, "refresh", "rankings", now=now)
        purge = purge_cache(RANKING_PURGE_PATHS)
        purge_text = {
            CachePurgeStatus.SUCCESS: "キャッシュパージ成功",
            CachePurgeStatus.FAILED: "キャッシュパージ失敗（TTL待ち）",
            CachePurgeStatus.SKIPPED: "キャッシュパージ未設定のためスキップ",
        }[purge.status]
        notice = (
            "ランキングを再計算しました "
            f"（名言 {result.quote_count}件、著者 {result.author_count}件、"
            f"カテゴリ {result.category_count}件、{result.duration_seconds:.3f}秒）。"
            f"{purge_text}。"
        )
    return RedirectResponse(f"/admin?{urlencode({'notice': notice})}", status_code=303)


@login_router.get("/login", include_in_schema=False)
def login() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=302)
