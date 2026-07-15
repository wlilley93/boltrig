"""Credential-free durable state for one run-scoped MCP grant lease."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum

from boltrig.models import RunId, TenantId, VerbId, WorkspaceId
from boltrig.models.execution_ledger import ExecutionAssignment

from .execution import PhaseAssignmentRef, PhaseId
from .grant_lease_values import (
    MAX_GRANT_TTL_SECONDS,
    MAX_PERMITTED_VERBS,
    MAX_REVOCATION_REASON_LENGTH,
    MAX_SIGNED_BIGINT,
    aware as _aware,
    concrete_verbs as _concrete_verbs,
    identifier as _identifier,
    positive_bigint as _positive_bigint,
    prefixed_sha256_digest as _prefixed_sha256_digest,
    raw_sha256_digest as _raw_sha256_digest,
    validate_revocation_reason,
)


class GrantLeaseStatus(str, Enum):
    """Durable lifecycle of a bearer digest, never of the bearer itself."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class GrantLeaseConflict(RuntimeError):
    """An atomic lease insert conflicted with durable generation state."""


class ActiveGrantGenerationConflict(GrantLeaseConflict):
    """The exact assignment already has an active lease for this generation."""


class StaleGrantGeneration(GrantLeaseConflict):
    """An issue attempt used a generation older than durable history."""


class LeaseGenerationExhausted(GrantLeaseConflict):
    """The store-owned signed-BIGINT lease fence cannot advance safely."""


