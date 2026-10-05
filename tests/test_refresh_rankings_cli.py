from datetime import UTC, datetime

import pytest

from app.services import heartbeat
from app.services.cache_purge import CachePurgeResult, CachePurgeStatus
from app.services.ranking_refresh import RankingRefreshResult
from scripts import refresh_rankings as cli


@pytest.fixture(autouse=True)
def heartbeat_environment(monkeypatch):
    monkeypatch.delenv("UPTIMEROBOT_RANKING_HEARTBEAT_URL", raising=False)


def test_cli_returns_zero_after_refresh_when_purge_is_skipped(monkeypatch) -> None:
    result = RankingRefreshResult(3, 2, 1, 0.125, datetime.now(UTC))
    monkeypatch.setattr(cli, "refresh_rankings", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(
        cli,
        "purge_cache",
        lambda _paths: CachePurgeResult(CachePurgeStatus.SKIPPED, ()),
    )

    assert cli.main() == 0


def test_cli_returns_nonzero_when_refresh_fails(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(cli, "refresh_rankings", fail)
    monkeypatch.setattr(cli, "send_heartbeat", lambda *_a: pytest.fail("heartbeat"))

    assert cli.main() != 0


def test_success_heartbeat_precedes_purge(monkeypatch):
    calls = []
    monkeypatch.setenv(
        "UPTIMEROBOT_RANKING_HEARTBEAT_URL", "https://heartbeat.example/token"
    )
    result = RankingRefreshResult(3, 2, 1, 0.125, datetime.now(UTC))
    monkeypatch.setattr(cli, "refresh_rankings", lambda *_a, **_k: result)

    def ping(job, url):
        assert job == "refresh_rankings"
        assert url == "https://heartbeat.example/token"
        calls.append("heartbeat")

    def purge(_paths):
        calls.append("purge")
        return CachePurgeResult(CachePurgeStatus.FAILED, ())

    monkeypatch.setattr(cli, "send_heartbeat", ping)
    monkeypatch.setattr(cli, "purge_cache", purge)
    assert cli.main() == 0
    assert calls == ["heartbeat", "purge"]


def test_heartbeat_failure_keeps_success_exit(monkeypatch):
    monkeypatch.setenv(
        "UPTIMEROBOT_RANKING_HEARTBEAT_URL", "https://heartbeat.example/token"
    )
    result = RankingRefreshResult(3, 2, 1, 0.125, datetime.now(UTC))
    monkeypatch.setattr(cli, "refresh_rankings", lambda *_a, **_k: result)
    monkeypatch.setattr(
        cli, "purge_cache", lambda _p: CachePurgeResult(CachePurgeStatus.SKIPPED, ())
    )

    def fail(*_a, **_k):
        raise TimeoutError("https://heartbeat.example/token")

    monkeypatch.setattr(heartbeat, "urlopen", fail)
    assert cli.main() == 0
