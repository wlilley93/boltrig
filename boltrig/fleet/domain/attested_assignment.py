"""Trusted server facts for exactly one attestable execution assignment.

Nothing here names evidence.  A binding, a pin, an attestation set, and an
attestation-set reference are all constituents of the assignment record these
facts produce, so they are derived from that record rather than carried beside
it.  A caller therefore cannot hand in evidence belonging to another assignment:
it is inexpressible, not merely rejected.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime

from boltrig.fleet.domain.capability_attestation import CapabilityAttestation
from boltrig.models import (
    MAX_CONCRETE_VERBS,
    AuthorityEvaluationRef,
    ExecutionScopeRef,
    OrganisationUserRef,
    ProfileVersionPin,
    SkillVersionPin,
)

# The ledger identifiers this record's command, event, and outbox intent carry are
# derived by prefixing the command id, and every one of them is a bounded 160-char
# identifier.  Bounding the command id below that leaves room for the longest
# prefix, so a valid command id can never derive an invalid ledger identifier.
MAX_COMMAND_ID_CHARS = 128
MAX_SIGNED_BIGINT = 2**63 - 1
_SHA256_CHARS = 71
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


@dataclass(frozen=True, slots=True)
class AttestedAssignmentFacts:
    """Trusted facts; no binding, pin, attestation set, or set reference appears.

    ``attempt`` is absent by construction: these facts describe a first, original
    assignment of a work item, never a replacement of an earlier attempt.
    """

    scope: ExecutionScopeRef
    assignment_id: str
    phase_id: str
    work_item_id: str
    runtime_identity_id: str
    profile: ProfileVersionPin
    skills: tuple[SkillVersionPin, ...]
    authority: AuthorityEvaluationRef
    attestations: tuple[CapabilityAttestation, ...]
    catalog_generation: int
    catalog_digest: str
    requested_by: OrganisationUserRef
    command_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _exact("scope", self.scope, ExecutionScopeRef)
        for label, value in (
            ("assignment_id", self.assignment_id),
            ("phase_id", self.phase_id),
            ("work_item_id", self.work_item_id),
            ("runtime_identity_id", self.runtime_identity_id),
        ):
            _identifier(label, value)
        _identifier("command_id", self.command_id, limit=MAX_COMMAND_ID_CHARS)
        _exact("profile", self.profile, ProfileVersionPin)
        _skills(self.skills)
        _exact("authority", self.authority, AuthorityEvaluationRef)
        _attestations(self.attestations)
        _generation("catalog_generation", self.catalog_generation)
        _digest("catalog_digest", self.catalog_digest)
        _exact("requested_by", self.requested_by, OrganisationUserRef)
        if self.requested_by.tenant_id != self.scope.tenant_id:
            raise ValueError("requesting user and assignment tenants differ")
        _aware("requested_at", self.requested_at)
        # Evidence that classifies a verb the authority evaluation did not permit,
        # or that leaves an authorised verb unclassified, is incoherent at its
        # source.  Rejecting it here is what lets the minted set be checked against
        # the assignment's own authority by exact equality rather than by subset.
        if self.attested_verbs != self.authority.permitted_verbs:
            raise ValueError("attested verbs and authorised verbs must be the same set")

    @property
    def attested_verbs(self) -> tuple[str, ...]:
        """The canonical attested verb set, ordered as an authority snapshot is."""

        return tuple(sorted(item.verb_id for item in self.attestations))


def _exact(label: str, value: object, expected: type[object]) -> None:
    if type(value) is not expected:
        raise TypeError(f"{label} must be an exact {expected.__name__}")


def _identifier(label: str, value: object, *, limit: int = 160) -> None:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if (
        not value
        or value != value.strip()
        or len(value) > limit
        or any(unicodedata.category(character) in _UNSAFE_CATEGORIES for character in value)
    ):
        raise ValueError(f"{label} must be a bounded, control-free, trimmed identifier")


def _digest(label: str, value: object) -> None:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if (
        len(value) != _SHA256_CHARS
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{label} must be a lowercase sha256 digest")


def _generation(label: str, value: object) -> None:
    if type(value) is not int or type(value) is bool:
        raise TypeError(f"{label} must be an exact integer")
    if not 1 <= value <= MAX_SIGNED_BIGINT:
        raise ValueError(f"{label} must be positive and fit a signed BIGINT")


def _aware(label: str, value: object) -> None:
    if type(value) is not datetime:
        raise TypeError(f"{label} must be an exact datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _skills(values: object) -> None:
    if type(values) is not tuple:
        raise TypeError("skills must be an immutable tuple")
    if any(type(item) is not SkillVersionPin for item in values):
        raise TypeError("skills must contain exact SkillVersionPin values")
    names = tuple(item.name for item in values)
    if len(set(names)) != len(names):
        raise ValueError("skill pins must be unique by name")


def _attestations(values: object) -> None:
    if type(values) is not tuple:
        raise TypeError("attestations must be an immutable tuple")
    if not values:
        raise ValueError("an attested assignment must classify at least one verb")
    if any(type(item) is not CapabilityAttestation for item in values):
        raise TypeError("attestations must contain exact CapabilityAttestation values")
    if len(values) > MAX_CONCRETE_VERBS:
        raise ValueError("attestations exceed the concrete-verb limit")
    verbs = tuple(item.verb_id for item in values)
    if len(set(verbs)) != len(verbs):
        raise ValueError("attested capability verbs must be unique")


__all__ = ["MAX_COMMAND_ID_CHARS", "AttestedAssignmentFacts"]
