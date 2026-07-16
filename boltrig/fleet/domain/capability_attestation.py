"""Immutable capability-effect attestations that may only narrow authority.

The registry consequence label and effect class are policy evidence, never grants.
Admission starts from a trusted assignment authority snapshot and returns only a
boolean.  An attestation therefore cannot add a verb that the five-layer authority
evaluation did not already permit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from boltrig.fleet.domain.grant_lease import GrantAuthoritySnapshot, GrantLeaseBinding
from boltrig.models import Consequence, MAX_CONCRETE_VERBS, VerbId, canonical_concrete_verbs

_CAPABILITY_SCHEMA = "boltrig.capability-effect-attestation/v1"
_SET_SCHEMA = "boltrig.assignment-capability-attestation-set/v1"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_IDENTIFIER_CHARS = 160


class EffectClass(str, Enum):
    """Closed policy taxonomy for a capability's real-world effect."""

    READ_ONLY_NO_EXTERNAL_EFFECT = "read_only_no_external_effect"
    READ_ONLY_WITH_EGRESS = "read_only_with_egress"
    REVERSIBLE_MUTATION = "reversible_mutation"
    IRREVERSIBLE_MUTATION = "irreversible_mutation"
    AUTHORITY_OR_CREDENTIAL_CHANGE = "authority_or_credential_change"


@dataclass(frozen=True, order=True)
class ConsequenceClassification:
    """Exact registry consequence plus the independently attested effect class."""

    effect_class: EffectClass
    consequence: Consequence

    def __post_init__(self) -> None:
        if type(self.effect_class) is not EffectClass:
            raise TypeError("effect_class must be an exact EffectClass")
        if type(self.consequence) is not Consequence:
            raise TypeError("consequence must be an exact Consequence")

    @property
    def is_initial_safe_read_only(self) -> bool:
        """True only for the first rollout's local, low-consequence read class."""

        return (
            self.effect_class is EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT
            and self.consequence is Consequence.LOW
        )


@dataclass(frozen=True, order=True)
class CapabilityAttestation:
    """Effect evidence for one exact, immutable capability definition."""

    verb_id: VerbId
    definition_digest: str
    classification: ConsequenceClassification

    def __post_init__(self) -> None:
        object.__setattr__(self, "verb_id", _concrete_verb(self.verb_id))
        object.__setattr__(
            self,
            "definition_digest",
            _prefixed_sha256("definition_digest", self.definition_digest),
        )
        if type(self.classification) is not ConsequenceClassification:
            raise TypeError("classification must be an exact ConsequenceClassification")

    @property
    def digest(self) -> str:
        """Digest the complete, versioned classification document canonically."""

        return _document_digest(_capability_document(self))


