"""Bounded owned state and cleanup helpers for the Codex runtime adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from boltrig.fleet.domain import PhaseRef, RuntimeThreadRef

from . import codex_protocol as wire
from .codex_cell_supervisor import InitializedCodexCell
from .codex_runtime_actor import CodexRuntimeActor
from .codex_runtime_validation import CodexRuntimeBindingError, validate_thread_ref

PhaseKey = tuple[str, str, str, str]


@dataclass(repr=False)
class CodexThreadState:
    cell: InitializedCodexCell = field(repr=False)
    ref: RuntimeThreadRef
    cwd: str
    model: str
    admission_evidence_digest: str
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    actor: CodexRuntimeActor | None = field(default=None, repr=False)
    cleanup_task: asyncio.Task[None] | None = field(default=None, repr=False)
    cleanup_failed: bool = False

    def exact_actor(self) -> CodexRuntimeActor:
        if self.actor is None:
            raise CodexRuntimeBindingError("Codex notification actor is unavailable")
        return self.actor


async def cleanup_state(state: CodexThreadState) -> None:
    try:
        await state.cell.aclose()
    except BaseException:
        state.cleanup_failed = True


async def cleanup_cell_ignoring_failure(cell: InitializedCodexCell) -> None:
    task = asyncio.create_task(cell.aclose())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
    except BaseException:
        pass


def phase_key(phase: PhaseRef) -> PhaseKey:
    return (
        phase.principal.tenant_id,
        phase.workspace_id,
        phase.root_run_id,
        phase.phase_id,
    )


def require_ready_cell(cell: InitializedCodexCell) -> None:
    if (
        cell.closed
        or cell.returncode is not None
        or cell.client.state is not wire.ClientState.READY
    ):
        raise CodexRuntimeBindingError("live Codex cell is no longer available")


def validate_runtime_thread(thread: RuntimeThreadRef, runtime: str) -> None:
    validate_thread_ref(thread)
    if thread.runtime != runtime:
        raise CodexRuntimeBindingError("thread belongs to another runtime")


__all__ = [
    "CodexThreadState",
    "PhaseKey",
    "cleanup_cell_ignoring_failure",
    "cleanup_state",
    "phase_key",
    "require_ready_cell",
    "validate_runtime_thread",
]
