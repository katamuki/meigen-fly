import logging
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError

import pytest

from app.services import heartbeat

SECRET_URL = "https://heartbeat.example/private-token"


class Response:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


def test_unconfigured_skips(monkeypatch, caplog):
    monkeypatch.setattr(heartbeat, "urlopen", lambda *_a, **_k: pytest.fail("HTTP"))
    with caplog.at_level(logging.INFO):
        heartbeat.send_heartbeat("backup_sqlite", None)
    assert "skipped job=backup_sqlite" in caplog.text


def test_success_get_once(monkeypatch, caplog):
    calls = []

    def open_request(request, *, timeout):
        calls.append((request, timeout))
        return Response()

    monkeypatch.setattr(heartbeat, "urlopen", open_request)
    with caplog.at_level(logging.INFO):
        heartbeat.send_heartbeat("backup_sqlite", SECRET_URL)
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == SECRET_URL
    assert request.get_method() == "GET"
    assert timeout == 10
    assert "succeeded job=backup_sqlite" in caplog.text
    assert "heartbeat.example" not in caplog.text
    assert "private-token" not in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        HTTPError(SECRET_URL, 500, SECRET_URL, {}, None),
        TimeoutError(SECRET_URL),
        URLError(SECRET_URL),
        IncompleteRead(SECRET_URL.encode(), 5),
        ValueError(SECRET_URL),
    ],
)
def test_failure_does_not_raise_or_leak(monkeypatch, caplog, error):
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(heartbeat, "urlopen", fail)
    heartbeat.send_heartbeat("backup_sqlite", SECRET_URL)
    assert "failed job=backup_sqlite" in caplog.text
    assert "heartbeat.example" not in caplog.text
    assert "private-token" not in caplog.text


def test_non_success_response(monkeypatch, caplog):
    monkeypatch.setattr(heartbeat, "urlopen", lambda *_a, **_k: Response(503))
    heartbeat.send_heartbeat("backup_sqlite", SECRET_URL)
    assert "HTTP 503" in caplog.text
    assert SECRET_URL not in caplog.text
