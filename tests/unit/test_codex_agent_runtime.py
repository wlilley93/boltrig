from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, cast

import pytest

from boltrig.fleet.domain import (
    CanonicalJSON,
    OrganisationUserRef,
    PhaseAssignmentRef,
    PhaseMode,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
    SandboxPolicy,
)
from boltrig.fleet.infrastructure.codex_agent_runtime import (
    CodexAgentRuntime,
    CodexRuntimeBindingError,
    CodexRuntimeOperationError,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import CodexRuntimeAdmissionError
from boltrig.fleet.infrastructure.codex_runtime_events import CodexRuntimeProtocolError
from boltrig.fleet.ports.runtime import RuntimeTurnSpec, TurnSteerRequest

from .codex_runtime_fakes import (
    FakeCellProvider,
    FakeCodexCell,
    admission,
    collect,
    leased_cell,
    thread_spec,
    wrong_thread,
)


async def _started_runtime() -> tuple[
    CodexAgentRuntime, RuntimeThreadRef, FakeCodexCell, FakeCellProvider
]:
    admitted = admission()
    leased, cell = leased_cell(admitted)
    provider = FakeCellProvider(leased)
    runtime = CodexAgentRuntime(provider, allow_test_only_runtime=True)
    thread = await runtime.start_thread(thread_spec(admitted))
    return runtime, thread, cell, provider


def test_runtime_is_off_by_default_until_production_isolation_is_proven() -> None:
    with pytest.raises(CodexRuntimeOperationError, match="isolation controls"):
        CodexAgentRuntime(FakeCellProvider())


async def test_start_thread_uses_only_exact_admission_policy_and_one_cell() -> None:
    admitted = admission()
    leased, cell = leased_cell(admitted)
    provider = FakeCellProvider(leased)
    runtime = CodexAgentRuntime(provider, allow_test_only_runtime=True)
    spec = replace(
        thread_spec(admitted),
        metadata=CanonicalJSON.from_mapping(
            {
                "working_directory": "/prompt/controlled",
                "model": "prompt-model",
                "sandbox": "danger-full-access",
            }
        ),
    )

    thread = await runtime.start_thread(spec)

    assert thread.assignment == admitted.assignment
    assert thread.runtime == "codex_app_server"
    assert runtime.production_ready is False
    assert provider.calls == [admitted.assignment]
    call, values = cell.client.calls[0]
    assert call == "thread_start"
    assert values == {
        "approval_policy": "never",
        "cwd": admitted.layout.workspace.as_posix(),
        "developer_instructions": admitted.developer_instructions,
        "model": admitted.compilation.policy.model.model_id,
        "sandbox": "read-only",
    }
    await runtime.close_thread(thread)
    assert cell.close_calls == 1


@pytest.mark.parametrize(
    "drift",
    [
        "working_directory",
        "mode",
        "sandbox",
    ],
)
async def test_start_thread_rejects_path_or_write_policy_drift_and_closes_cell(
    drift: str,
) -> None:
    admitted = admission()
    leased, cell = leased_cell(admitted)
    provider = FakeCellProvider(leased)
    runtime = CodexAgentRuntime(provider, allow_test_only_runtime=True)

    spec = thread_spec(admitted)
    if drift == "working_directory":
        spec = replace(spec, working_directory="/srv/other")
    elif drift == "mode":
        spec = replace(spec, mode=PhaseMode.APPROVAL_GATED_WRITE)
    else:
        spec = replace(spec, sandbox=SandboxPolicy.WORKSPACE_WRITE)
    with pytest.raises(CodexRuntimeAdmissionError):
        await runtime.start_thread(spec)

    if drift == "working_directory":
        assert cell.closed
    else:
        assert provider.calls == [] and not cell.closed


async def test_one_phase_owner_and_exact_thread_binding_are_enforced() -> None:
    admitted = admission()
    alternate_assignment = PhaseAssignmentRef(
        replace(
            admitted.assignment.phase,
            principal=OrganisationUserRef("org-1", "other-user"),
        ),
        "assignment-alternate",
    )
    alternate = admission(alternate_assignment)
    first, first_cell = leased_cell(admitted)
    second, second_cell = leased_cell(alternate)
    provider = FakeCellProvider(first, second)
    runtime = CodexAgentRuntime(provider, allow_test_only_runtime=True)
    thread = await runtime.start_thread(thread_spec(admitted))

    with pytest.raises(CodexRuntimeBindingError, match="already has"):
        await runtime.start_thread(thread_spec(alternate))
    with pytest.raises(CodexRuntimeBindingError, match="not active"):
        await runtime.resume_thread(wrong_thread(thread))

    assert provider.calls == [admitted.assignment]
    assert not second_cell.closed
    await runtime.close_thread(thread)
    assert first_cell.closed


async def test_live_cell_resume_steer_interrupt_and_close_preserve_exact_ids() -> None:
    runtime, thread, cell, _provider = await _started_runtime()
    assert await runtime.resume_thread(thread) == thread
    turn = await runtime.start_turn(RuntimeTurnSpec(thread, "Investigate", "message-1"))

    assert await runtime.steer_turn(TurnSteerRequest(turn, "More evidence", "message-2")) == turn
    await runtime.interrupt_turn(turn)
    names = [name for name, _values in cell.client.calls]
    assert names == ["thread_start", "thread_resume", "turn_start", "turn_steer", "turn_interrupt"]
    assert cell.client.calls[-2][1]["expected_turn_id"] == turn.turn_id
    assert cell.client.calls[-1][1] == {
        "thread_id": thread.thread_id,
        "turn_id": turn.turn_id,
    }
    await runtime.close_thread(thread)
    with pytest.raises(CodexRuntimeBindingError, match="closed"):
        await runtime.resume_thread(thread)


async def test_resume_fails_closed_after_live_cell_process_loss() -> None:
    runtime, thread, cell, _provider = await _started_runtime()
    cell.returncode = 137

    with pytest.raises(CodexRuntimeBindingError, match="live Codex cell"):
        await runtime.resume_thread(thread)

    assert cell.closed


async def test_cancellation_during_thread_start_closes_ambiguous_cell() -> None:
    admitted = admission()
    leased, cell = leased_cell(admitted)
    cell.client.thread_start_gate = asyncio.Event()
    runtime = CodexAgentRuntime(
        FakeCellProvider(leased), allow_test_only_runtime=True
    )
    starting = asyncio.create_task(runtime.start_thread(thread_spec(admitted)))
    while not cell.client.calls:
        await asyncio.sleep(0)

    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting

    assert cell.closed and cell.close_calls == 1


async def test_cancellation_during_turn_start_closes_and_retires_binding() -> None:
    runtime, thread, cell, _provider = await _started_runtime()
    cell.client.turn_start_gate = asyncio.Event()
    starting = asyncio.create_task(
        runtime.start_turn(RuntimeTurnSpec(thread, "SECRET prompt", "message-1"))
    )
    while len(cell.client.calls) < 2:
        await asyncio.sleep(0)

    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting

    assert cell.closed
    with pytest.raises(CodexRuntimeOperationError, match="cancelled"):
        await runtime.resume_thread(thread)


async def test_cancelling_event_consumer_does_not_control_the_live_cell() -> None:
    runtime, thread, cell, _provider = await _started_runtime()
    stream = runtime.events(thread)
    assert (await anext(stream)).kind is RuntimeEventKind.THREAD_STARTED
    waiting: asyncio.Future[object] = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert not cell.closed
    assert await runtime.resume_thread(thread) == thread
    await runtime.close_thread(thread)


async def test_notifications_are_bounded_normalized_and_never_copy_content() -> None:
    runtime, thread, cell, _provider = await _started_runtime()
    turn = await runtime.start_turn(RuntimeTurnSpec(thread, "SECRET prompt", "message-1"))
    notifications = [
        (
            "item/started",
            {
                "item": {"id": "item-1", "text": "SECRET answer", "type": "agentMessage"},
                "startedAtMs": 1,
                "threadId": thread.thread_id,
                "turnId": turn.turn_id,
            },
        ),
        (
            "item/agentMessage/delta",
            {
                "delta": "SECRET delta",
                "itemId": "item-1",
                "threadId": thread.thread_id,
                "turnId": turn.turn_id,
            },
        ),
        ("warning", {"message": "SECRET warning", "threadId": thread.thread_id}),
        (
            "error",
            {
                "error": {"message": "SECRET error"},
                "threadId": thread.thread_id,
                "turnId": turn.turn_id,
                "willRetry": False,
            },
        ),
        (
            "item/completed",
            {
                "completedAtMs": 3,
                "item": {"id": "item-1", "text": "SECRET answer", "type": "agentMessage"},
                "threadId": thread.thread_id,
                "turnId": turn.turn_id,
            },
        ),
        ("turn/completed", {"threadId": thread.thread_id, "turn": _turn(turn, "completed")}),
    ]
    for method, params in notifications:
        await cell.client.notify(method, cast(dict[str, Any], params))

    stream = runtime.events(thread)
    events = await collect(stream, len(notifications) + 2)

    assert [event.kind for event in events] == [
        RuntimeEventKind.THREAD_STARTED,
        RuntimeEventKind.TURN_STARTED,
        RuntimeEventKind.ITEM_STARTED,
        RuntimeEventKind.UNKNOWN,
        RuntimeEventKind.WARNING,
        RuntimeEventKind.ERROR,
        RuntimeEventKind.ITEM_COMPLETED,
        RuntimeEventKind.TURN_COMPLETED,
    ]
    assert all(event.assignment == thread.assignment for event in events)
    assert set(events[3].payload.to_mapping()) == {"method_digest"}
    serialized = repr([(event.item_id, event.payload.to_mapping()) for event in events])
    assert "SECRET" not in serialized
    assert "SECRET prompt" not in repr(runtime._states)  # noqa: SLF001
    await runtime.close_thread(thread)


async def test_cross_thread_notification_fails_closed_and_reaps_cell() -> None:
    runtime, thread, cell, _provider = await _started_runtime()
    turn = await runtime.start_turn(RuntimeTurnSpec(thread, "Investigate", "message-1"))
    await cell.client.notify(
        "item/started",
        {
            "item": {"id": "item-1", "text": "hidden", "type": "agentMessage"},
            "startedAtMs": 1,
            "threadId": "outside-thread",
            "turnId": turn.turn_id,
        },
    )
    iterator = runtime.events(thread)
    await cell.initialized.wait_closed()

    with pytest.raises(CodexRuntimeProtocolError, match="active phase tree"):
        await anext(iterator)

    assert cell.closed


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("skills/changed", {}),
        (
            "mcpServer/startupStatus/updated",
            {"name": "unexpected", "status": "ready"},
        ),
        ("configWarning", {"summary": "configuration changed"}),
    ],
)
async def test_post_start_config_or_inventory_invalidation_retires_phase(
    method: str,
    params: dict[str, Any],
) -> None:
    runtime, thread, cell, _provider = await _started_runtime()
    await cell.client.notify(method, params)
    iterator = runtime.events(thread)
    await cell.initialized.wait_closed()

    with pytest.raises(CodexRuntimeProtocolError, match="invalidated"):
        await anext(iterator)

    assert cell.closed


def _turn(turn: RuntimeTurnRef, status: str) -> dict[str, object]:
    return {"id": turn.turn_id, "items": [], "status": status}
