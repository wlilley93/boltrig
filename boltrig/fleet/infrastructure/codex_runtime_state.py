"""Bounded owned state and cleanup helpers for the Codex runtime adapter."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

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
    # The API-owned per-run cell tree (in-process posture only; None per-cell,
    # where the tree lives in a slot the spawner clears at the next provision).
    cell_root: Path | None = None

    def exact_actor(self) -> CodexRuntimeActor:
        if self.actor is None:
            raise CodexRuntimeBindingError("Codex notification actor is unavailable")
        return self.actor


async def remove_cell_root(cell_root: Path | None) -> None:
    """Best-effort removal of a per-run cell tree AFTER its cell is down.

    The path always comes from a layout that ``validate_cell_layout`` proved
    lives under the stack root. A leftover tree is a disk leak, never a
    correctness failure, so removal errors are swallowed (P9).
    """

    if cell_root is None:
        return
    with contextlib.suppress(OSError):
        await asyncio.to_thread(shutil.rmtree, cell_root, ignore_errors=True)


async def cleanup_state(state: CodexThreadState) -> None:
    try:
        await state.cell.aclose()
    except BaseException:
        state.cleanup_failed = True
    await remove_cell_root(state.cell_root)


async def cleanup_cell_ignoring_failure(
    cell: InitializedCodexCell, *, cell_root: Path | None = None
) -> None:
    task = asyncio.create_task(cell.aclose())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
    except BaseException:
        pass
    await remove_cell_root(cell_root)


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
    "remove_cell_root",
    "require_ready_cell",
    "validate_runtime_thread",
]
