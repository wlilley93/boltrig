"""Ports for immutable, assignment-pinned capability attestation evidence.

Two surfaces intentionally kept apart. ``CapabilityAttestationResolver`` is the
narrow read-only view handed to admission-time code: it loads exact evidence by
its assignment-bound pin and issues no authority. ``CapabilityAttestationStore``
adds the single write verb needed for any evidence to exist -- an immutable
insert-once keyed by the exact assignment binding -- and structurally satisfies
the resolver, so the same durable object serves both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
)


class CapabilityAttestationStoreError(RuntimeError):
    """An attestation set could not be retained without weakening history."""


class CapabilityAttestationConflict(CapabilityAttestationStoreError):
    """An exact assignment already owns a different immutable attestation set."""


class CapabilityAttestationCapacityExceeded(CapabilityAttestationStoreError):
    """The bounded attestation store cannot retain another immutable set."""


class CapabilityAttestationInsertStatus(str, Enum):
    """Only a fresh insert and an exact replay are successful outcomes."""

    INSERTED = "inserted"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class CapabilityAttestationInsertResult:
    """A sanitized write result carrying the exact retained attestation set."""

    status: CapabilityAttestationInsertStatus
    attestations: AssignmentCapabilityAttestationSet = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.status) is not CapabilityAttestationInsertStatus:
            raise TypeError("status must be an exact CapabilityAttestationInsertStatus")
        if type(self.attestations) is not AssignmentCapabilityAttestationSet:
            raise TypeError("attestations must be an exact AssignmentCapabilityAttestationSet")


class CapabilityAttestationResolver(Protocol):
    """Load exact evidence by its assignment-bound pin without issuing authority."""

    async def resolve_capability_attestations(
        self,
        pin: AssignmentCapabilityAttestationPin,
    ) -> AssignmentCapabilityAttestationSet | None:
        """Return the exact immutable set or no evidence; callers still verify it."""
        ...


class CapabilityAttestationStore(CapabilityAttestationResolver, Protocol):
    """Immutable insert-once persistence plus the narrow resolve view."""

    async def insert_once(
        self, attestations: AssignmentCapabilityAttestationSet
    ) -> CapabilityAttestationInsertResult:
        """Insert once, replay an exact set, or conflict atomically per assignment."""
        ...


__all__ = [
    "CapabilityAttestationCapacityExceeded",
    "CapabilityAttestationConflict",
    "CapabilityAttestationInsertResult",
    "CapabilityAttestationInsertStatus",
    "CapabilityAttestationResolver",
    "CapabilityAttestationStore",
    "CapabilityAttestationStoreError",
]
