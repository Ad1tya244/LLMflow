"""Sliding-window rate limiter (process-local; correct for a single instance)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

_MAX_TRACKED = 10_000


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits[key]
        while q and now - q[0] >= self._window:
            q.popleft()
        if not q and len(self._hits) > _MAX_TRACKED:
            del self._hits[key]  # bound memory under key-spraying
            return deque()
        return q

    def retry_after(self, key: str) -> float | None:
        """Seconds until ``key`` may act again, or None if it is under the limit."""
        now = self._clock()
        q = self._prune(key, now)
        if len(q) < self._limit:
            return None
        return max(0.0, self._window - (now - q[0]))

    def hit(self, key: str) -> None:
        now = self._clock()
        self._prune(key, now)
        self._hits[key].append(now)

    def acquire(self, key: str) -> float | None:
        """Record a hit unless over the limit. Returns retry-after seconds if rejected."""
        wait = self.retry_after(key)
        if wait is None:
            self.hit(key)
        return wait
