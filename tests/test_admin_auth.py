from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from json import JSONDecodeError
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientError, PyJWKSetError

from app import admin
from app.admin import require_admin
from app.db import create_db_engine, get_connection, metadata
from app.main import app
from app.schema import authors, quotes

TEAM_DOMAIN = "https://example.cloudflareaccess.com"
AUDIENCE = "admin-audience"
EMAIL = "admin@example.com"


@pytest.fixture
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def admin_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rsa_keys
) -> Iterator[tuple[TestClient, object]]:
    private_key, public_key = rsa_keys
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", f"{TEAM_DOMAIN}/")
    monkeypatch.setenv("CF_ACCESS_AUD", AUDIENCE)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("ADMIN_DEV_EMAIL", raising=False)
    monkeypatch.setattr(
        admin,
        "_get_jwk_client",
        lambda _domain: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
        ),
    )

    test_engine = create_db_engine(f"sqlite:///{tmp_path / 'admin.db'}")
    metadata.create_all(test_engine)
    instant = "2026-01-01T00:00:00.000000Z"
    with test_engine.begin() as connection:
        connection.execute(
            authors.insert(),
            {
                "id": 1,
                "name": "著者",
                "slug": "author",
                "created_at": instant,
                "updated_at": instant,
            },
        )
        connection.execute(
            quotes.insert(),
            [
                {
                    "id": 1,
                    "text": "公開",
                    "enable": 1,
                    "created_at": instant,
                    "updated_at": instant,
                },
                {
                    "id": 2,
                    "text": "非公開",
                    "enable": 0,
                    "created_at": instant,
                    "updated_at": instant,
                },
            ],
        )

    def override_connection():
        with test_engine.begin() as connection:
            yield connection

    app.dependency_overrides[get_connection] = override_connection
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client, private_key
    app.dependency_overrides.clear()
    test_engine.dispose()


def _token(private_key, **updates) -> str:
    claims = {
        "aud": AUDIENCE,
        "iss": TEAM_DOMAIN,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "email": EMAIL,
    }
    claims.update(updates)
    return jwt.encode(claims, private_key, algorithm="RS256")


def _get_admin(client: TestClient, token: str | None = None):
    headers = {"Cf-Access-Jwt-Assertion": token} if token is not None else {}
    return client.get("/admin", headers=headers)


def test_admin_rejects_missing_assertion(admin_client) -> None:
    client, _private_key = admin_client
    assert _get_admin(client).status_code == 403


def test_admin_rejects_bad_signature(admin_client) -> None:
    client, _private_key = admin_client
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert _get_admin(client, _token(other_key)).status_code == 403


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("aud", "other-audience"),
        ("iss", "https://other.cloudflareaccess.com"),
        ("exp", datetime.now(UTC) - timedelta(minutes=1)),
        ("email", ""),
        ("email", None),
    ],
)
def test_admin_rejects_invalid_claims(admin_client, claim: str, value) -> None:
    client, private_key = admin_client
    assert _get_admin(client, _token(private_key, **{claim: value})).status_code == 403


def test_admin_rejects_missing_email(admin_client) -> None:
    client, private_key = admin_client
    token = jwt.encode(
        {
            "aud": AUDIENCE,
            "iss": TEAM_DOMAIN,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )
    assert _get_admin(client, token).status_code == 403


@pytest.mark.parametrize(
    ("missing_claim", "log_reason"),
    [
        ("aud", "audience missing"),
        ("iss", "issuer missing"),
        ("exp", "expiration missing"),
    ],
)
def test_admin_logs_the_missing_required_claim(
    admin_client,
    caplog: pytest.LogCaptureFixture,
    missing_claim: str,
    log_reason: str,
) -> None:
    client, private_key = admin_client
    claims = {
        "aud": AUDIENCE,
        "iss": TEAM_DOMAIN,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "email": EMAIL,
    }
    del claims[missing_claim]
    token = jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
    )

    with caplog.at_level("WARNING", logger="app.admin"):
        response = _get_admin(client, token)

    assert response.status_code == 403
    assert f"admin authentication rejected: {log_reason}" in caplog.text
    assert token not in caplog.text


