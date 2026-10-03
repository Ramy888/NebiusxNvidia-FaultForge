import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    """Sliding-window limit per client. `check` returns 0 if allowed, else seconds to wait."""

    def __init__(self, max_requests: int, window_s: float, clock: Callable[[], float] = time.time):
        self._max, self._window, self._clock = max_requests, window_s, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return max(1, math.ceil(hits[0] + self._window - now))
            hits.append(now)
            return 0
