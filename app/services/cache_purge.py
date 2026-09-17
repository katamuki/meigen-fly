"""Best-effort Cloudflare URL cache purging shared by admin and CLI code."""

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_cf_api_token, get_cf_zone_id, get_public_origin

logger = logging.getLogger("app.services.cache_purge")

CLOUDFLARE_API = "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache"
MAX_URLS_PER_REQUEST = 100
PURGE_TIMEOUT_SECONDS = 5


class CachePurgeStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CachePurgeResult:
    status: CachePurgeStatus
    urls: tuple[str, ...]
    detail: str | None = None


def _absolute_urls(paths: list[str]) -> tuple[str, ...]:
    origin = get_public_origin()
    urls = []
    seen = set()
    for path in paths:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("cache purge paths must start with one slash")
        url = f"{origin}{path}"
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return tuple(urls)


def purge_cache(paths: list[str]) -> CachePurgeResult:
    """Purge paths once, returning failure details without raising them."""
    try:
        urls = _absolute_urls(paths)
        zone_id = get_cf_zone_id()
        token = get_cf_api_token()
    except ValueError as error:
        logger.error("Cloudflare cache purge failed: %s", error)
        return CachePurgeResult(CachePurgeStatus.FAILED, (), str(error))
    if not zone_id or not token:
        return CachePurgeResult(
            CachePurgeStatus.SKIPPED,
            urls,
            "Cloudflare credentials are not configured",
        )

    endpoint = CLOUDFLARE_API.format(zone_id=zone_id)
    for offset in range(0, len(urls), MAX_URLS_PER_REQUEST):
        chunk = urls[offset : offset + MAX_URLS_PER_REQUEST]
        try:
            request = Request(
                endpoint,
                data=json.dumps({"files": list(chunk)}, separators=(",", ":")).encode(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(request, timeout=PURGE_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
            if not isinstance(payload, dict) or payload.get("success") is not True:
                detail = "Cloudflare API returned success=false"
                logger.error("Cloudflare cache purge failed: %s", detail)
                return CachePurgeResult(CachePurgeStatus.FAILED, urls, detail)
        except HTTPError as error:
            detail = f"Cloudflare API returned HTTP {error.code}"
            logger.error("Cloudflare cache purge failed: %s", detail)
            return CachePurgeResult(CachePurgeStatus.FAILED, urls, detail)
        except TimeoutError:
            detail = "Cloudflare cache purge timed out"
            logger.error("Cloudflare cache purge failed: %s", detail)
            return CachePurgeResult(CachePurgeStatus.FAILED, urls, detail)
        except (
            URLError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            detail = f"Cloudflare cache purge request failed: {error}"
            logger.error("Cloudflare cache purge failed: %s", detail)
            return CachePurgeResult(CachePurgeStatus.FAILED, urls, detail)
    return CachePurgeResult(CachePurgeStatus.SUCCESS, urls)