@dataclass(frozen=True, order=True)
class GrantLeaseBinding:
    """The exact Boltrig scope a token may authenticate; no user input is authority."""

    tenant_id: TenantId
    workspace_id: WorkspaceId
    root_run_id: RunId
    phase_id: PhaseId
    assignment_id: str

    def __post_init__(self) -> None:
        _identifier("tenant_id", self.tenant_id)
        _identifier("workspace_id", self.workspace_id)
        _identifier("root_run_id", self.root_run_id)
        _identifier("phase_id", self.phase_id)
        _identifier("assignment_id", self.assignment_id)

    @classmethod
    def from_assignment(cls, assignment: PhaseAssignmentRef) -> GrantLeaseBinding:
        if type(assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        phase = assignment.phase
        return cls(
            tenant_id=phase.principal.tenant_id,
            workspace_id=phase.workspace_id,
            root_run_id=phase.root_run_id,
            phase_id=phase.phase_id,
            assignment_id=assignment.assignment_id,
        )

    @classmethod
    def from_execution_assignment(cls, assignment: ExecutionAssignment) -> GrantLeaseBinding:
        if type(assignment) is not ExecutionAssignment:
            raise TypeError("assignment must be an exact ExecutionAssignment")
        return cls(
            tenant_id=assignment.scope.tenant_id,
            workspace_id=assignment.scope.workspace_id,
            root_run_id=assignment.scope.root_run_id,
            phase_id=assignment.phase_id,
            assignment_id=assignment.id,
        )


@dataclass(frozen=True, init=False)
class GrantAuthoritySnapshot:
    """Trusted current authority material resolved from Boltrig's durable ledger."""

    binding: GrantLeaseBinding
    authority_evaluation_id: str
    authority_evaluation_digest: str
    authority_policy_generation: int
    permitted_verbs: tuple[VerbId, ...]

    @classmethod
    def from_execution_assignment(cls, assignment: ExecutionAssignment) -> GrantAuthoritySnapshot:
        """Project authority only from the canonical immutable assignment record."""

        if type(assignment) is not ExecutionAssignment:
            raise TypeError("assignment must be an exact ExecutionAssignment")
        authority = assignment.authority
        snapshot = object.__new__(cls)
        object.__setattr__(
            snapshot,
            "binding",
            GrantLeaseBinding.from_execution_assignment(assignment),
        )
        object.__setattr__(snapshot, "authority_evaluation_id", authority.id)
        object.__setattr__(snapshot, "authority_evaluation_digest", authority.digest)
        object.__setattr__(
            snapshot,
            "authority_policy_generation",
            authority.policy_generation,
        )
        object.__setattr__(snapshot, "permitted_verbs", authority.permitted_verbs)
        snapshot.__post_init__()
        return snapshot

    def __post_init__(self) -> None:
        if type(self.binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        _identifier("authority_evaluation_id", self.authority_evaluation_id)
        object.__setattr__(
            self,
            "authority_evaluation_digest",
            _prefixed_sha256_digest(
                "authority evaluation digest", self.authority_evaluation_digest
            ),
        )
        _positive_bigint("authority_policy_generation", self.authority_policy_generation)
        object.__setattr__(self, "permitted_verbs", _concrete_verbs(self.permitted_verbs))


@dataclass(frozen=True)
class GrantRequestObservation:
    """Server-parsed exact assignment and concrete verb for one MCP request."""

    assignment: PhaseAssignmentRef
    verb_id: VerbId

    def __post_init__(self) -> None:
        if type(self.assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        verbs = _concrete_verbs((self.verb_id,))
        if len(verbs) != 1:
            raise ValueError("request observation requires one concrete verb")
        object.__setattr__(self, "verb_id", verbs[0])

    @property
    def binding(self) -> GrantLeaseBinding:
        return GrantLeaseBinding.from_assignment(self.assignment)


@dataclass(frozen=True, order=True)
class GrantRootBinding:
    """Exact root scope for a bounded revoke-all operation."""

    tenant_id: TenantId
    workspace_id: WorkspaceId
    root_run_id: RunId

    def __post_init__(self) -> None:
        _identifier("tenant_id", self.tenant_id)
        _identifier("workspace_id", self.workspace_id)
        _identifier("root_run_id", self.root_run_id)

    @classmethod
    def from_assignment(cls, assignment: PhaseAssignmentRef) -> GrantRootBinding:
        binding = GrantLeaseBinding.from_assignment(assignment)
        return cls(binding.tenant_id, binding.workspace_id, binding.root_run_id)


@dataclass(frozen=True)
class GrantLeaseCandidate:
    """Validated issuance material before storage allocates its lease generation."""

    lease_id: str
    issue_operation_id: str
    binding: GrantLeaseBinding
    token_digest: str
    authority_snapshot: GrantAuthoritySnapshot
    issued_at: datetime
    expires_at: datetime
    max_ttl_seconds: int
    expected_current_lease_generation: int | None

    def __post_init__(self) -> None:
        _identifier("lease_id", self.lease_id)
        _identifier("issue_operation_id", self.issue_operation_id)
        if type(self.binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        object.__setattr__(
            self, "token_digest", _raw_sha256_digest("token digest", self.token_digest)
        )
        if type(self.authority_snapshot) is not GrantAuthoritySnapshot:
            raise TypeError("authority_snapshot must be an exact GrantAuthoritySnapshot")
        if self.authority_snapshot.binding != self.binding:
            raise ValueError("authority snapshot belongs to another grant binding")
        issued_at = _aware("issued_at", self.issued_at)
        expires_at = _aware("expires_at", self.expires_at)
        if (
            type(self.max_ttl_seconds) is not int
            or not 1 <= self.max_ttl_seconds <= MAX_GRANT_TTL_SECONDS
        ):
            raise ValueError(f"max_ttl_seconds must be between 1 and {MAX_GRANT_TTL_SECONDS}")
        if self.expected_current_lease_generation is not None:
            _positive_bigint(
                "expected_current_lease_generation",
                self.expected_current_lease_generation,
            )
        ttl = expires_at - issued_at
        if ttl <= timedelta(0) or ttl > timedelta(seconds=self.max_ttl_seconds):
            raise ValueError("lease lifetime must be positive and within its maximum TTL")

    def matches_authority_snapshot(self, snapshot: GrantAuthoritySnapshot) -> bool:
        return type(snapshot) is GrantAuthoritySnapshot and self.authority_snapshot == snapshot

    @property
    def permitted_verbs(self) -> tuple[VerbId, ...]:
        return self.authority_snapshot.permitted_verbs

    @property
    def authority_evaluation_id(self) -> str:
        return self.authority_snapshot.authority_evaluation_id

    @property
    def authority_evaluation_digest(self) -> str:
        return self.authority_snapshot.authority_evaluation_digest

    @property
    def authority_policy_generation(self) -> int:
        return self.authority_snapshot.authority_policy_generation


@dataclass(frozen=True)
class StoredGrantLease(GrantLeaseCandidate):
    """Persisted authority snapshot plus its store-owned monotonic generation."""

    lease_generation: int
    status: GrantLeaseStatus = GrantLeaseStatus.ACTIVE
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _positive_bigint("lease_generation", self.lease_generation)
        self._validate_terminal_state()

    @classmethod
    def from_candidate(
        cls,
        candidate: GrantLeaseCandidate,
        *,
        lease_generation: int,
    ) -> StoredGrantLease:
        """Seal an exact candidate at the generation allocated by durable storage."""

        if type(candidate) is not GrantLeaseCandidate:
            raise TypeError("candidate must be an exact GrantLeaseCandidate")
        return StoredGrantLease(
            lease_id=candidate.lease_id,
            issue_operation_id=candidate.issue_operation_id,
            binding=candidate.binding,
            token_digest=candidate.token_digest,
            authority_snapshot=candidate.authority_snapshot,
            issued_at=candidate.issued_at,
            expires_at=candidate.expires_at,
            max_ttl_seconds=candidate.max_ttl_seconds,
            expected_current_lease_generation=(candidate.expected_current_lease_generation),
            lease_generation=_positive_bigint("lease_generation", lease_generation),
        )

    def is_projection_of(self, candidate: GrantLeaseCandidate) -> bool:
        """Return whether durable storage preserved every immutable issue input."""

        if type(candidate) is not GrantLeaseCandidate:
            return False
        return (
            self.lease_id == candidate.lease_id
            and self.issue_operation_id == candidate.issue_operation_id
            and self.binding == candidate.binding
            and self.token_digest == candidate.token_digest
            and self.authority_snapshot == candidate.authority_snapshot
            and self.issued_at == candidate.issued_at
            and self.expires_at == candidate.expires_at
            and self.max_ttl_seconds == candidate.max_ttl_seconds
            and self.expected_current_lease_generation
            == candidate.expected_current_lease_generation
        )

    def _validate_terminal_state(self) -> None:
        if type(self.status) is not GrantLeaseStatus:
            raise TypeError("status must be an exact GrantLeaseStatus")
        if self.status is GrantLeaseStatus.REVOKED:
            if self.revoked_at is None or self.revocation_reason is None:
                raise ValueError("revoked leases require a timestamp and reason")
            _aware("revoked_at", self.revoked_at)
            validate_revocation_reason(self.revocation_reason)
            if self.revoked_at < self.issued_at:
                raise ValueError("revoked_at cannot precede issued_at")
        elif self.revoked_at is not None or self.revocation_reason is not None:
            raise ValueError("non-revoked leases cannot carry revocation metadata")

    def revoke(self, *, at: datetime, reason: str) -> StoredGrantLease:
        """Return an immutable revoked copy; callers persist it atomically."""

        if self.status is not GrantLeaseStatus.ACTIVE:
            return self
        return replace(
            self,
            status=GrantLeaseStatus.REVOKED,
            revoked_at=_aware("revoked_at", at),
            revocation_reason=validate_revocation_reason(reason),
        )

    def expire(self) -> StoredGrantLease:
        """Return an immutable expired copy without manufacturing a revocation."""

        if self.status is not GrantLeaseStatus.ACTIVE:
            return self
        return replace(self, status=GrantLeaseStatus.EXPIRED)

    def is_active_at(self, at: datetime, *, authority_policy_generation: int) -> bool:
        """Evaluate metadata only; bearer authentication still requires digest comparison."""

        now = _aware("at", at)
        if (
            type(authority_policy_generation) is not int
            or not 1 <= authority_policy_generation <= MAX_SIGNED_BIGINT
        ):
            return False
        return (
            self.status is GrantLeaseStatus.ACTIVE
            and self.expires_at > now
            and self.authority_policy_generation == authority_policy_generation
        )

    def authorizes_request(
        self,
        binding: GrantLeaseBinding,
        authority: GrantAuthoritySnapshot,
        *,
        at: datetime,
        verb_id: VerbId,
    ) -> bool:
        """Evaluate the exact trusted request observation after digest lookup."""

        return bool(
            type(binding) is GrantLeaseBinding
            and type(authority) is GrantAuthoritySnapshot
            and self.binding == binding
            and self.authority_snapshot == authority
            and self.is_active_at(
                at,
                authority_policy_generation=authority.authority_policy_generation,
            )
            and verb_id in self.permitted_verbs
        )


__all__ = [
    "ActiveGrantGenerationConflict",
    "GrantAuthoritySnapshot",
    "GrantLeaseCandidate",
    "GrantLeaseBinding",
    "GrantLeaseConflict",
    "GrantLeaseStatus",
    "GrantRootBinding",
    "GrantRequestObservation",
    "LeaseGenerationExhausted",
    "MAX_GRANT_TTL_SECONDS",
    "MAX_PERMITTED_VERBS",
    "MAX_REVOCATION_REASON_LENGTH",
    "StaleGrantGeneration",
    "StoredGrantLease",
    "validate_revocation_reason",
]
