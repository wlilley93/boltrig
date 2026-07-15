"""Credential-free durable state for one run-scoped MCP grant lease."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum

from boltrig.models import RunId, TenantId, VerbId, WorkspaceId
from boltrig.models.grants import is_safe_identifier, normalize_identifier

from .execution import PhaseAssignmentRef, PhaseId

MAX_IDENTIFIER_LENGTH = 256
MAX_PERMITTED_VERBS = 256
MAX_GRANT_TTL_SECONDS = 3600


def _identifier(label: str, value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty, trimmed identifier")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{label} exceeds the bounded identifier length")
    return value


def _aware(label: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _concrete_verbs(values: tuple[VerbId, ...]) -> tuple[VerbId, ...]:
    if len(values) > MAX_PERMITTED_VERBS:
        raise ValueError(f"authority snapshots permit at most {MAX_PERMITTED_VERBS} verbs")
    result: set[VerbId] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError("permitted verb must be a string")
        canonical = normalize_identifier(_identifier("permitted verb", value))
        if canonical != value or not is_safe_identifier(canonical) or "*" in canonical:
            raise ValueError("permitted verbs must be safe concrete identifiers")
        result.add(canonical)
    return tuple(sorted(result))


def _raw_sha256_digest(label: str, value: str) -> str:
    _identifier(label, value)
    if len(value) != 64 or value != value.lower():
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest") from None
    return value


def _prefixed_sha256_digest(label: str, value: str) -> str:
    _identifier(label, value)
    if not value.startswith("sha256:"):
        raise ValueError(f"{label} must be a lowercase sha256 digest")
    _raw_sha256_digest(label, value.removeprefix("sha256:"))
    return value


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
        if not isinstance(assignment, PhaseAssignmentRef):
            raise TypeError("assignment must be a PhaseAssignmentRef")
        phase = assignment.phase
        return cls(
            tenant_id=phase.principal.tenant_id,
            workspace_id=phase.workspace_id,
            root_run_id=phase.root_run_id,
            phase_id=phase.phase_id,
            assignment_id=assignment.assignment_id,
        )


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
class StoredGrantLease:
    """Persistable authority snapshot with a digest instead of credential material."""

    lease_id: str
    binding: GrantLeaseBinding
    token_digest: str
    permitted_verbs: tuple[VerbId, ...]
    authority_evaluation_id: str
    authority_evaluation_digest: str
    issued_at: datetime
    expires_at: datetime
    max_ttl_seconds: int
    policy_generation: int
    status: GrantLeaseStatus = GrantLeaseStatus.ACTIVE
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        _identifier("lease_id", self.lease_id)
        if not isinstance(self.binding, GrantLeaseBinding):
            raise TypeError("binding must be a GrantLeaseBinding")
        object.__setattr__(
            self, "token_digest", _raw_sha256_digest("token digest", self.token_digest)
        )
        object.__setattr__(self, "permitted_verbs", _concrete_verbs(self.permitted_verbs))
        _identifier("authority_evaluation_id", self.authority_evaluation_id)
        object.__setattr__(
            self,
            "authority_evaluation_digest",
            _prefixed_sha256_digest(
                "authority evaluation digest", self.authority_evaluation_digest
            ),
        )
        issued_at = _aware("issued_at", self.issued_at)
        expires_at = _aware("expires_at", self.expires_at)
        if (
            type(self.max_ttl_seconds) is not int
            or not 1 <= self.max_ttl_seconds <= MAX_GRANT_TTL_SECONDS
        ):
            raise ValueError(
                f"max_ttl_seconds must be between 1 and {MAX_GRANT_TTL_SECONDS}"
            )
        if type(self.policy_generation) is not int or self.policy_generation < 1:
            raise ValueError("policy_generation must be a positive integer")
        ttl = expires_at - issued_at
        if ttl <= timedelta(0) or ttl > timedelta(seconds=self.max_ttl_seconds):
            raise ValueError("lease lifetime must be positive and within its maximum TTL")
        self._validate_terminal_state()

    def _validate_terminal_state(self) -> None:
        if not isinstance(self.status, GrantLeaseStatus):
            raise TypeError("status must be a GrantLeaseStatus")
        if self.status is GrantLeaseStatus.REVOKED:
            if self.revoked_at is None or self.revocation_reason is None:
                raise ValueError("revoked leases require a timestamp and reason")
            _aware("revoked_at", self.revoked_at)
            _identifier("revocation_reason", self.revocation_reason)
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
            revocation_reason=_identifier("revocation_reason", reason),
        )

    def expire(self) -> StoredGrantLease:
        """Return an immutable expired copy without manufacturing a revocation."""

        if self.status is not GrantLeaseStatus.ACTIVE:
            return self
        return replace(self, status=GrantLeaseStatus.EXPIRED)

    def is_active_at(self, at: datetime, *, policy_generation: int) -> bool:
        """Evaluate metadata only; bearer authentication still requires digest comparison."""

        now = _aware("at", at)
        if type(policy_generation) is not int or policy_generation < 1:
            return False
        return (
            self.status is GrantLeaseStatus.ACTIVE
            and self.expires_at > now
            and self.policy_generation == policy_generation
        )


__all__ = [
    "ActiveGrantGenerationConflict",
    "GrantLeaseBinding",
    "GrantLeaseConflict",
    "GrantLeaseStatus",
    "GrantRootBinding",
    "MAX_GRANT_TTL_SECONDS",
    "MAX_PERMITTED_VERBS",
    "StaleGrantGeneration",
    "StoredGrantLease",
]
