"""Retry and cooperative rate-limit policy for outbound HTTP adapters."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry settings used only for idempotent HTTP methods."""

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    backoff_factor: float = 2.0


@dataclass(frozen=True)
class RateLimitConfig:
    """Cooperative client-side rate limit (FR-KER-05)."""

    max: int = 600
    per: str = "minute"
    scope: str = "tenant"

    def window_seconds(self) -> float:
        return {"second": 1.0, "minute": 60.0, "hour": 3600.0}.get(self.per, 60.0)

    def as_spec(self) -> dict[str, object]:
        """Shape consumed by ``VerbSpec.rate_limit`` and the registry."""
        return {"per": self.per, "max": self.max, "scope": self.scope}


class RateLimiter:
    """A small in-process sliding-window limiter, one per adapter instance."""

    def __init__(self, config: RateLimitConfig) -> None:
        self._max = max(0, config.max)
        self._window = config.window_seconds()
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._max <= 0:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                self._evict(now)
                if len(self._calls) < self._max:
                    self._calls.append(now)
                    return
                sleep_for = self._window - (now - self._calls[0])
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    def _evict(self, now: float) -> None:
        while self._calls and now - self._calls[0] > self._window:
            self._calls.popleft()
