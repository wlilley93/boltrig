"""Reusable behavior checks for every CapabilityAttestationStore adapter.

Proves the immutable insert-once / exact-replay / conflict semantics and the
fail-closed resolve-by-pin surface, so the in-memory reference adapter and any
durable adapter share one semantic matrix. The store retains one immutable set
per assignment binding; ``resolve`` returns it only when the caller's pin matches
the stored set exactly.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
    CapabilityAttestation,
    ConsequenceClassification,
    EffectClass,
)
from boltrig.fleet.domain.grant_lease import GrantLeaseBinding
from boltrig.fleet.ports.capability_attestations import (
    CapabilityAttestationConflict,
    CapabilityAttestationInsertStatus,
    CapabilityAttestationStore,
)
from boltrig.models import Consequence
from tests.contracts.grant_lease_fixtures import authority_snapshot, binding, foreign_bindings

_DEF_A = "sha256:" + "a" * 64
_DEF_D = "sha256:" + "d" * 64
_CATALOG = "sha256:" + "b" * 64


def attestation(
    verb_id: str,
    *,
    effect: EffectClass = EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT,
    consequence: Consequence = Consequence.LOW,
    definition_digest: str = _DEF_A,
) -> CapabilityAttestation:
    return CapabilityAttestation(
        verb_id=verb_id,
        definition_digest=definition_digest,
        classification=ConsequenceClassification(effect, consequence),
    )


def attestation_set(
    *,
    scope: GrantLeaseBinding | None = None,
    attestations: tuple[CapabilityAttestation, ...] | None = None,
    authority_evaluation_id: str = "authority-1",
    authority_policy_generation: int = 1,
    catalog_generation: int = 7,
    catalog_digest: str = _CATALOG,
) -> AssignmentCapabilityAttestationSet:
    exact_scope = scope or binding()
    items = attestations or (
        attestation("document.read"),
        attestation("ticket.read"),
    )
    authority = authority_snapshot(
        scope=exact_scope,
        authority_evaluation_id=authority_evaluation_id,
        authority_policy_generation=authority_policy_generation,
        permitted_verbs=tuple(sorted(item.verb_id for item in items)),
    )
    return AssignmentCapabilityAttestationSet(
        binding=authority.binding,
        authority_evaluation_id=authority.authority_evaluation_id,
        authority_evaluation_digest=authority.authority_evaluation_digest,
        authority_policy_generation=authority.authority_policy_generation,
        catalog_generation=catalog_generation,
        catalog_digest=catalog_digest,
        attestations=items,
    )


def pin(attestations: AssignmentCapabilityAttestationSet) -> AssignmentCapabilityAttestationPin:
    return AssignmentCapabilityAttestationPin.from_set(attestations)


def changed_sets(
    original: AssignmentCapabilityAttestationSet,
) -> tuple[AssignmentCapabilityAttestationSet, ...]:
    """Return valid same-binding sets changing every persisted fact family."""

    scope = original.binding
    return (
        replace(original, catalog_generation=original.catalog_generation + 1),
        replace(original, catalog_digest="sha256:" + "f" * 64),
        attestation_set(scope=scope, authority_evaluation_id="authority-2"),
        attestation_set(scope=scope, authority_policy_generation=2),
        attestation_set(
            scope=scope,
            attestations=(attestation("document.read"), attestation("ticket.read", consequence=Consequence.HIGH)),
        ),
        attestation_set(
            scope=scope,
            attestations=(attestation("document.read"), attestation("ticket.read", definition_digest=_DEF_D)),
        ),
        attestation_set(scope=scope, attestations=(attestation("ticket.read"),)),
    )


async def assert_insert_once_replay_conflict_and_resolve(
    store: CapabilityAttestationStore,
) -> None:
    original = attestation_set()
    exact_copy = replace(original)
    assert exact_copy == original and exact_copy is not original
    assert exact_copy.digest == original.digest

    inserted = await store.insert_once(original)
    replayed = await store.insert_once(exact_copy)
    assert inserted.status is CapabilityAttestationInsertStatus.INSERTED
    assert replayed.status is CapabilityAttestationInsertStatus.REPLAYED
    # The inserter always receives its own object; a replay or read returns the
    # canonical value. The in-memory adapter preserves identity, a durable adapter
    # reconstructs an equal value, so the shared contract binds on canonical
    # equality, not identity.
    assert inserted.attestations is original
    assert replayed.attestations == original

    exact_pin = pin(original)
    assert await store.resolve_capability_attestations(exact_pin) == original

    for changed in changed_sets(original):
        assert changed.binding == original.binding
        assert changed.digest != original.digest
        try:
            await store.insert_once(changed)
        except CapabilityAttestationConflict:
            pass
        else:  # pragma: no cover - a broken adapter reaches the assertion
            raise AssertionError("changed immutable attestation history did not conflict")
        assert await store.resolve_capability_attestations(exact_pin) == original

    # A pin whose binding matches but whose set digest names a different set never
    # resolves: partial or stale evidence must fail closed.
    stale_pin = replace(exact_pin, attestation_set_digest=changed_sets(original)[0].digest)
    assert stale_pin.binding == original.binding
    assert await store.resolve_capability_attestations(stale_pin) is None

    # No evidence for a foreign assignment resolves.
    for scope in foreign_bindings():
        assert await store.resolve_capability_attestations(pin(attestation_set(scope=scope))) is None


async def assert_concurrent_exact_replay_is_serializable(
    store: CapabilityAttestationStore,
) -> None:
    original = attestation_set()
    outcomes = await asyncio.gather(*(store.insert_once(original) for _ in range(32)))

    statuses = [outcome.status for outcome in outcomes]
    assert statuses.count(CapabilityAttestationInsertStatus.INSERTED) == 1
    assert statuses.count(CapabilityAttestationInsertStatus.REPLAYED) == 31
    assert all(outcome.attestations == original for outcome in outcomes)
    assert await store.resolve_capability_attestations(pin(original)) == original


__all__ = [
    "assert_concurrent_exact_replay_is_serializable",
    "assert_insert_once_replay_conflict_and_resolve",
    "attestation",
    "attestation_set",
    "changed_sets",
    "pin",
]
