"""Durable asyncpg adapter for immutable, assignment-pinned capability attestations."""

from __future__ import annotations

import hmac

import asyncpg

from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
)
from boltrig.fleet.infrastructure.postgres_capability_attestation_support import (
    insert_set,
    load_set,
    lock_binding,
    stored_set_digest,
)
from boltrig.fleet.ports.capability_attestations import (
    CapabilityAttestationConflict,
    CapabilityAttestationInsertResult,
    CapabilityAttestationInsertStatus,
)


class PostgresCapabilityAttestationStore:
    """Durable insert-once capability-attestation store backed by PostgreSQL.

    One assignment binding owns exactly one immutable attestation set, held across
    a set header row and one child row per attested verb. Every write runs inside
    one transaction holding a per-binding transactional advisory lock, so competing
    inserts for one assignment serialize exactly as the in-memory adapter's single
    process lock does: the first lands, the rest observe the retained set digest and
    replay. A different set for the same binding fails closed as a conflict; the
    canonical set digest is the immutable identity, matching the sibling
    root-decision adapter. Bounded-record backpressure is a property of the
    in-memory adapter only; this durable store is unbounded.

    ``resolve`` reconstructs the stored set by the pin's binding and returns it only
    when the pin matches it exactly, so partial or stale evidence fails closed.
    """

    __slots__ = ("_pool",)

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def __repr__(self) -> str:
        return "PostgresCapabilityAttestationStore(bounded=False)"

    async def insert_once(
        self, attestations: AssignmentCapabilityAttestationSet
    ) -> CapabilityAttestationInsertResult:
        if type(attestations) is not AssignmentCapabilityAttestationSet:
            raise TypeError("attestations must be an exact AssignmentCapabilityAttestationSet")
        binding = attestations.binding
        incoming_digest = attestations.digest
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_binding(conn, binding)
                existing = await stored_set_digest(conn, binding)
                if existing is not None:
                    if not hmac.compare_digest(existing, incoming_digest):
                        raise CapabilityAttestationConflict(
                            "capability attestation set conflicts with immutable history"
                        )
                    retained = await load_set(conn, binding)
                    if retained is None or retained.digest != incoming_digest:
                        raise CapabilityAttestationConflict(
                            "capability attestation set conflicts with immutable history"
                        )
                    return CapabilityAttestationInsertResult(
                        CapabilityAttestationInsertStatus.REPLAYED, retained
                    )
                await insert_set(conn, attestations)
                return CapabilityAttestationInsertResult(
                    CapabilityAttestationInsertStatus.INSERTED, attestations
                )

    async def resolve_capability_attestations(
        self, pin: AssignmentCapabilityAttestationPin
    ) -> AssignmentCapabilityAttestationSet | None:
        if type(pin) is not AssignmentCapabilityAttestationPin:
            raise TypeError("pin must be an exact AssignmentCapabilityAttestationPin")
        async with self._pool.acquire() as conn:
            stored = await load_set(conn, pin.binding)
        if stored is None or not pin.matches(stored):
            return None
        return stored


__all__ = ["PostgresCapabilityAttestationStore"]
