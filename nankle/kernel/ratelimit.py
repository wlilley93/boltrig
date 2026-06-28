"""Rate limiting (FR-KER-05, US-KER-04).

Limits are enforced in the kernel BEFORE any outbound call. Counters use a
fixed window. The production back end is Redis; an in-memory back end is used
for dev/tests. Both implement the same ``Counter`` protocol.
"""

from __future__ import annotations

import math
import time
from typing import Protocol

from nankle.models import RateLimit, RateLimited


class Counter(Protocol):
    async def incr(self, key: str, window_seconds: int) -> int:
        """Increment the counter for ``key`` within its current window and
        return the new count."""
        ...


class InMemoryCounter:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, int], int] = {}

    def _now(self) -> float:
        return time.time()

    async def incr(self, key: str, window_seconds: int) -> int:
        window = int(self._now() // window_seconds)
        bkey = (key, window)
        self._buckets[bkey] = self._buckets.get(bkey, 0) + 1
        # opportunistic cleanup of stale windows
        for k in [k for k in self._buckets if k[0] == key and k[1] != window]:
            del self._buckets[k]
        return self._buckets[bkey]


class RedisCounter:
    """Redis fixed-window counter. INCR + EXPIRE on first hit of a window."""

    def __init__(self, redis) -> None:  # redis.asyncio.Redis
        self._r = redis

    async def incr(self, key: str, window_seconds: int) -> int:
        window = int(time.time() // window_seconds)
        rkey = f"nankle:rl:{key}:{window}"
        count = await self._r.incr(rkey)
        if count == 1:
            await self._r.expire(rkey, window_seconds)
        return count


_WINDOW_SECONDS = {"minute": 60, "hour": 3600}


class RateLimiter:
    def __init__(self, counter: Counter | None = None) -> None:
        self._counter = counter or InMemoryCounter()

    async def enforce(self, tenant_id: str, verb_id: str, rl: RateLimit | None) -> None:
        """Raise ``RateLimited`` if this call would exceed the configured limit."""
        if rl is None:
            return
        window_seconds = _WINDOW_SECONDS.get(rl.per, 60)
        scope = tenant_id if rl.scope == "tenant" else f"{tenant_id}:{verb_id}"
        key = f"{scope}:{verb_id}" if rl.scope == "verb" else scope
        count = await self._counter.incr(key, window_seconds)
        if count > rl.max:
            # crude retry-after: time to the next window boundary
            retry_after = window_seconds - (math.floor(time.time()) % window_seconds)
            raise RateLimited(
                f"rate limit exceeded for '{verb_id}' ({rl.max}/{rl.per})",
                retry_after_seconds=float(retry_after),
            )
