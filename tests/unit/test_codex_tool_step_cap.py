"""The per-turn tool-step budget: a runaway weak-model loop stops honestly.

Before any cap existed, a small model looping on its one-tool harness burned
9+ minutes of wall-clock per turn (measured on the beelink stack, ~231s per
model call on dev). The budget bounds the TURN's tool work at the drain, and
the runtime interrupts the turn and degrades with the paid-for usage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from boltrig.fleet.codex_runtime import CodexRuntime
from boltrig.fleet.codex_runtime_support import (
    TOOL_ITEM_TYPES,
    ToolBudgetExhausted,
    drain_until_complete,
)
from boltrig.fleet.domain.execution import (
    CanonicalJSON,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
)

from .test_codex_runtime import _FakeLifecycle, _context


def _item(thread: RuntimeThreadRef, n: int, item_type: str) -> RuntimeEvent:
    return RuntimeEvent(
        event_id=f"item-{n}",
        assignment=thread.assignment,
        kind=RuntimeEventKind.ITEM_STARTED,
        thread=thread,
        payload=CanonicalJSON.from_mapping({"item_type": item_type}),
    )


def _usage(thread: RuntimeThreadRef, n: int, total: int) -> RuntimeEvent:
    return RuntimeEvent(
        event_id=f"usage-{n}",
        assignment=thread.assignment,
        kind=RuntimeEventKind.TOKEN_USAGE,
        thread=thread,
        payload=CanonicalJSON.from_mapping(
            {"total_tokens": total, "input_tokens": total - 5, "output_tokens": 5}
        ),
    )


def _completed(thread: RuntimeThreadRef) -> RuntimeEvent:
    return RuntimeEvent(
        event_id="done",
        assignment=thread.assignment,
        kind=RuntimeEventKind.TURN_COMPLETED,
        thread=thread,
    )


async def _stream(events: list[RuntimeEvent]) -> AsyncIterator[RuntimeEvent]:
    for event in events:
        yield event


def _thread() -> RuntimeThreadRef:
    from boltrig.fleet.codex_runtime_support import mint_assignment

    assignment = mint_assignment(_context(), "run-1", "ws-1")
    return RuntimeThreadRef(assignment, "codex_app_server", "thr-1")


async def test_the_cap_trips_on_the_step_after_the_budget():
    thread = _thread()
    events = [_usage(thread, 0, 40)]
    events += [_item(thread, n, "mcpToolCall") for n in range(3)]
    with pytest.raises(ToolBudgetExhausted) as exhausted:
        await drain_until_complete(_stream(events), max_tool_steps=2)
    # The third START trips; at most two tool steps ever complete, and the
    # spend already reported rides out with the refusal.
    assert exhausted.value.steps == 3
    assert exhausted.value.tokens == 40


async def test_thinking_is_not_a_step_and_completion_under_budget_returns():
    thread = _thread()
    events = [
        _item(thread, 0, "reasoning"),
        _item(thread, 1, "agentMessage"),
        _item(thread, 2, "mcpToolCall"),
        _usage(thread, 3, 99),
        _completed(thread),
    ]
    assert await drain_until_complete(_stream(events), max_tool_steps=1) == 99


async def test_no_cap_means_the_operator_chose_unbounded():
    thread = _thread()
    events = [_item(thread, n, "commandExecution") for n in range(50)]
    events.append(_completed(thread))
    assert await drain_until_complete(_stream(events), max_tool_steps=None) == 0


async def test_every_declared_tool_type_counts():
    thread = _thread()
    for item_type in sorted(TOOL_ITEM_TYPES):
        events = [_item(thread, 0, item_type), _item(thread, 1, item_type)]
        with pytest.raises(ToolBudgetExhausted):
            await drain_until_complete(_stream(events), max_tool_steps=1)


class _LoopingLifecycle(_FakeLifecycle):
    """A model that calls its one tool forever - the measured failure mode."""

    def __init__(self) -> None:
        super().__init__(text="partial answer")
        self.interrupted: list[RuntimeTurnRef] = []

    async def _events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]:
        n = 0
        while True:  # never completes on its own
            yield _usage(thread, n, 10 * (n + 1))
            yield _item(thread, n, "mcpToolCall")
            n += 1

    async def interrupt_turn(self, turn: RuntimeTurnRef) -> None:
        self.interrupted.append(turn)


async def test_a_looping_turn_is_interrupted_and_degrades_with_its_spend():
    fake = _LoopingLifecycle()
    runtime = CodexRuntime(fake, stack_root=Path("/stack"), max_tool_steps=4)

    result = await runtime.run("spin", _context(), tools=[])

    assert result.ok is True and result.degraded is True
    assert result.degrade_reason == "codex_tool_budget_exhausted:4"
    assert result.tokens_used == 50  # the spend that already happened
    assert [turn.turn_id for turn in fake.interrupted] == ["turn-1"]
    assert fake.closed is True  # the thread is closed even on a budget stop
