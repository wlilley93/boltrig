from __future__ import annotations

from dataclasses import replace

import pytest

from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
    CapabilityAttestation,
    ConsequenceClassification,
    EffectClass,
    attestations_admit_initial_read_only,
)
from boltrig.fleet.domain.grant_lease import GrantAuthoritySnapshot, GrantLeaseBinding
from boltrig.models import Consequence
from tests.contracts.grant_lease_fixtures import authority_snapshot, foreign_bindings

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_C = "sha256:" + "c" * 64


def _capability(
    verb_id: str,
    *,
    effect: EffectClass = EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT,
    consequence: Consequence = Consequence.LOW,
    digest: str = _A,
) -> CapabilityAttestation:
    return CapabilityAttestation(
        verb_id,
        digest,
        ConsequenceClassification(effect, consequence),
    )


def _set(
    *capabilities: CapabilityAttestation,
) -> AssignmentCapabilityAttestationSet:
    authority = authority_snapshot(
        permitted_verbs=tuple(sorted(item.verb_id for item in capabilities))
    )
    return AssignmentCapabilityAttestationSet(
        binding=authority.binding,
        authority_evaluation_id=authority.authority_evaluation_id,
        authority_evaluation_digest=authority.authority_evaluation_digest,
        authority_policy_generation=authority.authority_policy_generation,
        catalog_generation=1,
        catalog_digest=_B,
        attestations=capabilities,
    )


def _admitted(
    attestations: AssignmentCapabilityAttestationSet,
    *,
    authority_verbs: tuple[str, ...] | None = None,
    pin: AssignmentCapabilityAttestationPin | None = None,
) -> bool:
    authority = authority_snapshot(
        permitted_verbs=(authority_verbs if authority_verbs is not None else attestations.verb_ids)
    )
    return attestations_admit_initial_read_only(
        authority,
        pin or AssignmentCapabilityAttestationPin.from_set(attestations),
        attestations,
    )


@pytest.mark.parametrize("effect", tuple(EffectClass)[1:])
def test_egress_and_every_mutating_effect_fail_closed_even_when_low(
    effect: EffectClass,
) -> None:
    attestations = _set(_capability("ticket.read", effect=effect))
    assert not _admitted(attestations)


def test_high_consequence_fails_closed_even_without_external_effect() -> None:
    attestations = _set(_capability("ticket.read", consequence=Consequence.HIGH))
    assert not _admitted(attestations)


def test_lexical_read_suffix_cannot_override_attested_destructive_effect() -> None:
    attestations = _set(_capability("ticket.read", effect=EffectClass.IRREVERSIBLE_MUTATION))
    assert not _admitted(attestations)


@pytest.mark.invariant("SEC-161")
def test_attestations_can_only_reject_and_never_seed_authority() -> None:
    ticket = _capability("ticket.read")
    admin = _capability("admin.read", digest=_C)

    assert not _admitted(_set(ticket, admin), authority_verbs=("ticket.read",))
    assert not _admitted(_set(ticket), authority_verbs=("admin.read", "ticket.read"))
    assert not _admitted(_set(ticket), authority_verbs=())
    assert _admitted(_set(), authority_verbs=())


def test_repinning_a_partial_or_broader_safe_set_still_cannot_change_authority() -> None:
    original = _set(_capability("ticket.read"), _capability("document.read", digest=_C))
    partial = replace(original, attestations=(_capability("ticket.read"),))
    broader = replace(
        original,
        attestations=(*original.attestations, _capability("admin.read", digest=_B)),
    )

    assert not _admitted(
        partial,
        authority_verbs=original.verb_ids,
        pin=AssignmentCapabilityAttestationPin.from_set(partial),
    )
    assert not _admitted(
        broader,
        authority_verbs=original.verb_ids,
        pin=AssignmentCapabilityAttestationPin.from_set(broader),
    )


@pytest.mark.parametrize("foreign_binding", foreign_bindings())
def test_every_assignment_scope_dimension_is_bound(foreign_binding: GrantLeaseBinding) -> None:
    original = _set(_capability("ticket.read"))
    changed = replace(original, binding=foreign_binding)

    assert not _admitted(
        changed,
        pin=AssignmentCapabilityAttestationPin.from_set(changed),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        {"authority_evaluation_id": "authority-2"},
        {"authority_evaluation_digest": _C},
        {"authority_policy_generation": 2},
    ),
)
def test_authority_evaluation_identity_is_bound(mutation: dict[str, object]) -> None:
    original = _set(_capability("ticket.read"))
    changed = replace(original, **mutation)

    assert not _admitted(
        changed,
        pin=AssignmentCapabilityAttestationPin.from_set(changed),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        {"catalog_generation": 2},
        {"catalog_digest": _C},
        {"attestation_set_digest": _C},
    ),
)
def test_every_pin_dimension_is_checked_before_admission(mutation: dict[str, object]) -> None:
    attestations = _set(_capability("ticket.read"))
    pin = replace(AssignmentCapabilityAttestationPin.from_set(attestations), **mutation)
    assert not _admitted(attestations, pin=pin)


