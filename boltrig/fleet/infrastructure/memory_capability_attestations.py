"""Bounded atomic in-memory storage for immutable capability attestation sets."""

from __future__ import annotations

import asyncio
import hmac
from dataclasses import dataclass, field

from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
)
from boltrig.fleet.domain.grant_lease import GrantLeaseBinding
from boltrig.fleet.ports.capability_attestations import (
    CapabilityAttestationCapacityExceeded,
    CapabilityAttestationConflict,
    CapabilityAttestationInsertResult,
    CapabilityAttestationInsertStatus,
)

DEFAULT_MAX_CAPABILITY_ATTESTATION_SETS = 4_096
HARD_MAX_CAPABILITY_ATTESTATION_SETS = 100_000


@dataclass(frozen=True, slots=True)
class _StoredSet:
    attestations: AssignmentCapabilityAttestationSet = field(repr=False)
    digest: str = field(repr=False)


class MemoryCapabilityAttestationStore:
    """Serializable non-evicting reference adapter with bounded backpressure.

    One assignment binding owns exactly one immutable attestation set. An insert
    that lands returns the caller's own object; an exact re-insert replays it; a
    different set for the same binding fails closed as a conflict. ``resolve``
    reads by the pin's binding and returns the set only when the pin matches it
    exactly, so partial or stale evidence never satisfies a resolution.
    """

    __slots__ = ("_lock", "_max_sets", "_records")

    def __init__(
        self, *, max_sets: int = DEFAULT_MAX_CAPABILITY_ATTESTATION_SETS
    ) -> None:
        self._max_sets = _capacity(max_sets)
        self._records: dict[GrantLeaseBinding, _StoredSet] = {}
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return "MemoryCapabilityAttestationStore(bounded=True)"

    async def insert_once(
        self, attestations: AssignmentCapabilityAttestationSet
    ) -> CapabilityAttestationInsertResult:
        if type(attestations) is not AssignmentCapabilityAttestationSet:
            raise TypeError("attestations must be an exact AssignmentCapabilityAttestationSet")
        incoming_digest = attestations.digest
        async with self._lock:
            existing = self._records.get(attestations.binding)
            if existing is not None:
                if existing.attestations == attestations and hmac.compare_digest(
                    existing.digest, incoming_digest
                ):
                    return CapabilityAttestationInsertResult(
                        CapabilityAttestationInsertStatus.REPLAYED,
                        existing.attestations,
                    )
                raise CapabilityAttestationConflict(
                    "capability attestation set conflicts with immutable history"
                )
            if len(self._records) >= self._max_sets:
                raise CapabilityAttestationCapacityExceeded(
                    "capability attestation store capacity exceeded"
                )
            self._records[attestations.binding] = _StoredSet(attestations, incoming_digest)
            return CapabilityAttestationInsertResult(
                CapabilityAttestationInsertStatus.INSERTED,
                attestations,
            )

    async def resolve_capability_attestations(
        self, pin: AssignmentCapabilityAttestationPin
    ) -> AssignmentCapabilityAttestationSet | None:
        if type(pin) is not AssignmentCapabilityAttestationPin:
            raise TypeError("pin must be an exact AssignmentCapabilityAttestationPin")
        async with self._lock:
            stored = self._records.get(pin.binding)
        if stored is None or not pin.matches(stored.attestations):
            return None
        return stored.attestations


def _capacity(value: object) -> int:
    if type(value) is not int or not 1 <= value <= HARD_MAX_CAPABILITY_ATTESTATION_SETS:
        raise ValueError(
            f"max_sets must be between 1 and {HARD_MAX_CAPABILITY_ATTESTATION_SETS}"
        )
    return value


__all__ = [
    "DEFAULT_MAX_CAPABILITY_ATTESTATION_SETS",
    "HARD_MAX_CAPABILITY_ATTESTATION_SETS",
    "MemoryCapabilityAttestationStore",
]
