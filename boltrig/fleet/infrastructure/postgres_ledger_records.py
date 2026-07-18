"""Row<->object mapping for the six canonical execution-ledger records.

Each record persists its scalar fields to typed columns and its nested value
objects to JSONB via the generic codec. The reconstructed object equals the
original by dataclass value equality, which the shared contract asserts.
"""

from __future__ import annotations

from typing import Any

from boltrig.fleet.infrastructure.postgres_ledger_codec import decode, decode_seq, encode
from boltrig.models import (
    AssignmentLease,
    AssignmentStatus,
    AttestationSetRef,
    AuthorityEvaluationRef,
    CancellationMetadata,
    EvidenceRef,
    ExecutionAssignment,
    ExecutionPhase,
    ExecutionPhaseStatus,
    ExecutionResult,
    ExecutionRootRun,
    ExecutionScopeRef,
    ExecutionUsage,
    ExecutionVerification,
    ExecutionWorkItem,
    LedgerWorkItemStatus,
    OrganisationUserRef,
    PhaseMode,
    PhaseTerminalOutcome,
    ProfileVersionPin,
    ResultBlocker,
    ResultFinding,
    ResultHandoff,
    ResultStatus,
    RetryPolicy,
    RootRunStatus,
    SkillVersionPin,
    VerificationCheck,
    VerificationStatus,
    VerifierRef,
    WorkspaceScopeRef,
)

Row = Any

ROOT_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "requested_by_user_id",
    "objective_digest", "profile", "policy_generation", "status", "cancellation",
    "final_synthesis_digest", "version", "created_at",
]
PHASE_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "id", "ordinal", "name",
    "objective_digest", "mode", "profile", "skills", "policy_generation",
    "dependencies", "retry", "status", "terminal_outcome", "version", "created_at",
]
WORK_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "id", "phase_id", "ordinal",
    "intent_digest", "dependencies", "parent_id", "requires_verification",
    "status", "version", "created_at",
]
ASSIGNMENT_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "id", "phase_id", "work_item_id",
    "runtime_identity_id", "attempt", "profile", "skills", "authority", "lease",
    "attestation_set", "replaces_assignment_id", "status", "version", "created_at",
]
RESULT_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "id", "phase_id", "work_item_id",
    "assignment_id", "output_digest", "status", "evidence", "findings", "blockers",
    "handoffs", "usage", "completed_at",
]
VERIFICATION_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "id", "phase_id", "work_item_id",
    "result_id", "status", "evidence_digest", "checks", "verified_by", "created_at",
]


def scope_of(row: Row) -> ExecutionScopeRef:
    return ExecutionScopeRef(
        WorkspaceScopeRef(row["tenant_id"], row["workspace_id"]), row["root_run_id"]
    )


def root_values(record: ExecutionRootRun) -> tuple[Any, ...]:
    scope = record.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id,
        record.requested_by.user_id, record.objective_digest, encode(record.profile),
        record.policy_generation, record.status.value, encode(record.cancellation),
        record.final_synthesis_digest, record.version, record.created_at,
    )


def row_to_root(row: Row) -> ExecutionRootRun:
    scope = scope_of(row)
    return ExecutionRootRun(
        scope, OrganisationUserRef(scope.tenant_id, row["requested_by_user_id"]),
        row["objective_digest"], decode(ProfileVersionPin, row["profile"]),
        row["policy_generation"], RootRunStatus(row["status"]),
        decode(CancellationMetadata, row["cancellation"]),
        row["final_synthesis_digest"], row["version"], row["created_at"],
    )


def phase_values(record: ExecutionPhase) -> tuple[Any, ...]:
    scope = record.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id, record.id,
        record.ordinal, record.name, record.objective_digest, record.mode.value,
        encode(record.profile), encode(record.skills), record.policy_generation,
        encode(record.dependencies), encode(record.retry), record.status.value,
        encode(record.terminal_outcome), record.version, record.created_at,
    )


