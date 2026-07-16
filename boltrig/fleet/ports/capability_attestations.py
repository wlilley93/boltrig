"""Port for resolving one immutable, assignment-pinned capability attestation set."""

from __future__ import annotations

from typing import Protocol

from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
)


class CapabilityAttestationResolver(Protocol):
    """Load exact evidence by its assignment-bound pin without issuing authority."""

    async def resolve_capability_attestations(
        self,
        pin: AssignmentCapabilityAttestationPin,
    ) -> AssignmentCapabilityAttestationSet | None:
        """Return the exact immutable set or no evidence; callers still verify it."""
        ...


__all__ = ["CapabilityAttestationResolver"]
