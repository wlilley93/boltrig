"""Independent bounded lifetime window for Codex native subagents."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from boltrig.fleet.domain import RuntimeEvent, RuntimeEventKind

from .codex_runtime_event_state import CodexRuntimeProtocolError

DEFAULT_NATIVE_SUBAGENT_LIFETIME_SECONDS = 120.0


def validate_native_subagent_lifetime(value: object) -> float:
    if type(value) not in {int, float}:
        raise TypeError("native subagent lifetime must be a finite positive number")
    lifetime = float(cast("int | float", value))
    if not math.isfinite(lifetime) or not 0 < lifetime <= 3600:
        raise ValueError("native subagent lifetime is outside the runtime bound")
    return lifetime


@dataclass
class NativeSubagentLifetimeState:
    """Mutable state for one uninterrupted non-empty native-agent window."""

    seconds: float | None
    active: int = 0
    task: asyncio.Task[None] | None = None


def native_subagent_lifetime_state(
    seconds: float | None,
) -> NativeSubagentLifetimeState:
    if seconds is not None and (
        type(seconds) not in {int, float}
        or not math.isfinite(float(seconds))
        or not 0 < float(seconds) <= 3600
    ):
        raise ValueError("native subagent lifetime must be finite and bounded")
    return NativeSubagentLifetimeState(
        seconds=None if seconds is None else float(seconds)
    )


def observe_native_subagent_event(
    state: NativeSubagentLifetimeState,
    event: RuntimeEvent,
    on_expired: Callable[[], Awaitable[None]],
) -> None:
    if event.kind is RuntimeEventKind.NATIVE_SUBAGENT_STARTED:
        if state.seconds is None:
            raise CodexRuntimeProtocolError(
                "native subagent lifetime enforcement is not configured"
            )
        if state.active == 0:
            state.task = asyncio.create_task(
                _expire_native_subagent_lifetime(state.seconds, on_expired),
                name="codex-native-subagent-lifetime",
            )
        state.active += 1
    elif event.kind is RuntimeEventKind.NATIVE_SUBAGENT_COMPLETED:
        if state.active <= 0:
            raise CodexRuntimeProtocolError(
                "native subagent lifetime state is inconsistent"
            )
        state.active -= 1
        if state.active == 0:
            cancel_native_subagent_lifetime(state)


def cancel_native_subagent_lifetime(state: NativeSubagentLifetimeState) -> None:
    task = state.task
    if task is not None and task is not asyncio.current_task():
        task.cancel()
    state.task = None


async def _expire_native_subagent_lifetime(
    seconds: float,
    on_expired: Callable[[], Awaitable[None]],
) -> None:
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    await on_expired()
