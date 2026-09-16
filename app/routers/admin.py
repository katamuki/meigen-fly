"""Administration routes protected by Cloudflare Access."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.admin import require_admin
from app.db import get_connection
from app.schema import authors, quotes

APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["comma"] = lambda value: f"{value:,}"

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
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "admin_email": admin_email,
            "published_quotes": counts.published_quotes,
            "private_quotes": counts.private_quotes,
            "author_count": author_count,
            "notice": notice,
        },
    )


@login_router.get("/login", include_in_schema=False)
def login() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=302)
