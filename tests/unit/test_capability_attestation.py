from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
    CapabilityAttestation,
    ConsequenceClassification,
    EffectClass,
    attestations_admit_initial_read_only,
)
from boltrig.fleet.ports.capability_attestations import CapabilityAttestationResolver
from boltrig.models import Consequence, MAX_CONCRETE_VERBS
from tests.contracts.grant_lease_fixtures import authority_snapshot, binding

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_C = "sha256:" + "c" * 64


def _attestation(
    verb_id: str,
    *,
    effect: EffectClass = EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT,
    consequence: Consequence = Consequence.LOW,
    definition_digest: str = _A,
) -> CapabilityAttestation:
    return CapabilityAttestation(
        verb_id=verb_id,
        definition_digest=definition_digest,
        classification=ConsequenceClassification(effect, consequence),
    )


def _set(
    *attestations: CapabilityAttestation,
) -> AssignmentCapabilityAttestationSet:
    authority = authority_snapshot(
        permitted_verbs=tuple(sorted(item.verb_id for item in attestations))
    )
    return AssignmentCapabilityAttestationSet(
        binding=authority.binding,
        authority_evaluation_id=authority.authority_evaluation_id,
        authority_evaluation_digest=authority.authority_evaluation_digest,
        authority_policy_generation=authority.authority_policy_generation,
        catalog_generation=7,
        catalog_digest=_B,
        attestations=attestations,
    )


def test_effect_class_is_the_exact_closed_policy_taxonomy() -> None:
    assert tuple(EffectClass) == (
        EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT,
        EffectClass.READ_ONLY_WITH_EGRESS,
        EffectClass.REVERSIBLE_MUTATION,
        EffectClass.IRREVERSIBLE_MUTATION,
        EffectClass.AUTHORITY_OR_CREDENTIAL_CHANGE,
    )
    assert tuple(item.value for item in EffectClass) == (
        "read_only_no_external_effect",
        "read_only_with_egress",
        "reversible_mutation",
        "irreversible_mutation",
        "authority_or_credential_change",
    )
    with pytest.raises(ValueError):
        EffectClass("unknown")


def test_classification_requires_exact_closed_enums_and_is_immutable() -> None:
    classification = ConsequenceClassification(
        EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT,
        Consequence.LOW,
    )
    assert classification.is_initial_safe_read_only
    with pytest.raises(FrozenInstanceError):
        classification.consequence = Consequence.HIGH  # type: ignore[misc]
    with pytest.raises(TypeError, match="exact EffectClass"):
        ConsequenceClassification("read_only_no_external_effect", Consequence.LOW)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact Consequence"):
        ConsequenceClassification(EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT, "low")  # type: ignore[arg-type]

    class _SpoofedClassification(ConsequenceClassification):
        pass

    with pytest.raises(TypeError, match="exact ConsequenceClassification"):
        CapabilityAttestation(
            "ticket.read",
            _A,
            _SpoofedClassification(
                EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT,
                Consequence.LOW,
            ),
        )


@pytest.mark.parametrize("effect", tuple(EffectClass)[1:])
def test_only_local_read_effect_can_be_initial_safe_read_only(effect: EffectClass) -> None:
    assert not ConsequenceClassification(effect, Consequence.LOW).is_initial_safe_read_only


def test_high_consequence_local_read_is_not_initial_safe_read_only() -> None:
    classification = ConsequenceClassification(
        EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT,
        Consequence.HIGH,
    )
    assert not classification.is_initial_safe_read_only


