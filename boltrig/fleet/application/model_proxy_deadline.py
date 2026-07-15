"""Conservative event-loop monotonic deadlines for model-proxy issuance."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import math


class ModelProxyIssuanceDeadline:
    __slots__ = ("_at",)

    def __init__(self, at: float) -> None:
        if type(at) is not float or not math.isfinite(at):
            raise ValueError("model-proxy issuance deadline must be a finite float")
        self._at = at

    @classmethod
    def start(cls, ttl_seconds: int) -> ModelProxyIssuanceDeadline:
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("model-proxy issuance TTL must be a positive integer")
        return cls(_event_loop_time() + ttl_seconds)

    @property
    def elapsed(self) -> bool:
        return _event_loop_time() >= self._at

    @property
    def remaining(self) -> float:
        return max(0.0, self._at - _event_loop_time())

    def schedule(self, callback: Callable[..., None], *args: object) -> None:
        remaining = self.remaining
        if remaining <= 0:
            raise ModelProxyDeadlineElapsed("model-proxy issuance deadline elapsed")
        try:
            _schedule_after(remaining, callback, *args)
        except Exception:
            raise ModelProxyDeadlineElapsed("model-proxy expiry scheduling failed") from None


class ModelProxyDeadlineElapsed(RuntimeError):
    pass


def _event_loop_time() -> float:
    return asyncio.get_running_loop().time()


def _schedule_after(delay: float, callback: Callable[..., None], *args: object) -> None:
    asyncio.get_running_loop().call_later(delay, callback, *args)


__all__ = ["ModelProxyDeadlineElapsed", "ModelProxyIssuanceDeadline"]
