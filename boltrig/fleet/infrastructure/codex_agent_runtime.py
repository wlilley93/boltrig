"""Test-only read-only ``AgentRuntime`` adapter for supervised Codex cells.

The adapter is not production-selectable. It lacks phase-scoped model-proxy
credentials, inherit-none subprocess proof, and complete effective App Server
configuration attestation. Native Codex agents are therefore disabled.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator

from boltrig.fleet.domain import PhaseRef, RuntimeEvent, RuntimeThreadRef, RuntimeTurnRef
from boltrig.fleet.ports.runtime import (
    AgentRuntime,
    RuntimeThreadSpec,
    RuntimeTurnSpec,
    TurnSteerRequest,
)

from .codex_runtime_actor import (
    MAX_BUFFERED_RUNTIME_EVENTS,
    CodexRuntimeActor,
    CodexRuntimeTerminal,
)
from .codex_runtime_admission import AdmittedCodexCell, CodexPhaseCellProvider
from .codex_runtime_events import CodexEventTranslator, CodexRuntimeProtocolError
from .codex_runtime_state import (
    CodexThreadState,
    PhaseKey,
    cleanup_cell_ignoring_failure,
    cleanup_state,
    phase_key,
    require_ready_cell,
    validate_runtime_thread,
)
from .codex_runtime_validation import (
    CodexRuntimeBindingError,
    copied_output_schema,
    runtime_identifier,
    validate_admission,
    validate_steer_request,
    validate_thread_spec,
    validate_turn_ref,
    validate_turn_spec,
)

MAX_ACTIVE_CODEX_PHASES = 64
DEFAULT_ROOT_START_TIMEOUT_SECONDS = 10.0


class CodexRuntimeOperationError(RuntimeError):
    """A Codex operation failed without exposing upstream content."""


class CodexAgentRuntime(AgentRuntime):
    """Own exact live-cell mappings without process-restart continuity."""

    name = "codex_app_server"
    production_ready = False

    def __init__(
        self,
        provider: CodexPhaseCellProvider,
        *,
        max_active_phases: int = MAX_ACTIVE_CODEX_PHASES,
        max_buffered_events: int = MAX_BUFFERED_RUNTIME_EVENTS,
        root_start_timeout_seconds: float = DEFAULT_ROOT_START_TIMEOUT_SECONDS,
        allow_test_only_runtime: bool = False,
    ) -> None:
        if type(allow_test_only_runtime) is not bool or not allow_test_only_runtime:
            raise CodexRuntimeOperationError(
                "Codex runtime requires unresolved production isolation controls"
            )
        if type(max_active_phases) is not int or not 1 <= max_active_phases <= 64:
            raise ValueError("max_active_phases is outside the runtime bound")
        if type(max_buffered_events) is not int or not 1 <= max_buffered_events <= 256:
            raise ValueError("max_buffered_events is outside the runtime bound")
        if type(root_start_timeout_seconds) not in {int, float}:
            raise TypeError("root start timeout must be a finite positive number")
        root_timeout = float(root_start_timeout_seconds)
        if not math.isfinite(root_timeout) or not 0 < root_timeout <= 30:
            raise ValueError("root start timeout is outside the runtime bound")
        self._provider = provider
        self._max_active = max_active_phases
        self._max_buffered_events = max_buffered_events
        self._root_start_timeout = root_timeout
        self._state_lock = asyncio.Lock()
        self._pending_phases: set[PhaseKey] = set()
        self._states: dict[str, CodexThreadState] = {}
        self._terminal_states: dict[str, CodexThreadState] = {}

    async def start_thread(self, spec: RuntimeThreadSpec) -> RuntimeThreadRef:
        validate_thread_spec(spec)
        await self._claim_pending(spec.assignment.phase)
        leased: AdmittedCodexCell | None = None
        state: CodexThreadState | None = None
        try:
            leased = await self._provider.acquire(spec.assignment)
            validate_admission(spec, leased)
            admission = leased.admission
            policy = admission.compilation.policy
            require_ready_cell(leased.cell)
            result = await leased.cell.client.thread_start(
                cwd=admission.layout.workspace.as_posix(),
                model=policy.model.model_id,
                sandbox="read-only",
                approval_policy="never",
                developer_instructions=admission.developer_instructions,
            )
            thread_id = runtime_identifier("thread id", result.thread_id)
            ref = RuntimeThreadRef(spec.assignment, self.name, thread_id)
            translator = CodexEventTranslator(
                assignment=spec.assignment,
                thread=ref,
                cwd=admission.layout.workspace.as_posix(),
                max_native_concurrent=0,
                max_native_total=0,
                max_native_depth=0,
            )
            state = CodexThreadState(
                leased.cell,
                ref,
                admission.layout.workspace.as_posix(),
                policy.model.model_id,
                leased.evidence_digest(),
            )
            actor = CodexRuntimeActor(
                client=leased.cell.client,
                translator=translator,
                on_terminal=lambda _actor, terminal: self._retire(state, terminal),
                max_buffered_events=self._max_buffered_events,
            )
            state.actor = actor
            await self._activate(spec.assignment.phase, state)
            actor.start()
            await actor.wait_for_root(self._root_start_timeout)
            await self._checkpoint(state)
            return ref
        except BaseException as error:
            await self._discard_pending(spec.assignment.phase)
            if state is not None and state.actor is not None:
                await state.actor.fail(_terminal_from_exception(error))
            elif leased is not None:
                await cleanup_cell_ignoring_failure(leased.cell)
            raise

    async def resume_thread(self, thread: RuntimeThreadRef) -> RuntimeThreadRef:
        state = await self._lookup(thread)
        async with state.operation_lock:
            await self._checkpoint(state)
            await state.exact_actor().assert_no_active_turn()
            try:
                result = await state.cell.client.thread_resume(
                    thread.thread_id,
                    cwd=state.cwd,
                    model=state.model,
                    sandbox="read-only",
                    approval_policy="never",
                )
                if result.thread_id != thread.thread_id:
                    raise CodexRuntimeBindingError("Codex resumed another thread")
                await self._checkpoint(state)
                return thread
            except asyncio.CancelledError:
                await self._fail_operation(state, "Codex thread resume was cancelled")
                raise
            except (CodexRuntimeBindingError, CodexRuntimeProtocolError):
                await self._fail_operation(state, "Codex thread resume violated its binding")
                raise
            except Exception:
                await self._fail_operation(state, "Codex thread resume failed")
                raise CodexRuntimeOperationError("Codex thread resume failed") from None

    async def start_turn(self, spec: RuntimeTurnSpec) -> RuntimeTurnRef:
        validate_turn_spec(spec)
        output_schema = copied_output_schema(spec.output_schema)
        state = await self._lookup(spec.thread)
        actor = state.exact_actor()
        async with state.operation_lock:
            await self._checkpoint(state)
            await actor.begin_turn_start()
            try:
                result = await state.cell.client.turn_start(
                    spec.thread.thread_id,
                    prompt=spec.prompt,
                    client_user_message_id=spec.client_message_id,
                    output_schema=output_schema,
                )
                turn = RuntimeTurnRef(
                    spec.thread, runtime_identifier("turn id", result.turn_id)
                )
                await actor.commit_turn_start(turn)
                await self._checkpoint(state)
                return turn
            except asyncio.CancelledError:
                await self._fail_operation(state, "Codex turn start was cancelled")
                raise
            except (CodexRuntimeBindingError, CodexRuntimeProtocolError):
                await self._fail_operation(state, "Codex turn start violated its binding")
                raise
            except Exception:
                await self._fail_operation(state, "Codex turn start failed")
                raise CodexRuntimeOperationError("Codex turn start failed") from None

    async def steer_turn(self, request: TurnSteerRequest) -> RuntimeTurnRef:
        validate_steer_request(request)
        state = await self._lookup(request.turn.thread)
        async with state.operation_lock:
            await self._checkpoint(state)
            await state.exact_actor().assert_active_turn(request.turn)
            try:
                result = await state.cell.client.turn_steer(
                    request.turn.thread.thread_id,
                    expected_turn_id=request.turn.turn_id,
                    prompt=request.prompt,
                    client_user_message_id=request.client_message_id,
                )
                if result.turn_id != request.turn.turn_id:
                    raise CodexRuntimeBindingError("Codex steered another turn")
                await self._checkpoint(state)
                return request.turn
            except asyncio.CancelledError:
                await self._fail_operation(state, "Codex turn steer was cancelled")
                raise
            except (CodexRuntimeBindingError, CodexRuntimeProtocolError):
                await self._fail_operation(state, "Codex turn steer violated its binding")
                raise
            except Exception:
                await self._fail_operation(state, "Codex turn steer failed")
                raise CodexRuntimeOperationError("Codex turn steer failed") from None

    async def interrupt_turn(self, turn: RuntimeTurnRef) -> None:
        validate_turn_ref(turn)
        state = await self._lookup(turn.thread)
        async with state.operation_lock:
            await self._checkpoint(state)
            await state.exact_actor().assert_active_turn(turn)
            try:
                await state.cell.client.turn_interrupt(turn.thread.thread_id, turn.turn_id)
                await self._checkpoint(state)
            except asyncio.CancelledError:
                await self._fail_operation(state, "Codex turn interrupt was cancelled")
                raise
            except (CodexRuntimeBindingError, CodexRuntimeProtocolError):
                await self._fail_operation(state, "Codex turn interrupt violated its binding")
                raise
            except Exception:
                await self._fail_operation(state, "Codex turn interrupt failed")
                raise CodexRuntimeOperationError("Codex turn interrupt failed") from None

    def events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]:
        return self._event_stream(thread)

    async def close_thread(self, thread: RuntimeThreadRef) -> None:
        state = await self._lookup(thread)
        await state.exact_actor().fail(CodexRuntimeTerminal("closed", "Codex thread closed"))
        await self._await_cleanup(state)
        if state.cleanup_failed:
            raise CodexRuntimeOperationError("Codex thread cleanup failed")

    async def read_turn_output(self, thread: RuntimeThreadRef) -> str:
        """The latest turn's assistant text, read back via the ``thread/read`` seam.

        ``events()`` is a deliberately content-free lifecycle ledger (it never
        copies model output, a contract pinned by test), so the turn's actual
        answer is obtained by reading the thread back through the App Server. This
        is a read: it does not steer, resume, or mutate the thread. Returns an
        empty string when no ``agentMessage`` text is present (the caller degrades).
        """
        state = await self._lookup(thread)
        async with state.operation_lock:
            result = await state.cell.client.thread_read(
                thread.thread_id, include_turns=True
            )
        return _latest_agent_message_text(result.payload.to_mapping())

    async def _event_stream(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]:
        state = await self._event_state(thread)
        actor = state.exact_actor()
        await actor.claim_stream()
        try:
            while True:
                try:
                    yield await actor.next_event()
                except RuntimeError:
                    terminal = actor.terminal
                    if terminal is not None and terminal.category == "closed":
                        return
                    if terminal is not None:
                        raise _terminal_exception(terminal) from None
                    raise
        finally:
            await actor.release_stream()

    async def _checkpoint(self, state: CodexThreadState) -> None:
        try:
            await state.exact_actor().checkpoint()
        except RuntimeError:
            terminal = state.exact_actor().terminal
            if terminal is not None:
                raise _terminal_exception(terminal) from None
            raise
        await self._require_current(state)

    async def _fail_operation(self, state: CodexThreadState, message: str) -> None:
        await state.exact_actor().fail(CodexRuntimeTerminal("operation", message))

    async def _claim_pending(self, phase: PhaseRef) -> None:
        key = phase_key(phase)
        async with self._state_lock:
            active = {phase_key(state.ref.assignment.phase) for state in self._states.values()}
            if key in self._pending_phases or key in active:
                raise CodexRuntimeBindingError("phase already has a Codex owner")
            if len(self._pending_phases) + len(self._states) >= self._max_active:
                raise CodexRuntimeBindingError("Codex phase capacity is exhausted")
            self._pending_phases.add(key)

    async def _activate(self, phase: PhaseRef, state: CodexThreadState) -> None:
        key = phase_key(phase)
        async with self._state_lock:
            if (
                key not in self._pending_phases
                or state.ref.thread_id in self._states
                or state.ref.thread_id in self._terminal_states
            ):
                raise CodexRuntimeBindingError("Codex thread binding collided")
            self._pending_phases.remove(key)
            self._states[state.ref.thread_id] = state

    async def _discard_pending(self, phase: PhaseRef) -> None:
        async with self._state_lock:
            self._pending_phases.discard(phase_key(phase))

    async def _lookup(self, thread: RuntimeThreadRef) -> CodexThreadState:
        validate_runtime_thread(thread, self.name)
        async with self._state_lock:
            state = self._states.get(thread.thread_id)
            terminal = self._terminal_states.get(thread.thread_id)
            if state is not None and state.ref == thread:
                return state
            if terminal is not None and terminal.ref == thread:
                raise _terminal_exception(terminal.exact_actor().terminal) from None
        raise CodexRuntimeBindingError("thread binding is not active")

    async def _event_state(self, thread: RuntimeThreadRef) -> CodexThreadState:
        validate_runtime_thread(thread, self.name)
        async with self._state_lock:
            state = self._states.get(thread.thread_id) or self._terminal_states.get(
                thread.thread_id
            )
            if state is None or state.ref != thread:
                raise CodexRuntimeBindingError("thread binding is not available")
            return state

    async def _require_current(self, state: CodexThreadState) -> None:
        terminal = state.exact_actor().terminal
        if terminal is not None:
            raise _terminal_exception(terminal)
        async with self._state_lock:
            bound = self._states.get(state.ref.thread_id) is state
        if not bound:
            raise CodexRuntimeBindingError("Codex thread is not active")
        try:
            require_ready_cell(state.cell)
        except CodexRuntimeBindingError:
            await state.exact_actor().fail(
                CodexRuntimeTerminal("binding", "live Codex cell is no longer available")
            )
            raise

    async def _retire(
        self, state: CodexThreadState, _terminal: CodexRuntimeTerminal
    ) -> None:
        async with self._state_lock:
            if self._states.get(state.ref.thread_id) is state:
                del self._states[state.ref.thread_id]
                self._terminal_states[state.ref.thread_id] = state
                while len(self._terminal_states) > self._max_active:
                    self._terminal_states.pop(next(iter(self._terminal_states)))
            if state.cleanup_task is None:
                state.cleanup_task = asyncio.create_task(cleanup_state(state))
        await self._await_cleanup(state)

    async def _await_cleanup(self, state: CodexThreadState) -> None:
        task = state.cleanup_task
        if task is not None:
            await asyncio.shield(task)


def _terminal_from_exception(error: BaseException) -> CodexRuntimeTerminal:
    if isinstance(error, CodexRuntimeProtocolError):
        return CodexRuntimeTerminal("protocol", str(error))
    if isinstance(error, CodexRuntimeBindingError):
        return CodexRuntimeTerminal("binding", str(error))
    return CodexRuntimeTerminal("operation", "Codex phase start failed")


def _latest_agent_message_text(payload: object) -> str:
    """Extract the latest ``agentMessage`` text from a ``thread/read`` payload.

    Traverses ``thread.turns[-1].items[]`` for entries of type ``agentMessage``
    and joins their text. Content-defensive: any missing or misshaped node yields
    an empty string rather than raising, so a malformed read never crashes a run.
    """
    thread = payload.get("thread") if isinstance(payload, dict) else None
    turns = thread.get("turns") if isinstance(thread, dict) else None
    if not isinstance(turns, list) or not turns:
        return ""
    last = turns[-1]
    items = last.get("items") if isinstance(last, dict) else None
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if (
            isinstance(item, dict)
            and item.get("type") == "agentMessage"
            and isinstance(item.get("text"), str)
        ):
            parts.append(item["text"])
    return "\n".join(part for part in parts if part)


def _terminal_exception(terminal: CodexRuntimeTerminal | None) -> Exception:
    if terminal is None:
        return CodexRuntimeBindingError("Codex thread is not active")
    if terminal.category == "protocol":
        return CodexRuntimeProtocolError(terminal.message)
    if terminal.category == "binding" or terminal.category == "closed":
        return CodexRuntimeBindingError(terminal.message)
    return CodexRuntimeOperationError(terminal.message)


__all__ = [
    "CodexAgentRuntime",
    "CodexRuntimeBindingError",
    "CodexRuntimeOperationError",
]