@pytest.mark.parametrize(
    "verb_id",
    ("", " ticket.read", "ticket.*", "ticket.rеad", "ticket.read\u200b", "x" * 257),
)
def test_attestation_requires_one_bounded_safe_concrete_verb(verb_id: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _attestation(verb_id)


def test_attestation_rejects_non_string_verb() -> None:
    with pytest.raises(TypeError, match="exact string"):
        _attestation(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("digest", ("", "a" * 64, "sha256:" + "A" * 64, _A + " "))
def test_attestation_rejects_noncanonical_definition_digest(digest: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _attestation("ticket.read", definition_digest=digest)


def test_attestation_rejects_non_string_definition_digest() -> None:
    with pytest.raises(TypeError, match="exact string"):
        _attestation("ticket.read", definition_digest=object())  # type: ignore[arg-type]


def test_capability_digest_is_canonical_stable_and_complete() -> None:
    capability = _attestation("ticket.read")

    assert (
        capability.digest
        == "sha256:0056b6fb1911eab0f2e86ef519f9484bdcbb8c99a676ed5d845b227fe4245494"
    )
    assert replace(capability, verb_id="document.read").digest != capability.digest
    assert replace(capability, definition_digest=_C).digest != capability.digest
    assert (
        replace(
            capability,
            classification=ConsequenceClassification(
                EffectClass.READ_ONLY_WITH_EGRESS,
                Consequence.LOW,
            ),
        ).digest
        != capability.digest
    )
    assert (
        replace(
            capability,
            classification=ConsequenceClassification(
                EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT,
                Consequence.HIGH,
            ),
        ).digest
        != capability.digest
    )


def test_set_canonicalizes_order_without_deduplicating_evidence() -> None:
    document = _attestation("document.read")
    ticket = _attestation("ticket.read", definition_digest=_C)
    first = _set(ticket, document)
    second = _set(document, ticket)

    assert first.attestations == (document, ticket)
    assert first.verb_ids == ("document.read", "ticket.read")
    assert first.digest == second.digest
    with pytest.raises(ValueError, match="unique"):
        _set(ticket, ticket)


def test_set_rejects_mutable_malformed_or_oversized_collections() -> None:
    base = _set(_attestation("ticket.read"))
    with pytest.raises(TypeError, match="immutable tuple"):
        replace(base, attestations=list(base.attestations))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact CapabilityAttestation"):
        replace(base, attestations=(object(),))  # type: ignore[arg-type]

    class _SpoofedCapability(CapabilityAttestation):
        pass

    spoofed = _SpoofedCapability(
        "ticket.read",
        _A,
        ConsequenceClassification(EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT, Consequence.LOW),
    )
    with pytest.raises(TypeError, match="exact CapabilityAttestation"):
        replace(base, attestations=(spoofed,))
    oversized = tuple(_attestation(f"noun{index}.read") for index in range(MAX_CONCRETE_VERBS + 1))
    with pytest.raises(ValueError, match="concrete-verb limit"):
        replace(base, attestations=oversized)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("binding", object()),
        ("authority_evaluation_id", object()),
        ("authority_evaluation_id", ""),
        ("authority_evaluation_id", " bad"),
        ("authority_evaluation_id", "bad\u200b"),
        ("authority_evaluation_id", "x" * 161),
        ("authority_evaluation_digest", "sha256:" + "A" * 64),
        ("authority_evaluation_digest", object()),
        ("authority_policy_generation", 0),
        ("authority_policy_generation", True),
        ("authority_policy_generation", 2**63),
        ("catalog_generation", 0),
        ("catalog_generation", True),
        ("catalog_generation", 2**63),
        ("catalog_digest", "not-a-digest"),
    ),
)
def test_set_rejects_noncanonical_assignment_or_catalog_metadata(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(_set(_attestation("ticket.read")), **{field: value})


def test_set_digest_binds_every_assignment_authority_catalog_and_capability_field() -> None:
    original = _set(_attestation("ticket.read"))
    assert original.digest == "sha256:08313c56fd368e9ce2a287f3be4d833fdcb7a2688c8b4c15976483f8821b81cc"
    mutations = (
        replace(original, binding=binding(tenant="tenant-2")),
        replace(original, binding=binding(workspace="workspace-2")),
        replace(original, binding=binding(root="root-2")),
        replace(original, binding=binding(phase="phase-2")),
        replace(original, binding=binding(assignment="assignment-2")),
        replace(original, authority_evaluation_id="authority-2"),
        replace(original, authority_evaluation_digest=_C),
        replace(original, authority_policy_generation=2),
        replace(original, catalog_generation=8),
        replace(original, catalog_digest=_C),
        replace(original, attestations=(_attestation("document.read"),)),
        replace(original, attestations=(_attestation("ticket.read", definition_digest=_C),)),
        replace(
            original,
            attestations=(
                _attestation("ticket.read", effect=EffectClass.READ_ONLY_WITH_EGRESS),
            ),
        ),
        replace(
            original,
            attestations=(_attestation("ticket.read", consequence=Consequence.HIGH),),
        ),
    )
    assert all(changed.digest != original.digest for changed in mutations)


def test_pin_is_an_exact_immutable_projection_of_one_set() -> None:
    attestations = _set(_attestation("ticket.read"))
    pin = AssignmentCapabilityAttestationPin.from_set(attestations)

    assert pin.binding == attestations.binding
    assert pin.attestation_set_digest == attestations.digest
    assert pin.matches(attestations)
    assert not replace(pin, catalog_generation=8).matches(attestations)
    with pytest.raises(FrozenInstanceError):
        pin.catalog_generation = 8  # type: ignore[misc]
    with pytest.raises(TypeError, match="exact AssignmentCapabilityAttestationSet"):
        AssignmentCapabilityAttestationPin.from_set(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("binding", object()),
        ("authority_evaluation_id", object()),
        ("authority_evaluation_id", "bad\nvalue"),
        ("authority_evaluation_digest", "a" * 64),
        ("authority_policy_generation", False),
        ("catalog_generation", 0),
        ("catalog_digest", "sha256:" + "F" * 64),
        ("attestation_set_digest", "sha256:" + "0" * 63),
    ),
)
def test_pin_rejects_noncanonical_authority_catalog_or_set_metadata(
    field: str,
    value: object,
) -> None:
    pin = AssignmentCapabilityAttestationPin.from_set(_set(_attestation("ticket.read")))
    with pytest.raises((TypeError, ValueError)):
        replace(pin, **{field: value})


class _Resolver:
    def __init__(self, value: AssignmentCapabilityAttestationSet) -> None:
        self.value = value

    async def resolve_capability_attestations(
        self, pin: AssignmentCapabilityAttestationPin
    ) -> AssignmentCapabilityAttestationSet | None:
        return self.value if pin.matches(self.value) else None


async def test_narrow_resolver_port_returns_evidence_without_authority() -> None:
    attestations = _set(_attestation("ticket.read"))
    pin = AssignmentCapabilityAttestationPin.from_set(attestations)
    resolver: CapabilityAttestationResolver = _Resolver(attestations)

    assert await resolver.resolve_capability_attestations(pin) is attestations


@pytest.mark.invariant("SEC-161")
def test_exact_safe_set_admits_only_the_existing_authority_snapshot() -> None:
    attestations = _set(_attestation("ticket.read"), _attestation("document.read"))
    pin = AssignmentCapabilityAttestationPin.from_set(attestations)
    authority = authority_snapshot(permitted_verbs=attestations.verb_ids)

    decision = attestations_admit_initial_read_only(authority, pin, attestations)

    assert decision is True
    assert type(decision) is bool
