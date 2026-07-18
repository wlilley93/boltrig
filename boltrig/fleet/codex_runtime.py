"""Runtime-protocol adapter over a supervised read-only Codex phase.

This is the seam that makes Codex selectable by the spawner. The live selection
path speaks the one-shot ``Runtime`` protocol (runtime.py: ``run(prompt, ctx, *,
tools) -> AgentResult``), while Codex implements the disjoint ``AgentRuntime``
bounded-phase lifecycle (``start_thread -> start_turn -> events -> close_thread``,
plus a ``read_turn_output`` content read-back, since ``events()`` is a
content-free lifecycle ledger). ``CodexRuntime`` bridges the two: it mints a
read-only phase assignment from the invocation context, runs exactly one turn,
reads the turn's assistant text back, and returns a uniform ``AgentResult``.

Offline/degrade-safe (P9): a missing run scope, any runtime error, or empty
output yields a clearly-marked degraded ``AgentResult`` (never an exception into
the caller), exactly like every other runtime. Read-only by construction: the
thread spec pins ``PhaseMode.READ_ONLY`` / ``SandboxPolicy.READ_ONLY`` (the write
phase is the separate, court-gated PR8 and is not reachable from here).
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Protocol

from boltrig.fleet.domain import (
    PhaseAssignmentRef,
    PhaseRef,
    ProfileRef,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
)
from boltrig.fleet.ports.runtime import RuntimeThreadSpec, RuntimeTurnSpec
from boltrig.models import InvocationContext
from boltrig.models.execution_scope import OrganisationUserRef

from .result import AgentResult

# Read-only cells operate in the projected sanitized workspace; the concrete path
# is owned by the admission provisioning, so the spec carries the canonical mount
# point (an absolute cwd, as ``validate_thread_spec`` requires).
_WORKING_DIRECTORY = "/workspace"
_PROFILE = ProfileRef("codex-read-only", "1")


class CodexPhaseLifecycle(Protocol):
    """The subset of the Codex ``AgentRuntime`` the adapter drives, plus the
    content read-back it needs to build an ``AgentResult`` (``CodexAgentRuntime``
    satisfies this; tests inject a fake)."""

    async def start_thread(self, spec: RuntimeThreadSpec) -> RuntimeThreadRef: ...

    async def start_turn(self, spec: RuntimeTurnSpec) -> RuntimeTurnRef: ...

    def events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]: ...

    async def read_turn_output(self, thread: RuntimeThreadRef) -> str: ...

    async def close_thread(self, thread: RuntimeThreadRef) -> None: ...


class CodexRuntime:
    """One read-only Codex phase per ``run``, mapped to a uniform ``AgentResult``."""

    runtime = "codex"

    def __init__(
        self, lifecycle: CodexPhaseLifecycle, *, cost_tier: str = "standard"
    ) -> None:
        self._lifecycle = lifecycle
        self.cost_tier = cost_tier

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        run_id = context.run_id
        workspace_id = context.workspace_id
        if not run_id or not workspace_id:
            # A Codex phase is scoped to a run + workspace; without them there is
            # nothing to provision. Degrade rather than fabricate a scope.
            return AgentResult.degrade(
                runtime=self.runtime, reason="no_read_only_phase_scope", prompt=prompt
            )
        spec = RuntimeThreadSpec(
            assignment=_mint_assignment(context, run_id, workspace_id),
            profile=_PROFILE,
            skills=(),
            working_directory=_WORKING_DIRECTORY,
        )
        text = ""
        thread: RuntimeThreadRef | None = None
        try:
            thread = await self._lifecycle.start_thread(spec)
            await self._lifecycle.start_turn(
                RuntimeTurnSpec(
                    thread=thread, prompt=prompt, client_message_id=uuid.uuid4().hex
                )
            )
            await _drain_until_complete(self._lifecycle.events(thread))
            text = await self._lifecycle.read_turn_output(thread)
        except Exception:
            return AgentResult.degrade(
                runtime=self.runtime, reason="codex_turn_failed", prompt=prompt
            )
        finally:
            if thread is not None:
                with contextlib.suppress(Exception):
                    await self._lifecycle.close_thread(thread)
        if not text:
            return AgentResult.degrade(
                runtime=self.runtime, reason="codex_empty_output", prompt=prompt
            )
        return AgentResult.succeeded(
            output={"runtime": "codex_app_server", "text": text}, summary=text[:256]
        )


async def _drain_until_complete(events: AsyncIterator[RuntimeEvent]) -> None:
    """Consume the lifecycle stream until the turn completes (the completion
    signal, not the content source). A terminal stream raises and the caller
    degrades."""
    async for event in events:
        if event.kind is RuntimeEventKind.TURN_COMPLETED:
            return


def _mint_assignment(
    context: InvocationContext, run_id: str, workspace_id: str
) -> PhaseAssignmentRef:
    """Mint the read-only phase assignment for this chat turn from the context.

    The read-only reasoning phase is identity-bound to the run, not gated by the
    write-phase assignment admission; a deterministic per-run phase/assignment id
    keeps a re-run mapping onto the same phase.
    """
    principal = OrganisationUserRef(
        tenant_id=context.tenant_id,
        user_id=context.on_behalf_of or context.actor or "agent",
    )
    phase = PhaseRef(
        root_run_id=run_id,
        phase_id=f"{run_id}-codex",
        principal=principal,
        workspace_id=workspace_id,
    )
    return PhaseAssignmentRef(phase=phase, assignment_id=f"{run_id}-codex-assignment")


__all__ = ["CodexPhaseLifecycle", "CodexRuntime"]
