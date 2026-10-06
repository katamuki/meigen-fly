import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from starlette.responses import Response

from app import main
from app.db import create_db_engine, get_connection, metadata
from app.middleware import cache_control_for, response_headers_middleware

client = TestClient(main.app, base_url="http://localhost:8000")


@pytest.fixture(autouse=True)
def empty_database(tmp_path: Path) -> Iterator[None]:
    """Serve pages from an empty schema so tests never depend on data/app.db."""
    test_engine = create_db_engine(f"sqlite:///{tmp_path / 'app.db'}")
    metadata.create_all(test_engine)

    def override_connection() -> Iterator:
        with test_engine.begin() as connection:
            yield connection

    main.app.dependency_overrides[get_connection] = override_connection
    yield
    main.app.dependency_overrides.clear()
    test_engine.dispose()


def test_home_renders_template_with_cache_and_security_headers() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "名言集.com" in response.text
    assert response.headers["cache-control"] == "public, s-maxage=300, max-age=60"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_static_file_is_served_with_immutable_cache() -> None:
    response = client.get("/static/tokens.74bc89e2.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_healthz_is_ok_and_not_cached(tmp_path: Path, monkeypatch) -> None:
    health_engine = create_db_engine(f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setattr(main, "engine", health_engine)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "private, no-store"
    health_engine.dispose()


def test_healthz_returns_503_when_database_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    missing_parent = tmp_path / "missing" / "app.db"
    unavailable_engine = create_db_engine(f"sqlite:///{missing_parent}")
    monkeypatch.setattr(main, "engine", unavailable_engine)

    response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "private, no-store"
    unavailable_engine.dispose()


def test_sensitive_and_unknown_paths_are_not_cached() -> None:
    for path in ("/search?q=test", "/admin/example", "/login", "/random", "/unknown"):
        response = client.get(path)
        assert response.headers["cache-control"] == "private, no-store"


def test_api_documentation_is_not_exposed() -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "private, no-store"


def test_author_list_and_detail_use_distinct_cache_policies() -> None:
    list_request = client.build_request("GET", "/authors")
    detail_request = client.build_request("GET", "/authors/example")

    assert (
        cache_control_for(list_request, HTMLResponse())
        == "public, s-maxage=3600, max-age=300"
    )
    assert (
        cache_control_for(detail_request, HTMLResponse())
        == "public, s-maxage=86400, max-age=3600"
    )


def test_mandatory_no_store_overrides_downstream_cache_header() -> None:
    request = client.build_request("GET", "/healthz")

    async def call_next(_request) -> Response:
        return Response(headers={"Cache-Control": "public, max-age=3600"})

    response = asyncio.run(response_headers_middleware(request, call_next))

    assert response.headers["cache-control"] == "private, no-store"


def test_host_authority_must_match_public_origin_exactly() -> None:
    assert client.get("/", headers={"Host": "LOCALHOST:8000"}).status_code == 200

    for host in (
        "localhost",
        "localhost:9999",
        "localhost:not-a-port",
        "attacker.invalid",
    ):
        response = client.get("/", headers={"Host": host})
        assert response.status_code == 400


def test_og_images_use_thirty_day_edge_cache() -> None:
    for path in ("/quotes/q1/og.png", "/authors/example/og.png"):
        request = client.build_request("GET", path)
        assert (
            cache_control_for(request, HTMLResponse())
            == "public, s-maxage=2592000, max-age=86400"
        )
