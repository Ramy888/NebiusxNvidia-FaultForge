import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime


class RateLimiter:
    """Sliding-window limit per client. `check` returns 0 if allowed, else seconds to wait."""

    def __init__(self, max_requests: int, window_s: float, clock: Callable[[], float] = time.time):
        self._max, self._window, self._clock = max_requests, window_s, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            self._forget_idle(now)
            hits = self._hits[key]
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return max(1, math.ceil(hits[0] + self._window - now))
            hits.append(now)
            return 0

    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._hits)

    def _forget_idle(self, now: float) -> None:
        """Drop clients with no hits in the window, so memory stays bounded."""
        idle = [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - self._window]
        for key in idle:
            del self._hits[key]


class DailyBudget:
    """At most `limit` uses per UTC day: caps how much model spend a public demo can cause."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.time):
        self._limit, self._clock = limit, clock
        self._day, self._used = None, 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            self._roll()
            if self._used >= self._limit:
                return False
            self._used += 1
            return True

    def remaining(self) -> int:
        with self._lock:
            self._roll()
            return max(0, self._limit - self._used)

    def _roll(self) -> None:
        day = datetime.fromtimestamp(self._clock(), UTC).date()
        if day != self._day:
            self._day, self._used = day, 0
