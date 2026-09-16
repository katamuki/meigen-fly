import asyncio
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from app.admin import (
    CSRF_MAX_AGE_SECONDS,
    issue_csrf_token,
    read_urlencoded_form,
    require_csrf,
    validate_csrf_token,
)

EMAIL = "admin@example.com"


def test_csrf_token_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    now = 1_800_000_000
    token = issue_csrf_token(EMAIL, now=now)

    assert validate_csrf_token(token, EMAIL, now=now)
    assert not validate_csrf_token(f"{token}x", EMAIL, now=now)
    assert not validate_csrf_token(token, "other@example.com", now=now)
    assert not validate_csrf_token(token, EMAIL, now=now + CSRF_MAX_AGE_SECONDS + 1)
    assert not validate_csrf_token(token, EMAIL, now=now - 1)


def test_csrf_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    with pytest.raises(Exception) as missing:
        require_csrf({}, EMAIL)
    assert missing.value.status_code == 403


def _request(body: bytes, content_type: str) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/test",
            "headers": [(b"content-type", content_type.encode())],
        },
        receive,
    )


def test_urlencoded_form_preserves_multiple_values() -> None:
    form = asyncio.run(
        read_urlencoded_form(
            _request(
                b"category=1&category=2&name=%E5%90%8D%E8%A8%80",
                "application/x-www-form-urlencoded",
            )
        )
    )

    assert form == {"category": ["1", "2"], "name": ["名言"]}


def test_urlencoded_form_rejects_content_type_size_and_malformed_data() -> None:
    with pytest.raises(Exception) as content_type:
        asyncio.run(read_urlencoded_form(_request(b"a=1", "application/json")))
    assert content_type.value.status_code == 415

    with pytest.raises(Exception) as too_large:
        asyncio.run(
            read_urlencoded_form(
                _request(b"a=1234", "application/x-www-form-urlencoded"),
                max_bytes=5,
            )
        )
    assert too_large.value.status_code == 413

    with pytest.raises(Exception) as malformed:
        asyncio.run(
            read_urlencoded_form(
                _request(b"name=%ZZ", "application/x-www-form-urlencoded")
            )
        )
    assert malformed.value.status_code == 422


def test_admin_operation_log_is_one_line(caplog: pytest.LogCaptureFixture) -> None:
    from app.admin import log_admin_operation

    with caplog.at_level("INFO", logger="app.admin"):
        log_admin_operation(
            "admin@example.com\nignored",
            "update",
            "quotes:1",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )

    assert "admin_email=admin@example.com ignored" in caplog.text
    assert "action=update target=quotes:1" in caplog.text
    assert "at=2026-01-01T00:00:00+00:00" in caplog.text
