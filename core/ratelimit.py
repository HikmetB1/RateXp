"""A tiny in-memory per-client rate limiter (token bucket).

Dependency-free and per-process: each core instance keeps its own buckets, which
is the right granularity for the small single-instance deployment this project
targets. It throttles abusive callers on the public surface without needing
Redis or a sidecar. Set rate_limit_per_minute to 0 in config.yaml to disable.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.refill_per_second = per_minute / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Return True if the caller may proceed, False if over budget."""
        if self.capacity <= 0:  # disabled
            return True
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_second)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True