def test_admin_accepts_valid_assertion_and_shows_dashboard(admin_client) -> None:
    client, private_key = admin_client
    response = _get_admin(client, _token(private_key))

    assert response.status_code == 200
    assert EMAIL in response.text
    assert "公開名言" in response.text
    assert "非公開名言" in response.text
    assert "ログアウト" in response.text
    assert '<meta name="robots" content="noindex, nofollow">' in response.text
    assert "components.85b1abc0.css" not in response.text
    assert "admin.b242e875.css" in response.text
    assert "htmx" not in response.text.lower()


@pytest.mark.parametrize(
    "error",
    [
        PyJWKClientError("offline"),
        PyJWKSetError("no usable keys"),
        JSONDecodeError("invalid JSON", "not-json", 0),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte"),
    ],
)
def test_admin_rejects_signing_key_failure(
    admin_client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    client, private_key = admin_client
    token = _token(private_key)

    def fail(_token):
        raise error

    monkeypatch.setattr(
        admin,
        "_get_jwk_client",
        lambda _domain: SimpleNamespace(get_signing_key_from_jwt=fail),
    )
    with caplog.at_level("WARNING", logger="app.admin"):
        response = _get_admin(client, token)

    assert response.status_code == 403
    assert "admin authentication rejected: signing key retrieval failed" in caplog.text
    assert token not in caplog.text


def test_admin_rejects_missing_required_configuration(
    admin_client, monkeypatch
) -> None:
    client, _private_key = admin_client
    monkeypatch.delenv("SECRET_KEY")
    assert _get_admin(client).status_code == 403


def test_admin_rejects_invalid_team_domain(admin_client, monkeypatch) -> None:
    client, _private_key = admin_client
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "https://example.com")
    assert _get_admin(client).status_code == 403


def test_local_development_bypass(admin_client, monkeypatch) -> None:
    client, _private_key = admin_client
    monkeypatch.setenv("ADMIN_DEV_EMAIL", EMAIL)
    monkeypatch.delenv("CF_ACCESS_AUD")

    response = _get_admin(client)

    assert response.status_code == 200
    assert EMAIL in response.text


@pytest.mark.parametrize(
    ("env_name", "env_value", "delete_name"),
    [
        ("CF_ACCESS_AUD", AUDIENCE, None),
        ("PUBLIC_ORIGIN", "https://www.meigensyu.com", "CF_ACCESS_AUD"),
        ("ADMIN_DEV_EMAIL", None, "CF_ACCESS_AUD"),
    ],
)
def test_development_bypass_is_strictly_limited(
    admin_client,
    monkeypatch,
    env_name: str,
    env_value: str | None,
    delete_name: str | None,
) -> None:
    client, _private_key = admin_client
    monkeypatch.setenv("ADMIN_DEV_EMAIL", EMAIL)
    if delete_name:
        monkeypatch.delenv(delete_name, raising=False)
    if env_value is None:
        monkeypatch.delenv(env_name, raising=False)
    else:
        monkeypatch.setenv(env_name, env_value)

    assert _get_admin(client).status_code == 403


def test_admin_and_login_are_no_store_and_login_redirects(admin_client) -> None:
    client, private_key = admin_client
    admin_response = _get_admin(client, _token(private_key))
    login_response = client.get("/login", follow_redirects=False)

    assert admin_response.headers["cache-control"] == "private, no-store"
    assert login_response.status_code == 302
    assert login_response.headers["location"] == "/admin"
    assert login_response.headers["cache-control"] == "private, no-store"


def test_every_admin_route_has_the_shared_authentication_dependency() -> None:
    def application_routes(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                yield from application_routes(route.original_router.routes)

    admin_routes = [
        route
        for route in application_routes(app.routes)
        if route.path.startswith("/admin")
    ]

    assert admin_routes
    for route in admin_routes:
        assert any(
            dependency.call is require_admin
            for dependency in route.dependant.dependencies
        ), route.path
