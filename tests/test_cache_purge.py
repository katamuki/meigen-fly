import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app.services import cache_purge
from app.services.cache_purge import CachePurgeStatus, purge_cache


class Response:
    def __init__(self, payload: dict) -> None:
        self.body = BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        pass

    def read(self) -> bytes:
        return self.body.read()


@pytest.fixture(autouse=True)
def cloudflare_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://www.example.com/")
    monkeypatch.setenv("CF_ZONE_ID", "zone-id")
    monkeypatch.setenv("CF_API_TOKEN", "api-token")


def test_purge_builds_deduplicated_urls_header_and_body(monkeypatch) -> None:
    calls = []

    def open_request(request, *, timeout):
        calls.append((request, timeout))
        return Response({"success": True})

    monkeypatch.setattr(cache_purge, "urlopen", open_request)
    result = purge_cache(["/", "/ranking", "/ranking"])

    assert result.status is CachePurgeStatus.SUCCESS
    assert result.urls == (
        "https://www.example.com/",
        "https://www.example.com/ranking",
    )
    request, timeout = calls[0]
    assert request.full_url.endswith("/zones/zone-id/purge_cache")
    assert request.get_header("Authorization") == "Bearer api-token"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"files": list(result.urls)}
    assert timeout == 5


def test_purge_splits_only_above_cloudflare_limit(monkeypatch) -> None:
    bodies = []

    def open_request(request, *, timeout):
        bodies.append(json.loads(request.data))
        return Response({"success": True})

    monkeypatch.setattr(cache_purge, "urlopen", open_request)
    result = purge_cache([f"/page/{number}" for number in range(101)])

    assert result.status is CachePurgeStatus.SUCCESS
    assert [len(body["files"]) for body in bodies] == [100, 1]


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_http_failures_are_logged_and_returned(
    monkeypatch, caplog, status_code
) -> None:
    def fail(*_args, **_kwargs):
        raise HTTPError("https://api.example", status_code, "failure", {}, None)

    monkeypatch.setattr(cache_purge, "urlopen", fail)
    with caplog.at_level("ERROR", logger="app.services.cache_purge"):
        result = purge_cache(["/"])

    assert result.status is CachePurgeStatus.FAILED
    assert f"HTTP {status_code}" in result.detail
    assert "Cloudflare cache purge failed" in caplog.text


def test_timeout_is_logged_and_returned(monkeypatch, caplog) -> None:
    def fail(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(cache_purge, "urlopen", fail)
    with caplog.at_level("ERROR", logger="app.services.cache_purge"):
        result = purge_cache(["/"])

    assert result.status is CachePurgeStatus.FAILED
    assert "timed out" in result.detail
    assert "timed out" in caplog.text


def test_success_false_is_logged_and_returned(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        cache_purge, "urlopen", lambda *_args, **_kwargs: Response({"success": False})
    )
    with caplog.at_level("ERROR", logger="app.services.cache_purge"):
        result = purge_cache(["/"])

    assert result.status is CachePurgeStatus.FAILED
    assert "success=false" in result.detail
    assert "success=false" in caplog.text


def test_missing_configuration_skips_without_http(monkeypatch) -> None:
    monkeypatch.delenv("CF_API_TOKEN")

    def unexpected(*_args, **_kwargs):
        pytest.fail("HTTP must not be called")

    monkeypatch.setattr(cache_purge, "urlopen", unexpected)
    result = purge_cache(["/"])

    assert result.status is CachePurgeStatus.SKIPPED
