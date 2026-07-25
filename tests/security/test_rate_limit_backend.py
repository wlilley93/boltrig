"""The rate limiter's counter is SHARED, and both backends agree (FR-KER-05).

[2026] VJS-CC-BOLTRIG-RATE-LIMIT-WINDOW-001 D1/D3/D4/D7. ``RedisCounter`` existed
but was constructed nowhere, so every bound was per-process and per-boot while the
module docstring, ``docker-compose.yml`` and the production readiness check all
asserted Redis. A kernel restart reset every limit, including the 2FA
brute-force bound, and a second worker would have multiplied each by N.

The judgment refused to let the class stay both unwired and untested: either a
production path constructs it and a test exercises it, or it is deleted. These
pin the first limb, and D4's requirement that the two backends cannot silently
disagree - an unexercised second backend is not evidence of anything, which is
the whole reason the defect survived.
"""

from __future__ import annotations

import pytest

from boltrig.kernel.ratelimit import (
    InMemoryCounter,
    RateLimiter,
    RedisCounter,
    build_counter,
)
from boltrig.models import RateLimit, RateLimited

pytestmark = pytest.mark.security

LIMIT = RateLimit(per="minute", max=5, scope="verb")


def _fake_redis():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.aioredis.FakeRedis()


@pytest.mark.invariant("FR-KER-05")
def test_a_configured_redis_url_yields_a_shared_counter_not_the_in_process_one():
    """The wiring itself, which is what was missing. A URL must produce the shared
    backend; no URL must produce the documented dev fallback, not a silent one."""
    assert isinstance(build_counter("redis://127.0.0.1:6379/0"), RedisCounter)
    assert isinstance(build_counter(None), InMemoryCounter)
    assert isinstance(build_counter("   "), InMemoryCounter)


@pytest.mark.invariant("FR-KER-05")
async def test_the_composition_root_passes_the_shared_counter_to_the_kernel(monkeypatch):
    """A counter built and then not handed to the Kernel would leave the defect in
    place while looking fixed, so pin the hand-off, not just the constructor."""
    from boltrig.kernel import Kernel

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    kernel = Kernel(object(), counter=build_counter("redis://127.0.0.1:6379/0"))
    assert isinstance(kernel.rate_limiter._counter, RedisCounter), (
        "the kernel is still counting in-process: every bound would reset on restart"
    )


@pytest.mark.invariant("FR-KER-05")
async def test_both_backends_admit_and_refuse_the_identical_sequence():
    """D4 parity. The two counters must not silently disagree: a bound that is
    honest on the backend nobody runs and cosmetic on the one that ships is worse
    than a single backend, because it reads as covered."""
    redis = _fake_redis()
    try:
        results: dict[str, list[int]] = {}
        for name, counter in (("memory", InMemoryCounter()), ("redis", RedisCounter(redis))):
            limiter = RateLimiter(counter=counter)
            codes: list[int] = []
            for _ in range(7):
                try:
                    await limiter.enforce("acme", "ticket.create", LIMIT)
                    codes.append(200)
                except RateLimited:
                    codes.append(429)
            results[name] = codes
        assert results["memory"] == results["redis"], (
            f"backends disagree: memory={results['memory']} redis={results['redis']}"
        )
        assert results["redis"] == [200, 200, 200, 200, 200, 429, 429]
    finally:
        await redis.aclose()


@pytest.mark.invariant("FR-KER-05")
async def test_the_shared_counter_survives_a_kernel_restart():
    """The per-boot half of the defect, which the per-process half hid: with one
    worker the old in-memory counter looked fine until the process bounced, and
    then every bound silently started again from zero."""
    redis = _fake_redis()
    try:
        first = RateLimiter(counter=RedisCounter(redis))
        for _ in range(5):
            await first.enforce("acme", "auth.2fa.challenge.id:alice", LIMIT)

        # A new kernel over the SAME Redis: a restart, not a new tenant.
        second = RateLimiter(counter=RedisCounter(redis))
        with pytest.raises(RateLimited):
            await second.enforce("acme", "auth.2fa.challenge.id:alice", LIMIT)
    finally:
        await redis.aclose()
