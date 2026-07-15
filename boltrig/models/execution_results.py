"""Structured result and verification records for the execution ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import cast

from .base import WorkItemId, utcnow
from .execution_ledger import AssignmentId, PhaseId, ResultId, VerificationId
from .execution_scope import (
    MAX_COLLECTION_ITEMS,
    EngineOwner,
    ExecutionScopeRef,
    OrganisationUserRef,
    _require_aware,
    _require_exact_enum,
    _require_exact_type,
    _require_identifier,
    _require_positive,
    _require_sha256,
)
from .execution_transitions import ResultStatus, VerificationStatus
from .execution_work_values import ProfileVersionPin


class EvidenceKind(str, Enum):
    ARTIFACT = "artifact"
    AUDIT_EVENT = "audit_event"
    DOMAIN_OBJECT = "domain_object"
    TEST_RESULT = "test_result"


class FindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VerifierKind(str, Enum):
    ORGANISATION_USER = "organisation_user"
    SYSTEM = "system"


@dataclass(frozen=True)
class EvidenceRef:
    id: str
    kind: EvidenceKind
    digest: str

    def __post_init__(self) -> None:
        _require_identifier("evidence id", self.id)
        _require_exact_enum("evidence kind", self.kind, EvidenceKind)
        _require_sha256("evidence digest", self.digest)


@dataclass(frozen=True)
class ResultFinding:
    code: str
    severity: FindingSeverity
    summary_digest: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier("finding code", self.code)
        _require_exact_enum("finding severity", self.severity, FindingSeverity)
        _require_sha256("finding summary digest", self.summary_digest)
        _require_unique_identifiers("finding evidence_ids", self.evidence_ids)


@dataclass(frozen=True)
class VerificationCheck:
    code: str
    passed: bool
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier("verification check code", self.code)
        if type(self.passed) is not bool:
            raise TypeError("verification check passed must be an exact bool")
        _require_unique_identifiers("verification evidence_ids", self.evidence_ids)


@dataclass(frozen=True)
class ResultBlocker:
    code: str
    detail_digest: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier("blocker code", self.code)
        _require_sha256("blocker detail digest", self.detail_digest)
        _require_unique_identifiers("blocker evidence_ids", self.evidence_ids)


@dataclass(frozen=True)
class ResultHandoff:
    target_profile: ProfileVersionPin
    summary_digest: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_exact_type("target_profile", self.target_profile, ProfileVersionPin)
        _require_sha256("handoff summary digest", self.summary_digest)
        _require_unique_identifiers("handoff evidence_ids", self.evidence_ids)


@dataclass(frozen=True)
class ExecutionUsage:
    input_tokens: int
    output_tokens: int
    tool_calls: int
    cost_micros: int

    def __post_init__(self) -> None:
        for label, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("tool_calls", self.tool_calls),
            ("cost_micros", self.cost_micros),
        ):
            _require_positive(label, value, allow_zero=True)


@dataclass(frozen=True)
class VerifierRef:
    kind: VerifierKind
    organisation_user: OrganisationUserRef | None = None
    system_id: str | None = None

    def __post_init__(self) -> None:
        _require_exact_enum("verifier kind", self.kind, VerifierKind)
        if self.organisation_user is not None:
            _require_exact_type("organisation_user", self.organisation_user, OrganisationUserRef)
        if self.system_id is not None:
            _require_identifier("system_id", self.system_id)
        is_user = self.kind is VerifierKind.ORGANISATION_USER
        if is_user != (self.organisation_user is not None and self.system_id is None):
            raise ValueError("organisation-user verifier shape is invalid")
        if not is_user and (self.system_id is None or self.organisation_user is not None):
            raise ValueError("system verifier shape is invalid")


@dataclass(frozen=True)
class ExecutionResult:
    scope: ExecutionScopeRef
    id: ResultId
    phase_id: PhaseId
    work_item_id: WorkItemId
    assignment_id: AssignmentId
    output_digest: str
    status: ResultStatus
    evidence: tuple[EvidenceRef, ...]
    findings: tuple[ResultFinding, ...]
    blockers: tuple[ResultBlocker, ...]
    handoffs: tuple[ResultHandoff, ...]
    usage: ExecutionUsage
    completed_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        for label, value in (
            ("result id", self.id),
            ("phase_id", self.phase_id),
            ("work_item_id", self.work_item_id),
            ("assignment_id", self.assignment_id),
        ):
            _require_identifier(label, value)
        _require_sha256("output_digest", self.output_digest)
        _require_exact_enum("status", self.status, ResultStatus)
        _require_exact_tuple("evidence", self.evidence, EvidenceRef)
        _require_exact_tuple("findings", self.findings, ResultFinding)
        _require_exact_tuple("blockers", self.blockers, ResultBlocker)
        _require_exact_tuple("handoffs", self.handoffs, ResultHandoff)
        _require_exact_type("usage", self.usage, ExecutionUsage)
        evidence_ids = tuple(item.id for item in self.evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("result evidence ids must be unique")
        known = set(evidence_ids)
        referenced = (
            tuple(item.evidence_ids for item in self.findings)
            + tuple(item.evidence_ids for item in self.blockers)
            + tuple(item.evidence_ids for item in self.handoffs)
        )
        if any(not set(reference_ids).issubset(known) for reference_ids in referenced):
            raise ValueError("structured result references unknown evidence")
        _require_aware("completed_at", self.completed_at)


@dataclass(frozen=True)
class ExecutionVerification:
    scope: ExecutionScopeRef
    id: VerificationId
    phase_id: PhaseId
    work_item_id: WorkItemId
    result_id: ResultId
    status: VerificationStatus
    evidence_digest: str
    checks: tuple[VerificationCheck, ...]
    verified_by: VerifierRef | None = None
    created_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        for label, value in (
            ("verification id", self.id),
            ("phase_id", self.phase_id),
            ("work_item_id", self.work_item_id),
            ("result_id", self.result_id),
        ):
            _require_identifier(label, value)
        _require_exact_enum("status", self.status, VerificationStatus)
        _require_sha256("evidence_digest", self.evidence_digest)
        _require_exact_tuple("checks", self.checks, VerificationCheck)
        if self.verified_by is not None:
            _require_exact_type("verified_by", self.verified_by, VerifierRef)
            principal = self.verified_by.organisation_user
            if principal is not None and principal.tenant_id != self.scope.tenant_id:
                raise ValueError("verifier and execution scope tenants differ")
        if self.status is not VerificationStatus.PENDING and not self.checks:
            raise ValueError("terminal verification must contain structured checks")
        if self.status is not VerificationStatus.PENDING and self.verified_by is None:
            raise ValueError("terminal verification must identify its verifier kind")
        if self.status is VerificationStatus.PASSED and any(not item.passed for item in self.checks):
            raise ValueError("passed verification cannot contain a failed check")
        if self.status is VerificationStatus.FAILED and all(item.passed for item in self.checks):
            raise ValueError("failed verification must contain a failed check")
        _require_aware("created_at", self.created_at)


def _require_unique_identifiers(label: str, values: object) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{label} must be an immutable tuple")
    normalized = tuple(_require_identifier(label, value) for value in cast(tuple[object, ...], values))
    if len(normalized) > MAX_COLLECTION_ITEMS:
        raise ValueError(f"{label} exceeds the collection limit")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must be unique")


def _require_exact_tuple(label: str, values: object, expected: type[object]) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{label} must be an immutable tuple")
    entries = cast(tuple[object, ...], values)
    if len(entries) > MAX_COLLECTION_ITEMS:
        raise ValueError(f"{label} exceeds the collection limit")
    if any(type(value) is not expected for value in entries):
        raise TypeError(f"{label} must contain exact {expected.__name__} values")
