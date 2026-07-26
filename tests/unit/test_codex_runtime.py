"""Unit tests for the read-only Codex ``Runtime`` adapter (Stage A).

The adapter bridges the one-shot ``Runtime.run`` seam onto the Codex phase
lifecycle. These tests drive it against a fake lifecycle so the mapping,
read-only spec, and degrade-don't-crash behaviour are pinned without a real cell.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from boltrig.fleet.codex_runtime import CodexRuntime
from boltrig.fleet.domain import (
    CanonicalJSON,
    PhaseMode,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
    SandboxPolicy,
)
from boltrig.fleet.ports.runtime import RuntimeThreadSpec
from boltrig.models import InvocationContext


class _FakeLifecycle:
    def __init__(
        self,
        *,
        text: str = "Hello from Codex.",
        fail_start: bool = False,
        runtime_error: bool = False,
    ) -> None:
        self._text = text
        self._fail_start = fail_start
        # A runtime ERROR notification ahead of completion - what codex emits for a bad key,
        # an unknown model id, or a gateway 5xx.
        self._runtime_error = runtime_error
        self.spec: RuntimeThreadSpec | None = None
        self.closed = False
        self.turn_prompt: str | None = None

    async def start_thread(self, spec: RuntimeThreadSpec) -> RuntimeThreadRef:
        self.spec = spec
        if self._fail_start:
            raise RuntimeError("cell provisioning failed")
        return RuntimeThreadRef(spec.assignment, "codex_app_server", "thr-1")

    async def start_turn(self, spec) -> RuntimeTurnRef:  # type: ignore[no-untyped-def]
        self.turn_prompt = spec.prompt
        return RuntimeTurnRef(spec.thread, "turn-1")

    def events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]:
        return self._events(thread)

    async def _events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]:
        if self._runtime_error:
            yield RuntimeEvent(
                event_id="e0",
                assignment=thread.assignment,
                kind=RuntimeEventKind.ERROR,
                thread=thread,
                # No message: runtime events never copy provider content.
                payload=CanonicalJSON.from_mapping({"will_retry": False}),
            )
        yield RuntimeEvent(
            event_id="e1",
            assignment=thread.assignment,
            kind=RuntimeEventKind.TURN_COMPLETED,
            thread=thread,
        )

    async def read_turn_output(self, thread: RuntimeThreadRef) -> str:
        return self._text

    async def close_thread(self, thread: RuntimeThreadRef) -> None:
        self.closed = True


_STACK = Path("/stack")


def _context(**over: object) -> InvocationContext:
    base: dict[str, object] = {
        "tenant_id": "tenant-1",
        "run_id": "run-1",
        "workspace_id": "ws-1",
        "actor": "chief-of-staff",
    }
    base.update(over)
    return InvocationContext(**base)  # type: ignore[arg-type]


async def test_run_returns_agent_message_text_and_closes_thread() -> None:
    fake = _FakeLifecycle(text="the answer")
    result = await CodexRuntime(fake, stack_root=_STACK).run("question?", _context(), tools=[])
    assert result.ok is True
    assert result.degraded is False
    assert result.output == {"runtime": "codex_app_server", "text": "the answer"}
    assert result.summary == "the answer"
    assert fake.turn_prompt == "question?"
    assert fake.closed is True  # the thread is always closed, even on success


async def test_run_builds_a_read_only_phase_spec() -> None:
    fake = _FakeLifecycle()
    await CodexRuntime(fake, stack_root=_STACK).run("hi", _context(), tools=[])
    spec = fake.spec
    assert spec is not None
    assert spec.mode is PhaseMode.READ_ONLY
    assert spec.sandbox is SandboxPolicy.READ_ONLY
    assert spec.skills == ()
    assert spec.assignment.phase.root_run_id == "run-1"
    assert spec.assignment.phase.workspace_id == "ws-1"
    assert spec.assignment.phase.principal.tenant_id == "tenant-1"


async def test_run_degrades_without_run_scope() -> None:
    fake = _FakeLifecycle()
    result = await CodexRuntime(fake, stack_root=_STACK).run("hi", _context(run_id=None), tools=[])
    assert result.degraded is True
    assert result.output["_degraded"]["reason"] == "no_read_only_phase_scope"
    assert fake.spec is None  # never touched the lifecycle


async def test_run_degrades_on_empty_output() -> None:
    """A genuinely silent turn keeps the plain reason - no error was reported."""
    result = await CodexRuntime(_FakeLifecycle(text=""), stack_root=_STACK).run("hi", _context(), tools=[])
    assert result.degraded is True
    assert result.output["_degraded"]["reason"] == "codex_empty_output"


async def test_empty_output_after_a_runtime_error_is_distinguished() -> None:
    """An empty turn that FOLLOWED a runtime error must not read as silence.

    This is the second cause of `codex_empty_output`: the drain loop saw a
    RuntimeEventKind.ERROR and dropped it, so a bad key or an unknown model id was
    reported to the operator as "the model produced nothing usable". The two need
    different responses, so they get different reasons.
    """
    fake = _FakeLifecycle(text="", runtime_error=True)
    result = await CodexRuntime(fake, stack_root=_STACK).run("hi", _context(), tools=[])
    assert result.degraded is True
    assert result.output["_degraded"]["reason"] == "codex_empty_output_after_error"


async def test_a_runtime_error_does_not_degrade_a_turn_that_produced_text() -> None:
    """BOUNDARY. Codex retries; an error followed by real output is a SUCCESS.

    Without this, adding error observation would turn every transient, retried hiccup
    into a degraded turn, which is worse than the silence it set out to fix.
    """
    fake = _FakeLifecycle(text="Hello from Codex.", runtime_error=True)
    result = await CodexRuntime(fake, stack_root=_STACK).run("hi", _context(), tools=[])
    assert result.degraded is False
    assert result.output["text"] == "Hello from Codex."


async def test_run_degrades_and_never_raises_on_lifecycle_error() -> None:
    fake = _FakeLifecycle(fail_start=True)
    result = await CodexRuntime(fake, stack_root=_STACK).run("hi", _context(), tools=[])
    assert result.degraded is True
    # The reason carries a short cause tag ("codex_turn_failed:<ExceptionType>")
    # so a failure is actionable on the wire without leaking the full traceback.
    assert result.output["_degraded"]["reason"].startswith("codex_turn_failed")
