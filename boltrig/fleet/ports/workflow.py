"""Durable phase-job port; native subagents remain inside the runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from boltrig.fleet.domain import PhaseRef


@dataclass(frozen=True)
class DurablePhaseJob:
    """A meaningful Boltrig phase assignment, never a Codex thought/tool call."""

    phase: PhaseRef
    queue: str
    attempt: int


class WorkflowEngine(Protocol):
    """Enqueue and cancel durable phase work without owning runtime internals."""

    async def enqueue_phase(self, job: DurablePhaseJob) -> str: ...

    async def cancel_phase(self, phase: PhaseRef, *, reason: str) -> None: ...
