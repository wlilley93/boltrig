"""Pinned policy, retry, lease, cancellation, and terminal execution values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .execution_scope import (
    OrganisationUserRef,
    _require_aware,
    _require_exact_type,
    _require_identifier,
    _require_positive,
    _require_sha256,
)


@dataclass(frozen=True)
class ProfileVersionPin:
    name: str
    version: str
    digest: str

    def __post_init__(self) -> None:
        _require_identifier("profile name", self.name)
        _require_identifier("profile version", self.version)
        _require_sha256("profile digest", self.digest)


@dataclass(frozen=True)
class SkillVersionPin:
    name: str
    version: str
    digest: str

    def __post_init__(self) -> None:
        _require_identifier("skill name", self.name)
        _require_identifier("skill version", self.version)
        _require_sha256("skill digest", self.digest)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    initial_backoff_seconds: int = 0
    max_backoff_seconds: int = 0

    def __post_init__(self) -> None:
        _require_positive("max_attempts", self.max_attempts)
        _require_positive("initial_backoff_seconds", self.initial_backoff_seconds, allow_zero=True)
        _require_positive("max_backoff_seconds", self.max_backoff_seconds, allow_zero=True)
        if self.max_attempts > 10:
            raise ValueError("max_attempts exceeds bounded retry policy")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("maximum retry backoff cannot be below initial backoff")


@dataclass(frozen=True)
class AssignmentLease:
    id: str
    owner: str
    claimed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_identifier("lease id", self.id)
        _require_identifier("lease owner", self.owner)
        claimed = _require_aware("claimed_at", self.claimed_at)
        expires = _require_aware("expires_at", self.expires_at)
        if expires <= claimed:
            raise ValueError("assignment lease must expire after it is claimed")


@dataclass(frozen=True)
class AuthorityEvaluationRef:
    """Reference to immutable, server-evaluated effective authority output."""

    id: str
    digest: str
    policy_generation: int
    evaluated_at: datetime

    def __post_init__(self) -> None:
        _require_identifier("authority evaluation id", self.id)
        _require_sha256("authority evaluation digest", self.digest)
        _require_positive("policy_generation", self.policy_generation)
        _require_aware("evaluated_at", self.evaluated_at)


@dataclass(frozen=True)
class CancellationMetadata:
    requested_by: OrganisationUserRef
    reason_code: str
    requested_at: datetime
    detail_digest: str | None = None

    def __post_init__(self) -> None:
        _require_exact_type("requested_by", self.requested_by, OrganisationUserRef)
        _require_identifier("cancellation reason_code", self.reason_code)
        _require_aware("requested_at", self.requested_at)
        if self.detail_digest is not None:
            _require_sha256("cancellation detail_digest", self.detail_digest)


@dataclass(frozen=True)
class PhaseTerminalOutcome:
    code: str
    digest: str
    completed_at: datetime

    def __post_init__(self) -> None:
        _require_identifier("phase outcome code", self.code)
        _require_sha256("phase outcome digest", self.digest)
        _require_aware("phase outcome completed_at", self.completed_at)
