"""Thin phase lifecycle use case with no runtime-vendor dependencies."""

from __future__ import annotations

from boltrig.fleet.domain import (
    CanonicalJSON,
    PhaseAssignmentRef,
    RuntimeThreadRef,
    RuntimeTurnRef,
)
from boltrig.fleet.ports import (
    AgentRuntime,
    RuntimeThreadSpec,
    RuntimeTurnSpec,
    TurnSteerRequest,
)


class RuntimeBindingError(RuntimeError):
    """A runtime returned or received a thread/turn for another assignment."""


def _require_assignment(
    expected: PhaseAssignmentRef, thread: RuntimeThreadRef
) -> RuntimeThreadRef:
    if thread.assignment != expected:
        raise RuntimeBindingError("runtime thread is bound to another phase assignment")
    return thread


class PhaseLifecycle:
    """Coordinate runtime lifecycle while Boltrig retains durable ownership."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def start(
        self,
        thread_spec: RuntimeThreadSpec,
        *,
        prompt: str,
        client_message_id: str,
        output_schema: CanonicalJSON | None = None,
    ) -> RuntimeTurnRef:
        thread = _require_assignment(
            thread_spec.assignment,
            await self._runtime.start_thread(thread_spec),
        )
        bound_turn = RuntimeTurnSpec(
            thread=thread,
            prompt=prompt,
            client_message_id=client_message_id,
            output_schema=output_schema,
        )
        turn = await self._runtime.start_turn(bound_turn)
        if turn.thread != thread:
            raise RuntimeBindingError("runtime turn is bound to another thread")
        return turn

    async def resume(
        self, assignment: PhaseAssignmentRef, thread: RuntimeThreadRef
    ) -> RuntimeThreadRef:
        expected = _require_assignment(assignment, thread)
        resumed = await self._runtime.resume_thread(expected)
        if resumed != expected:
            raise RuntimeBindingError("runtime resumed a different thread binding")
        return resumed

    async def steer(
        self, assignment: PhaseAssignmentRef, request: TurnSteerRequest
    ) -> RuntimeTurnRef:
        _require_assignment(assignment, request.turn.thread)
        steered = await self._runtime.steer_turn(request)
        if steered != request.turn:
            raise RuntimeBindingError("runtime steered a different turn binding")
        return steered

    async def interrupt(
        self, assignment: PhaseAssignmentRef, turn: RuntimeTurnRef
    ) -> None:
        _require_assignment(assignment, turn.thread)
        await self._runtime.interrupt_turn(turn)
