"""Durable normalized runtime-event log port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from boltrig.fleet.domain import PhaseRef, RecordedRuntimeEvent, RuntimeEvent


class RunEventLog(Protocol):
    """Canonical append/read boundary; transports are only projections."""

    async def append(self, event: RuntimeEvent) -> RecordedRuntimeEvent:
        """Append idempotently by event_id and assign the canonical sequence."""
        ...

    async def read(
        self, phase: PhaseRef, *, after_sequence: int = 0
    ) -> tuple[RecordedRuntimeEvent, ...]: ...

    def subscribe(
        self, phase: PhaseRef, *, after_sequence: int = 0
    ) -> AsyncIterator[RecordedRuntimeEvent]: ...
