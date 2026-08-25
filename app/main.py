from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_public_authority
from app.db import engine
from app.middleware import ExactHostMiddleware, response_headers_middleware
from app.routers.public import router as public_router

APP_DIR = Path(__file__).parent

app = FastAPI(
    title="meigen-fly",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.middleware("http")(response_headers_middleware)
app.add_middleware(
    ExactHostMiddleware,
    allowed_authority=get_public_authority(),
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
app.include_router(public_router)


@app.get("/healthz")
def healthz() -> JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
