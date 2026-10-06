"""Best-effort success pings; heartbeat URLs must never enter logs."""

import logging
from http.client import HTTPException as HTTPClientException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("app.services.heartbeat")


def send_heartbeat(job: str, url: str | None) -> None:
    if url is None:
        logger.info("heartbeat skipped job=%s: URL is not configured", job)
        return
    try:
        with urlopen(Request(url, method="GET"), timeout=10):
            pass
    except HTTPError as error:
        logger.warning("heartbeat failed job=%s HTTP %d", job, error.code)
        return
    except (URLError, HTTPClientException, OSError, ValueError, TypeError) as error:
        logger.warning("heartbeat failed job=%s %s", job, type(error).__name__)
        return
    logger.info("heartbeat succeeded job=%s", job)
