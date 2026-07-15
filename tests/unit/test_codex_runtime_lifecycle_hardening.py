from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast

import pytest

from boltrig.fleet.domain import RuntimeEvent, RuntimeEventKind, RuntimeThreadRef
from boltrig.fleet.infrastructure.codex_agent_runtime import CodexAgentRuntime
from boltrig.fleet.infrastructure.codex_runtime_events import CodexRuntimeProtocolError
from boltrig.fleet.ports.runtime import RuntimeTurnSpec

from .codex_runtime_fakes import (
    FakeCellProvider,
    FakeCodexCell,
    admission,
    leased_cell,
    thread_spec,
)


async def _started_runtime(
    *, max_buffered_events: int = 256
) -> tuple[CodexAgentRuntime, RuntimeThreadRef, FakeCodexCell]:
    admitted = admission()
    leased, cell = leased_cell(admitted)
    runtime = CodexAgentRuntime(
        FakeCellProvider(leased),
        allow_test_only_runtime=True,
        max_buffered_events=max_buffered_events,
    )
    thread = await runtime.start_thread(thread_spec(admitted))
    return runtime, thread, cell


async def _eventually(predicate: Callable[[], bool]) -> None:
    for _attempt in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not observed")


async def test_queued_invalidation_retires_phase_without_an_events_consumer() -> None:
    runtime, thread, cell = await _started_runtime()

    await cell.client.notify("skills/changed", {})
    await asyncio.wait_for(cell.initialized.wait_closed(), timeout=1)

    with pytest.raises(CodexRuntimeProtocolError, match="invalidated"):
        await runtime.start_turn(RuntimeTurnSpec(thread, "Investigate", "message-1"))
    assert [name for name, _values in cell.client.calls] == ["thread_start"]


async def test_invalidation_racing_gated_turn_rpc_preserves_terminal_cause() -> None:
    runtime, thread, cell = await _started_runtime()
    cell.client.turn_start_gate = asyncio.Event()
    starting = asyncio.create_task(
        runtime.start_turn(RuntimeTurnSpec(thread, "Investigate", "message-1"))
    )
    await _eventually(
        lambda: [name for name, _values in cell.client.calls]
        == ["thread_start", "turn_start"]
    )

    await cell.client.notify("thread/settings/updated", {"model": "rerouted"})
    await asyncio.wait_for(cell.initialized.wait_closed(), timeout=1)

    with pytest.raises(CodexRuntimeProtocolError, match="invalidated"):
        await starting
    assert cell.close_calls == 1


@pytest.mark.parametrize("consumer", ["none", "slow"])
async def test_normalized_queue_overflow_fails_closed_for_slow_or_absent_consumer(
    consumer: str,
) -> None:
    runtime, thread, cell = await _started_runtime(max_buffered_events=1)
    stream = runtime.events(thread)
    if consumer == "slow":
        assert (await anext(stream)).kind is RuntimeEventKind.THREAD_STARTED

    await cell.client.notify("warning", {"message": "first"})
    if consumer == "slow":
        await cell.client.notify("warning", {"message": "second"})
    await asyncio.wait_for(cell.initialized.wait_closed(), timeout=1)

    with pytest.raises(CodexRuntimeProtocolError, match="queue overflowed"):
        await anext(stream)
    assert cell.closed


async def test_actor_is_the_only_client_notification_reader() -> None:
    runtime, thread, cell = await _started_runtime()
    await _eventually(lambda: cell.client.active_notification_readers == 1)
    stream = runtime.events(thread)
    assert (await anext(stream)).kind is RuntimeEventKind.THREAD_STARTED
    waiting: asyncio.Future[object] = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)

    assert cell.client.active_notification_readers == 1
    assert cell.client.max_notification_readers == 1
    assert await runtime.resume_thread(thread) == thread
    assert cell.client.max_notification_readers == 1

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await runtime.close_thread(thread)


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("model/rerouted", {"fromModel": "one", "toModel": "two"}),
        ("thread/settings/updated", {"threadId": "thread-1"}),
        ("mcpServer/oauthLogin/completed", {"name": "unexpected"}),
        ("app/list/updated", {"apps": []}),
    ],
)
async def test_additional_runtime_invalidation_methods_fail_closed(
    method: str,
    params: dict[str, Any],
) -> None:
    runtime, thread, cell = await _started_runtime()

    await cell.client.notify(method, params)
    await asyncio.wait_for(cell.initialized.wait_closed(), timeout=1)

    with pytest.raises(CodexRuntimeProtocolError, match="invalidated"):
        await anext(runtime.events(thread))
    assert cell.closed


async def test_cancelled_consumer_can_reconnect_without_replacing_actor_reader() -> None:
    runtime, thread, cell = await _started_runtime()
    first = runtime.events(thread)
    assert (await anext(first)).kind is RuntimeEventKind.THREAD_STARTED
    waiting: asyncio.Future[object] = asyncio.ensure_future(anext(first))
    await asyncio.sleep(0)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    second = runtime.events(thread)
    await cell.client.notify("warning", {"message": "bounded"})
    assert (await anext(second)).kind is RuntimeEventKind.WARNING
    assert cell.client.max_notification_readers == 1
    await cast(AsyncGenerator[RuntimeEvent, None], second).aclose()
    await runtime.close_thread(thread)


async def test_cleanup_failure_does_not_replace_primary_protocol_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, thread, cell = await _started_runtime()

    async def fail_close() -> None:
        raise RuntimeError("SECRET cleanup detail")

    monkeypatch.setattr(cell.client, "aclose", fail_close)
    await cell.client.notify("app/list/updated", {})
    await asyncio.wait_for(cell.initialized.wait_closed(), timeout=1)

    with pytest.raises(CodexRuntimeProtocolError, match="invalidated") as caught:
        await anext(runtime.events(thread))
    assert "SECRET cleanup detail" not in str(caught.value)
    assert cell.initialized.cleanup_failed
