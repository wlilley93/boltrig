"""Trusted current-authority resolution for run-scoped grant admission."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.fleet.domain.execution import PhaseAssignmentRef
from boltrig.fleet.domain.grant_lease import GrantAuthoritySnapshot


class GrantAuthoritySnapshotResolver(Protocol):
    """Resolve current ledger authority only while lifecycle and approval permit it."""

    async def resolve_current_grant_authority(
        self,
        assignment: PhaseAssignmentRef,
        *,
        at: datetime,
    ) -> GrantAuthoritySnapshot | None:
        """Return no snapshot when assignment, approval, or runtime state is inactive."""
        ...


__all__ = ["GrantAuthoritySnapshotResolver"]
