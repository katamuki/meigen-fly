from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_public_authority
from app.db import engine
from app.middleware import (
    ExactHostMiddleware,
    legacy_redirect_middleware,
    response_headers_middleware,
)
from app.routers.admin import login_router
from app.routers.admin import router as admin_router
from app.routers.public import router as public_router

APP_DIR = Path(__file__).parent

app = FastAPI(
    title="meigen-fly",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
# Starlette runs the last registered middleware first, so the host check
# guards everything and legacy redirects still get the shared headers.
app.middleware("http")(legacy_redirect_middleware)
app.middleware("http")(response_headers_middleware)
app.add_middleware(
    ExactHostMiddleware,
    allowed_authority=get_public_authority(),
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
app.include_router(public_router)
app.include_router(admin_router)
app.include_router(login_router)


@app.get("/healthz")
def healthz() -> JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
