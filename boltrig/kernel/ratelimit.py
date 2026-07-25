"""Rate limiting (FR-KER-05, US-KER-04).

Limits are enforced in the kernel BEFORE any outbound call. The production back
end is Redis (wired from ``REDIS_URL`` at the composition root); an in-memory
back end is used for dev/tests. Both implement the same ``Counter`` protocol.

That sentence was FALSE for a long time and is load-bearing, so it is worth
saying why it is now true. ``RedisCounter`` existed but was constructed nowhere:
the kernel always fell back to ``InMemoryCounter``, so every bound was
per-process and per-boot, while this docstring, ``docker-compose.yml`` and the
production readiness check all asserted Redis. A kernel restart silently reset
every rate limit, including the 2FA brute-force bound, and a second worker would
have multiplied every bound by N. Found when a First Instance bench went to
verify a different question about this file
([2026] VJS-CC-BOLTRIG-RATE-LIMIT-WINDOW-001, D1/D3).

WINDOW SEMANTICS, stated here because callers configure against it: the window is
a FIXED calendar window aligned to the epoch, NOT a sliding one. A limit of
``max`` per minute therefore admits up to ``2 * max`` within an arbitrarily short
span that straddles a boundary (five in the closing instant of one minute, five in
the opening instant of the next), while the SUSTAINED rate is preserved. That is a
deliberate trade, ruled on rather than assumed: see the same judgment, and
``tests/security/test_two_factor.py::test_the_window_is_fixed_not_sliding``, which
pins the burst so any move to a sliding window breaks a test that names it.
"""

from __future__ import annotations

import math
import time
from typing import Protocol

from boltrig.models import RateLimit, RateLimited


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
        rkey = f"boltrig:rl:{key}:{window}"
        count = await self._r.incr(rkey)
        if count == 1:
            await self._r.expire(rkey, window_seconds)
        return count


def build_counter(redis_url: str | None, *, timeout_s: float = 2.0) -> Counter:
    """The counter the kernel should use: Redis when a URL is configured.

    The composition root calls this so the shipped limiter is shared across
    processes and survives a restart. Falls back to the in-memory counter when no
    URL is set (dev, tests, and the offline suite), which is the documented
    dev/test backend rather than a silent production downgrade: production
    readiness independently REQUIRES Redis (``api/readiness.py``), so a
    production deployment that reached the fallback would already be failing its
    readiness gate loudly.
    """
    if not redis_url or not redis_url.strip():
        return InMemoryCounter()
    from redis.asyncio import Redis

    return RedisCounter(
        Redis.from_url(
            redis_url.strip(),
            socket_connect_timeout=timeout_s,
            socket_timeout=timeout_s,
        )
    )


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