@dataclass(frozen=True)
class AssignmentCapabilityAttestationSet:
    """One exact assignment's digest-pinned capability classification set."""

    binding: GrantLeaseBinding
    authority_evaluation_id: str
    authority_evaluation_digest: str
    authority_policy_generation: int
    catalog_generation: int
    catalog_digest: str
    attestations: tuple[CapabilityAttestation, ...]

    def __post_init__(self) -> None:
        if type(self.binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        _identifier("authority_evaluation_id", self.authority_evaluation_id)
        object.__setattr__(
            self,
            "authority_evaluation_digest",
            _prefixed_sha256("authority_evaluation_digest", self.authority_evaluation_digest),
        )
        _positive_generation("authority_policy_generation", self.authority_policy_generation)
        _positive_generation("catalog_generation", self.catalog_generation)
        object.__setattr__(
            self,
            "catalog_digest",
            _prefixed_sha256("catalog_digest", self.catalog_digest),
        )
        if type(self.attestations) is not tuple:
            raise TypeError("attestations must be an immutable tuple")
        if len(self.attestations) > MAX_CONCRETE_VERBS:
            raise ValueError("attestations exceed the concrete-verb limit")
        if any(type(item) is not CapabilityAttestation for item in self.attestations):
            raise TypeError("attestations must contain exact CapabilityAttestation values")
        verb_ids = tuple(item.verb_id for item in self.attestations)
        if len(set(verb_ids)) != len(verb_ids):
            raise ValueError("attested capability verbs must be unique")
        object.__setattr__(
            self,
            "attestations",
            tuple(sorted(self.attestations, key=lambda item: item.verb_id)),
        )

    @property
    def verb_ids(self) -> tuple[VerbId, ...]:
        return tuple(item.verb_id for item in self.attestations)

    @property
    def digest(self) -> str:
        """Bind scope, assignment, authority, catalog, and every classification."""

        return _document_digest(
            {
                "assignment": _binding_document(self.binding),
                "attestations": [_capability_document(item) for item in self.attestations],
                "authority": {
                    "digest": self.authority_evaluation_digest,
                    "id": self.authority_evaluation_id,
                    "policy_generation": self.authority_policy_generation,
                },
                "catalog": {
                    "digest": self.catalog_digest,
                    "generation": self.catalog_generation,
                },
                "schema": _SET_SCHEMA,
            }
        )


@dataclass(frozen=True)
class AssignmentCapabilityAttestationPin:
    """Small value persisted with an assignment to name one exact attestation set."""

    binding: GrantLeaseBinding
    authority_evaluation_id: str
    authority_evaluation_digest: str
    authority_policy_generation: int
    catalog_generation: int
    catalog_digest: str
    attestation_set_digest: str

    def __post_init__(self) -> None:
        if type(self.binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        _identifier("authority_evaluation_id", self.authority_evaluation_id)
        object.__setattr__(
            self,
            "authority_evaluation_digest",
            _prefixed_sha256("authority_evaluation_digest", self.authority_evaluation_digest),
        )
        _positive_generation("authority_policy_generation", self.authority_policy_generation)
        _positive_generation("catalog_generation", self.catalog_generation)
        object.__setattr__(
            self,
            "catalog_digest",
            _prefixed_sha256("catalog_digest", self.catalog_digest),
        )
        object.__setattr__(
            self,
            "attestation_set_digest",
            _prefixed_sha256("attestation_set_digest", self.attestation_set_digest),
        )

    @classmethod
    def from_set(
        cls, attestations: AssignmentCapabilityAttestationSet
    ) -> AssignmentCapabilityAttestationPin:
        if type(attestations) is not AssignmentCapabilityAttestationSet:
            raise TypeError("attestations must be an exact AssignmentCapabilityAttestationSet")
        return cls(
            binding=attestations.binding,
            authority_evaluation_id=attestations.authority_evaluation_id,
            authority_evaluation_digest=attestations.authority_evaluation_digest,
            authority_policy_generation=attestations.authority_policy_generation,
            catalog_generation=attestations.catalog_generation,
            catalog_digest=attestations.catalog_digest,
            attestation_set_digest=attestations.digest,
        )

    def matches(self, attestations: object) -> bool:
        """Fail closed unless the resolved set is exactly the pinned set."""

        return type(attestations) is AssignmentCapabilityAttestationSet and (
            self.binding == attestations.binding
            and self.authority_evaluation_id == attestations.authority_evaluation_id
            and hmac.compare_digest(
                self.authority_evaluation_digest,
                attestations.authority_evaluation_digest,
            )
            and self.authority_policy_generation == attestations.authority_policy_generation
            and self.catalog_generation == attestations.catalog_generation
            and hmac.compare_digest(self.catalog_digest, attestations.catalog_digest)
            and hmac.compare_digest(self.attestation_set_digest, attestations.digest)
        )


def attestations_admit_initial_read_only(
    authority: object,
    pin: object,
    attestations: object,
) -> bool:
    """Return only a rejection predicate over already-authorised concrete verbs.

    No grants or verbs are returned.  Exact set equality prevents a broader
    attestation catalog from seeding authority and prevents partial evidence from
    silently classifying an unobserved authorised verb as safe.
    """

    if (
        type(authority) is not GrantAuthoritySnapshot
        or type(pin) is not AssignmentCapabilityAttestationPin
        or type(attestations) is not AssignmentCapabilityAttestationSet
    ):
        return False
    try:
        if not pin.matches(attestations):
            return False
        if not _authority_matches(authority, attestations):
            return False
        if authority.permitted_verbs != attestations.verb_ids:
            return False
        return all(
            item.classification.is_initial_safe_read_only
            for item in attestations.attestations
        )
    except (AttributeError, TypeError, UnicodeError, ValueError):
        # Deserializers must use the validating constructors, but an unsafe
        # hydrator or in-process mutation must still reject at this trust boundary.
        return False


def _authority_matches(
    authority: GrantAuthoritySnapshot,
    attestations: AssignmentCapabilityAttestationSet,
) -> bool:
    return (
        authority.binding == attestations.binding
        and authority.authority_evaluation_id == attestations.authority_evaluation_id
        and hmac.compare_digest(
            authority.authority_evaluation_digest,
            attestations.authority_evaluation_digest,
        )
        and authority.authority_policy_generation == attestations.authority_policy_generation
    )


def _concrete_verb(value: object) -> VerbId:
    if type(value) is not str:
        raise TypeError("verb_id must be an exact string")
    return canonical_concrete_verbs((value,))[0]


def _identifier(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if (
        not value
        or value != value.strip()
        or len(value) > _MAX_IDENTIFIER_CHARS
        or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
        )
    ):
        raise ValueError(f"{label} must be a bounded, trimmed identifier")
    return value


def _positive_generation(label: str, value: object) -> int:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError(f"{label} must be a positive signed BIGINT")
    return value


def _prefixed_sha256(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase sha256 digest")
    return value


def _binding_document(binding: GrantLeaseBinding) -> dict[str, str]:
    return {
        "assignment_id": binding.assignment_id,
        "phase_id": binding.phase_id,
        "root_run_id": binding.root_run_id,
        "tenant_id": binding.tenant_id,
        "workspace_id": binding.workspace_id,
    }


def _capability_document(attestation: CapabilityAttestation) -> dict[str, str]:
    return {
        "consequence": attestation.classification.consequence.value,
        "definition_digest": attestation.definition_digest,
        "effect_class": attestation.classification.effect_class.value,
        "schema": _CAPABILITY_SCHEMA,
        "verb_id": attestation.verb_id,
    }


def _document_digest(document: Mapping[str, object]) -> str:
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "AssignmentCapabilityAttestationPin",
    "AssignmentCapabilityAttestationSet",
    "CapabilityAttestation",
    "ConsequenceClassification",
    "EffectClass",
    "attestations_admit_initial_read_only",
]
