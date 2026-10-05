"""Rebuild ranking snapshots and purge their public cache entries."""

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_uptimerobot_ranking_heartbeat_url
from app.db import engine
from app.services.cache_purge import CachePurgeStatus, purge_cache
from app.services.heartbeat import send_heartbeat
from app.services.ranking_refresh import refresh_rankings

RANKING_PURGE_PATHS = [
    "/",
    "/ranking",
    "/ranking/authors",
    "/ranking/categories",
]
logger = logging.getLogger("refresh_rankings")


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        result = refresh_rankings(engine, now=datetime.now(UTC))
    except Exception:
        logger.exception("ranking refresh failed")
        return 1

    logger.info(
        "ranking refresh succeeded quotes=%d authors=%d categories=%d "
        "duration_seconds=%.3f refreshed_at=%s",
        result.quote_count,
        result.author_count,
        result.category_count,
        result.duration_seconds,
        result.refreshed_at.isoformat(),
    )
    send_heartbeat("refresh_rankings", get_uptimerobot_ranking_heartbeat_url())
    purge = purge_cache(RANKING_PURGE_PATHS)
    if purge.status is CachePurgeStatus.SUCCESS:
        logger.info("cache purge succeeded urls=%d", len(purge.urls))
    elif purge.status is CachePurgeStatus.SKIPPED:
        logger.info("cache purge skipped: %s", purge.detail)
    else:
        logger.warning("cache purge failed; cached pages will expire by TTL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
