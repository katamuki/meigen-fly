"""Process-local rate limiting shared by the public write and search routes."""

from collections import OrderedDict, deque
from threading import Lock
from time import monotonic


class RateLimiter:
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
