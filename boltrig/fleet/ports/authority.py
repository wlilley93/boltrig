"""Live authority-resolution port for execution and tool admission."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.fleet.domain import EffectiveAuthority, PhaseAssignmentRef


class AuthorityResolver(Protocol):
    """Resolve all current ceilings; queued authority snapshots are never accepted."""

    async def resolve(
        self, assignment: PhaseAssignmentRef, *, at: datetime
    ) -> EffectiveAuthority: ...
