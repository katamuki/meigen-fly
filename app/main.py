from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_public_authority
from app.db import engine
from app.middleware import ExactHostMiddleware, response_headers_middleware

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=APP_DIR / "templates")

app = FastAPI(title="meigen-fly")
app.middleware("http")(response_headers_middleware)
app.add_middleware(
    ExactHostMiddleware,
    allowed_authority=get_public_authority(),
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="home.html")


@app.get("/healthz")
def healthz() -> JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