@pytest.mark.parametrize("foreign_binding", foreign_bindings())
def test_old_pin_rejects_every_assignment_scope_drift(
    foreign_binding: GrantLeaseBinding,
) -> None:
    original = _set(_capability("ticket.read"))
    pin = AssignmentCapabilityAttestationPin.from_set(original)

    assert not pin.matches(replace(original, binding=foreign_binding))


@pytest.mark.parametrize(
    "mutation",
    (
        {"authority_evaluation_id": "authority-2"},
        {"authority_evaluation_digest": _C},
        {"authority_policy_generation": 2},
        {"catalog_generation": 2},
        {"catalog_digest": _C},
    ),
)
def test_old_pin_rejects_every_authority_and_catalog_dimension(
    mutation: dict[str, object],
) -> None:
    original = _set(_capability("ticket.read"))
    pin = AssignmentCapabilityAttestationPin.from_set(original)

    assert not pin.matches(replace(original, **mutation))


def test_old_pin_rejects_definition_or_classification_drift() -> None:
    original = _set(_capability("ticket.read"))
    pin = AssignmentCapabilityAttestationPin.from_set(original)
    definition_drift = replace(
        original,
        attestations=(_capability("ticket.read", digest=_C),),
    )
    classification_drift = replace(
        original,
        attestations=(_capability("ticket.read", effect=EffectClass.READ_ONLY_WITH_EGRESS),),
    )

    assert not _admitted(definition_drift, pin=pin)
    assert not _admitted(classification_drift, pin=pin)


@pytest.mark.parametrize("invalid", (None, object(), "ticket.read", True, ()))
def test_malformed_boundary_values_return_false_without_raising(invalid: object) -> None:
    attestations = _set(_capability("ticket.read"))
    authority = authority_snapshot(permitted_verbs=attestations.verb_ids)
    pin = AssignmentCapabilityAttestationPin.from_set(attestations)

    assert not attestations_admit_initial_read_only(invalid, pin, attestations)
    assert not attestations_admit_initial_read_only(authority, invalid, attestations)
    assert not attestations_admit_initial_read_only(authority, pin, invalid)


@pytest.mark.parametrize("target", ("authority", "pin", "attestations"))
def test_corrupted_exact_instances_fail_closed_without_raising(target: str) -> None:
    attestations = _set(_capability("ticket.read"))
    authority = authority_snapshot(permitted_verbs=attestations.verb_ids)
    pin = AssignmentCapabilityAttestationPin.from_set(attestations)

    if target == "authority":
        object.__setattr__(authority, "authority_evaluation_digest", None)
    elif target == "pin":
        object.__setattr__(pin, "authority_evaluation_digest", None)
    else:
        object.__setattr__(attestations, "attestations", (object(),))

    assert not attestations_admit_initial_read_only(authority, pin, attestations)


class _SpoofedSet(AssignmentCapabilityAttestationSet):
    pass


class _SpoofedPin(AssignmentCapabilityAttestationPin):
    pass


class _SpoofedAuthority(GrantAuthoritySnapshot):
    pass


def test_subclass_spoof_cannot_cross_exact_type_boundary() -> None:
    original = _set(_capability("ticket.read"))
    spoofed = _SpoofedSet(
        binding=original.binding,
        authority_evaluation_id=original.authority_evaluation_id,
        authority_evaluation_digest=original.authority_evaluation_digest,
        authority_policy_generation=original.authority_policy_generation,
        catalog_generation=original.catalog_generation,
        catalog_digest=original.catalog_digest,
        attestations=original.attestations,
    )
    authority = authority_snapshot(permitted_verbs=original.verb_ids)
    pin = AssignmentCapabilityAttestationPin.from_set(original)

    assert not pin.matches(spoofed)
    assert not attestations_admit_initial_read_only(authority, pin, spoofed)

    spoofed_pin = _SpoofedPin(
        binding=pin.binding,
        authority_evaluation_id=pin.authority_evaluation_id,
        authority_evaluation_digest=pin.authority_evaluation_digest,
        authority_policy_generation=pin.authority_policy_generation,
        catalog_generation=pin.catalog_generation,
        catalog_digest=pin.catalog_digest,
        attestation_set_digest=pin.attestation_set_digest,
    )
    spoofed_authority = object.__new__(_SpoofedAuthority)
    object.__setattr__(spoofed_authority, "binding", authority.binding)
    object.__setattr__(
        spoofed_authority,
        "authority_evaluation_id",
        authority.authority_evaluation_id,
    )
    object.__setattr__(
        spoofed_authority,
        "authority_evaluation_digest",
        authority.authority_evaluation_digest,
    )
    object.__setattr__(
        spoofed_authority,
        "authority_policy_generation",
        authority.authority_policy_generation,
    )
    object.__setattr__(spoofed_authority, "permitted_verbs", authority.permitted_verbs)

    assert not attestations_admit_initial_read_only(authority, spoofed_pin, original)
    assert not attestations_admit_initial_read_only(spoofed_authority, pin, original)
