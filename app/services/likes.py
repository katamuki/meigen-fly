"""Anonymous quote-like validation, throttling, and persistence."""

from collections import OrderedDict, deque
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import get_like_rate_limit
from app.instants import format_instant
from app.schema import quote_likes, quotes


class QuoteNotLikeableError(Exception):
    """The requested quote does not exist or is not public."""


class LikeWriteUnavailableError(Exception):
    """SQLite could not complete the like write."""


def validate_client_uuid(value: str) -> str:
    """Require the canonical lowercase textual form of a UUID."""
    if len(value) != 36:
        raise ValueError("client_uuid must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError("client_uuid must be a canonical UUID") from error
    if str(parsed) != value:
        raise ValueError("client_uuid must be a canonical UUID")
    return value


class LikeRateLimiter:
    """A process-local sliding-window limit keyed only by source IP."""

    def __init__(
        self, max_requests: int, window_seconds: float, max_sources: int = 10_000
    ) -> None:
        if max_requests < 1 or window_seconds <= 0 or max_sources < 1:
            raise ValueError("rate limit values must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_sources = max_sources
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def allow(self, source_ip: str, *, now: float | None = None) -> tuple[bool, int]:
        current = monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            timestamps = self._requests.pop(source_ip, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(self._requests) >= self.max_sources:
                self._requests.popitem(last=False)
            self._requests[source_ip] = timestamps
            if len(timestamps) >= self.max_requests:
                retry_after = max(
                    1, int(timestamps[0] + self.window_seconds - current + 1)
                )
                return False, retry_after
            timestamps.append(current)
            return True, 0

    @property
    def tracked_source_count(self) -> int:
        with self._lock:
            return len(self._requests)

    def reset(self) -> None:
        """Clear transient state, primarily for isolated application tests."""
        with self._lock:
            self._requests.clear()


like_rate_limiter = LikeRateLimiter(*get_like_rate_limit())


def _current_like_count(connection: Connection, quote_id: int) -> int | None:
    valid_likes = func.coalesce(
        func.sum(case((quote_likes.c.is_valid == 1, 1), else_=0)), 0
    )
    return connection.execute(
        select((quotes.c.legacy_vote_count + valid_likes).label("like_count"))
        .select_from(
            quotes.outerjoin(quote_likes, quote_likes.c.quote_id == quotes.c.id)
        )
        .where(quotes.c.id == quote_id, quotes.c.enable == 1)
        .group_by(quotes.c.id)
    ).scalar_one_or_none()


def record_like(connection: Connection, quote_id: int, client_uuid: str) -> int:
    """Insert one public quote like, treating duplicate UUID votes as success."""
    try:
        legacy_count = connection.execute(
            select(quotes.c.legacy_vote_count).where(
                quotes.c.id == quote_id, quotes.c.enable == 1
            )
        ).scalar_one_or_none()
        if legacy_count is None:
            raise QuoteNotLikeableError

        already_exists = connection.execute(
            select(quote_likes.c.quote_id).where(
                quote_likes.c.quote_id == quote_id,
                quote_likes.c.client_uuid == client_uuid,
            )
        ).first()
        if already_exists is None:
            try:
                connection.execute(
                    quote_likes.insert().values(
                        quote_id=quote_id,
                        client_uuid=client_uuid,
                        created_at=format_instant(datetime.now(UTC)),
                        is_valid=1,
                    )
                )
            except IntegrityError as error:
                # Another request may have inserted the same composite key after
                # the existence check. Only that actual duplicate is idempotent.
                duplicate = connection.execute(
                    select(quote_likes.c.quote_id).where(
                        quote_likes.c.quote_id == quote_id,
                        quote_likes.c.client_uuid == client_uuid,
                    )
                ).first()
                if duplicate is None:
                    raise LikeWriteUnavailableError from error

        like_count = _current_like_count(connection, quote_id)
        if like_count is None:
            raise QuoteNotLikeableError
        return like_count
    except OperationalError as error:
        raise LikeWriteUnavailableError from error