def row_to_phase(row: Row) -> ExecutionPhase:
    return ExecutionPhase(
        scope_of(row), row["id"], row["ordinal"], row["name"], row["objective_digest"],
        PhaseMode(row["mode"]), decode(ProfileVersionPin, row["profile"]),
        decode_seq(SkillVersionPin, row["skills"]), row["policy_generation"],
        tuple(row["dependencies"]), decode(RetryPolicy, row["retry"]),
        ExecutionPhaseStatus(row["status"]), decode(PhaseTerminalOutcome, row["terminal_outcome"]),
        row["version"], row["created_at"],
    )


def work_values(record: ExecutionWorkItem) -> tuple[Any, ...]:
    scope = record.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id, record.id,
        record.phase_id, record.ordinal, record.intent_digest,
        encode(record.dependencies), record.parent_id, record.requires_verification,
        record.status.value, record.version, record.created_at,
    )


def row_to_work(row: Row) -> ExecutionWorkItem:
    return ExecutionWorkItem(
        scope_of(row), row["id"], row["phase_id"], row["ordinal"], row["intent_digest"],
        tuple(row["dependencies"]), row["parent_id"], row["requires_verification"],
        LedgerWorkItemStatus(row["status"]), row["version"], row["created_at"],
    )


def assignment_values(record: ExecutionAssignment) -> tuple[Any, ...]:
    scope = record.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id, record.id,
        record.phase_id, record.work_item_id, record.runtime_identity_id,
        record.attempt, encode(record.profile), encode(record.skills),
        encode(record.authority), encode(record.lease), encode(record.attestation_set),
        record.replaces_assignment_id, record.status.value, record.version, record.created_at,
    )


def row_to_assignment(row: Row) -> ExecutionAssignment:
    return ExecutionAssignment(
        scope_of(row), row["id"], row["phase_id"], row["work_item_id"],
        row["runtime_identity_id"], row["attempt"], decode(ProfileVersionPin, row["profile"]),
        decode_seq(SkillVersionPin, row["skills"]), decode(AuthorityEvaluationRef, row["authority"]),
        decode(AssignmentLease, row["lease"]), decode(AttestationSetRef, row["attestation_set"]),
        row["replaces_assignment_id"], AssignmentStatus(row["status"]), row["version"],
        row["created_at"],
    )


def result_values(record: ExecutionResult) -> tuple[Any, ...]:
    scope = record.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id, record.id,
        record.phase_id, record.work_item_id, record.assignment_id, record.output_digest,
        record.status.value, encode(record.evidence), encode(record.findings),
        encode(record.blockers), encode(record.handoffs), encode(record.usage),
        record.completed_at,
    )


def row_to_result(row: Row) -> ExecutionResult:
    return ExecutionResult(
        scope_of(row), row["id"], row["phase_id"], row["work_item_id"],
        row["assignment_id"], row["output_digest"], ResultStatus(row["status"]),
        decode_seq(EvidenceRef, row["evidence"]), decode_seq(ResultFinding, row["findings"]),
        decode_seq(ResultBlocker, row["blockers"]), decode_seq(ResultHandoff, row["handoffs"]),
        decode(ExecutionUsage, row["usage"]), row["completed_at"],
    )


def verification_values(record: ExecutionVerification) -> tuple[Any, ...]:
    scope = record.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id, record.id,
        record.phase_id, record.work_item_id, record.result_id, record.status.value,
        record.evidence_digest, encode(record.checks), encode(record.verified_by),
        record.created_at,
    )


def row_to_verification(row: Row) -> ExecutionVerification:
    return ExecutionVerification(
        scope_of(row), row["id"], row["phase_id"], row["work_item_id"], row["result_id"],
        VerificationStatus(row["status"]), row["evidence_digest"],
        decode_seq(VerificationCheck, row["checks"]), decode(VerifierRef, row["verified_by"]),
        row["created_at"],
    )


__all__ = [
    "ASSIGNMENT_COLS", "PHASE_COLS", "RESULT_COLS", "ROOT_COLS", "VERIFICATION_COLS",
    "WORK_COLS", "assignment_values", "phase_values", "result_values", "root_values",
    "row_to_assignment", "row_to_phase", "row_to_result", "row_to_root",
    "row_to_verification", "row_to_work", "scope_of", "verification_values", "work_values",
]
