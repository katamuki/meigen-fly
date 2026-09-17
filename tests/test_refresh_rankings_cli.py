from datetime import UTC, datetime

from app.services.cache_purge import CachePurgeResult, CachePurgeStatus
from app.services.ranking_refresh import RankingRefreshResult
from scripts import refresh_rankings as cli


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

    assert cli.main() != 0
