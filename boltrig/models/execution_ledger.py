"""Immutable command and work records for the canonical execution ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import cast

from .base import WorkItemId, utcnow
from .execution_scope import (
    MAX_COLLECTION_ITEMS,
    EngineOwner,
    ExecutionScopeRef,
    OrganisationUserRef,
    _require_aware,
    _require_bounded_text,
    _require_exact_enum,
    _require_exact_type,
    _require_identifier,
    _require_positive,
    _require_sha256,
)
from .execution_transitions import (
    AssignmentStatus,
    ExecutionPhaseStatus,
    LedgerWorkItemStatus,
    PhaseMode,
    RootRunStatus,
)
from .execution_work_values import (
    AssignmentLease,
    AttestationSetRef,
    AuthorityEvaluationRef,
    CancellationMetadata,
    PhaseTerminalOutcome,
    ProfileVersionPin,
    RetryPolicy,
    SkillVersionPin,
)

PhaseId = str
AssignmentId = str
ResultId = str
VerificationId = str


class ExecutionAggregateKind(str, Enum):
    ROOT_RUN = "root_run"
    PHASE = "phase"
    WORK_ITEM = "work_item"
    ASSIGNMENT = "assignment"
    RESULT = "result"
    VERIFICATION = "verification"


class LedgerMutationStatus(str, Enum):
    APPLIED = "applied"
    REPLAYED = "replayed"
    CONFLICT = "conflict"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


class LedgerClaimStatus(str, Enum):
    ACQUIRED = "acquired"
    REPLAYED = "replayed"
    HELD_BY_OTHER = "held_by_other"
    NOT_CLAIMABLE = "not_claimable"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class ExecutionRootRun:
    scope: ExecutionScopeRef
    requested_by: OrganisationUserRef
    objective_digest: str
    profile: ProfileVersionPin
    policy_generation: int
    status: RootRunStatus = RootRunStatus.PENDING
    cancellation: CancellationMetadata | None = None
    final_synthesis_digest: str | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_exact_type("requested_by", self.requested_by, OrganisationUserRef)
        if self.requested_by.tenant_id != self.scope.tenant_id:
            raise ValueError("requesting user and root-run tenants differ")
        _require_sha256("objective_digest", self.objective_digest)
        _require_exact_type("profile", self.profile, ProfileVersionPin)
        _require_positive("policy_generation", self.policy_generation)
        _require_exact_enum("status", self.status, RootRunStatus)
        if self.cancellation is not None:
            _require_exact_type("cancellation", self.cancellation, CancellationMetadata)
            if self.cancellation.requested_by.tenant_id != self.scope.tenant_id:
                raise ValueError("cancellation actor and root-run tenants differ")
        if self.status in {RootRunStatus.CANCELLING, RootRunStatus.CANCELLED}:
            if self.cancellation is None:
                raise ValueError("cancelling or cancelled root run requires cancellation metadata")
        if self.final_synthesis_digest is not None:
            _require_sha256("final_synthesis_digest", self.final_synthesis_digest)
        if self.status is RootRunStatus.SUCCEEDED and self.final_synthesis_digest is None:
            raise ValueError("succeeded root run requires final synthesis digest")
        _require_positive("version", self.version)
        _require_aware("created_at", self.created_at)


@dataclass(frozen=True)
class ExecutionPhase:
    scope: ExecutionScopeRef
    id: PhaseId
    ordinal: int
    name: str
    objective_digest: str
    mode: PhaseMode
    profile: ProfileVersionPin
    skills: tuple[SkillVersionPin, ...]
    policy_generation: int
    dependencies: tuple[PhaseId, ...]
    retry: RetryPolicy
    status: ExecutionPhaseStatus = ExecutionPhaseStatus.PENDING
    terminal_outcome: PhaseTerminalOutcome | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_identifier("phase id", self.id)
        _require_positive("ordinal", self.ordinal)
        _require_bounded_text("phase name", self.name)
        _require_sha256("objective_digest", self.objective_digest)
        _require_exact_enum("mode", self.mode, PhaseMode)
        _require_exact_type("profile", self.profile, ProfileVersionPin)
        _require_skill_pins(self.skills)
        _require_positive("policy_generation", self.policy_generation)
        _require_identifier_tuple("phase dependencies", self.dependencies, own_id=self.id)
        _require_exact_type("retry", self.retry, RetryPolicy)
        _require_exact_enum("status", self.status, ExecutionPhaseStatus)
        terminal = self.status in {
            ExecutionPhaseStatus.SUCCEEDED,
            ExecutionPhaseStatus.FAILED,
            ExecutionPhaseStatus.INTERRUPTED,
        }
        if self.terminal_outcome is not None:
            _require_exact_type("terminal_outcome", self.terminal_outcome, PhaseTerminalOutcome)
        if terminal != (self.terminal_outcome is not None):
            raise ValueError("phase terminal status and terminal outcome must agree")
        _require_positive("version", self.version)
        _require_aware("created_at", self.created_at)


@dataclass(frozen=True)
class ExecutionWorkItem:
    scope: ExecutionScopeRef
    id: WorkItemId
    phase_id: PhaseId
    ordinal: int
    intent_digest: str
    dependencies: tuple[WorkItemId, ...] = ()
    parent_id: WorkItemId | None = None
    requires_verification: bool = True
    status: LedgerWorkItemStatus = LedgerWorkItemStatus.PENDING
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_identifier("work item id", self.id)
        _require_identifier("phase_id", self.phase_id)
        _require_positive("ordinal", self.ordinal)
        _require_sha256("intent_digest", self.intent_digest)
        _require_identifier_tuple("work dependencies", self.dependencies, own_id=self.id)
        if self.parent_id is not None:
            _require_identifier("parent_id", self.parent_id)
            if self.parent_id == self.id:
                raise ValueError("work item cannot be its own parent")
        if type(self.requires_verification) is not bool:
            raise TypeError("requires_verification must be an exact bool")
        _require_exact_enum("status", self.status, LedgerWorkItemStatus)
        _require_positive("version", self.version)
        _require_aware("created_at", self.created_at)


@dataclass(frozen=True)
class ExecutionAssignment:
    scope: ExecutionScopeRef
    id: AssignmentId
    phase_id: PhaseId
    work_item_id: WorkItemId
    runtime_identity_id: str
    attempt: int
    profile: ProfileVersionPin
    skills: tuple[SkillVersionPin, ...]
    authority: AuthorityEvaluationRef
    lease: AssignmentLease | None = None
    attestation_set: AttestationSetRef | None = None
    replaces_assignment_id: AssignmentId | None = None
    status: AssignmentStatus = AssignmentStatus.OFFERED
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        for label, value in (("assignment id", self.id), ("phase_id", self.phase_id), ("work_item_id", self.work_item_id), ("runtime_identity_id", self.runtime_identity_id)):
            _require_identifier(label, value)
        _require_positive("attempt", self.attempt)
        _require_exact_type("profile", self.profile, ProfileVersionPin)
        _require_skill_pins(self.skills)
        _require_exact_type("authority", self.authority, AuthorityEvaluationRef)
        if self.lease is not None:
            _require_exact_type("lease", self.lease, AssignmentLease)
        if self.attestation_set is not None:
            _require_exact_type("attestation_set", self.attestation_set, AttestationSetRef)
        if self.replaces_assignment_id is not None:
            _require_identifier("replaces_assignment_id", self.replaces_assignment_id)
            if self.replaces_assignment_id == self.id:
                raise ValueError("assignment cannot replace itself")
        _require_exact_enum("status", self.status, AssignmentStatus)
        if self.status is AssignmentStatus.OFFERED and self.lease is not None:
            raise ValueError("offered assignment cannot already hold a lease")
        if self.status in {AssignmentStatus.CLAIMED, AssignmentStatus.RUNNING} and self.lease is None:
            raise ValueError("claimed or running assignment requires a lease")
        _require_positive("version", self.version)
        _require_aware("created_at", self.created_at)


def _require_identifier_tuple(label: str, values: object, *, own_id: str) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{label} must be an immutable tuple")
    entries = cast(tuple[object, ...], values)
    if len(entries) > MAX_COLLECTION_ITEMS:
        raise ValueError(f"{label} exceeds the collection limit")
    normalized = tuple(_require_identifier(label, value) for value in entries)
    if own_id in normalized or len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must be unique and cannot contain the record itself")


def _require_skill_pins(values: object) -> None:
    if type(values) is not tuple:
        raise TypeError("selected skills must be an immutable tuple")
    skills = cast(tuple[object, ...], values)
    if len(skills) > MAX_COLLECTION_ITEMS:
        raise ValueError("selected skills exceed the collection limit")
    if any(type(skill) is not SkillVersionPin for skill in skills):
        raise TypeError("selected skills must contain exact SkillVersionPin values")
    names = tuple(cast(SkillVersionPin, skill).name for skill in skills)
    if len(set(names)) != len(names):
        raise ValueError("selected skill pins must be unique by name")


@dataclass(frozen=True)
class LedgerMutationOutcome:
    scope: ExecutionScopeRef
    command_id: str
    request_digest: str
    status: LedgerMutationStatus
    aggregate_kind: ExecutionAggregateKind
    aggregate_id: str
    previous_version: int | None = None
    resulting_version: int | None = None

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_identifier("command_id", self.command_id)
        _require_sha256("request_digest", self.request_digest)
        _require_exact_enum("status", self.status, LedgerMutationStatus)
        _require_exact_enum("aggregate_kind", self.aggregate_kind, ExecutionAggregateKind)
        _require_identifier("aggregate_id", self.aggregate_id)
        for label, value in (("previous_version", self.previous_version), ("resulting_version", self.resulting_version)):
            if value is not None:
                _require_positive(label, value, allow_zero=True)
        if self.status is LedgerMutationStatus.APPLIED:
            if self.resulting_version is None:
                raise ValueError("applied mutation must report resulting_version")
            if self.previous_version is not None and self.resulting_version <= self.previous_version:
                raise ValueError("applied mutation must advance aggregate version")


@dataclass(frozen=True)
class LedgerClaimOutcome:
    scope: ExecutionScopeRef
    command_id: str
    request_digest: str
    status: LedgerClaimStatus
    work_item_id: WorkItemId
    assignment_id: AssignmentId | None = None
    lease: AssignmentLease | None = None

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_identifier("command_id", self.command_id)
        _require_sha256("request_digest", self.request_digest)
        _require_exact_enum("status", self.status, LedgerClaimStatus)
        _require_identifier("work_item_id", self.work_item_id)
        if self.assignment_id is not None:
            _require_identifier("assignment_id", self.assignment_id)
        if self.lease is not None:
            _require_exact_type("lease", self.lease, AssignmentLease)
        successful = self.status in {LedgerClaimStatus.ACQUIRED, LedgerClaimStatus.REPLAYED}
        if successful and (self.assignment_id is None or self.lease is None):
            raise ValueError("successful claim must identify its assignment and lease")
        if not successful and self.lease is not None:
            raise ValueError("unsuccessful claim cannot issue a lease")
