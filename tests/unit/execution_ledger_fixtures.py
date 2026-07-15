"""Reusable canonical values for execution-ledger adapter contract tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import cast

from boltrig.fleet.ports.execution_ledger import (
    AtomicEventAppend,
    AtomicLedgerWrite,
    ExecutionLedgerRecord,
    OutboxIntent,
)
from boltrig.models import (
    AssignmentLease,
    AssignmentStatus,
    AuthorityEvaluationRef,
    CanonicalEventPayload,
    CodexBindingKind,
    CodexThreadBinding,
    EngineOwner,
    ExecutionAggregateKind,
    ExecutionAssignment,
    ExecutionEventKind,
    ExecutionPhase,
    ExecutionResult,
    ExecutionRootRun,
    ExecutionScopeRef,
    ExecutionUsage,
    ExecutionVerification,
    ExecutionWorkItem,
    LedgerCommand,
    LedgerCommandKind,
    NormalizedExecutionMetadata,
    OrganisationUserRef,
    PendingExecutionEvent,
    PhaseMode,
    ProfileVersionPin,
    ResultStatus,
    RetryPolicy,
    RuntimeIdentity,
    SkillVersionPin,
    VerificationStatus,
    WorkspaceScopeRef,
)

NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
CLOCK_NOW = NOW + timedelta(seconds=30)


def digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


@dataclass(frozen=True)
class LedgerValues:
    tenant: str = "org-a"
    workspace: str = "workspace-a"
    run: str = "run-a"

    @property
    def scope(self) -> ExecutionScopeRef:
        return ExecutionScopeRef(WorkspaceScopeRef(self.tenant, self.workspace), self.run)

    @property
    def principal(self) -> OrganisationUserRef:
        return OrganisationUserRef(self.tenant, "user-a")

    @property
    def profile(self) -> ProfileVersionPin:
        return ProfileVersionPin("researcher", "1.0.0", digest("profile"))

    @property
    def skills(self) -> tuple[SkillVersionPin, ...]:
        return (SkillVersionPin("research", "1.0.0", digest("skill")),)

    def root(self) -> ExecutionRootRun:
        return ExecutionRootRun(
            self.scope,
            self.principal,
            digest("objective"),
            self.profile,
            3,
            created_at=NOW,
        )

    def phase(self) -> ExecutionPhase:
        return ExecutionPhase(
            self.scope,
            "phase-a",
            1,
            "Research",
            digest("phase-objective"),
            PhaseMode.READ_ONLY,
            self.profile,
            self.skills,
            3,
            (),
            RetryPolicy(3, 0, 0),
            created_at=NOW,
        )

    def work(self) -> ExecutionWorkItem:
        return ExecutionWorkItem(
            self.scope,
            "work-a",
            "phase-a",
            1,
            digest("work-intent"),
            created_at=NOW,
        )

    def identity(self, *, identity_id: str = "runtime-a") -> RuntimeIdentity:
        return RuntimeIdentity(
            identity_id,
            self.principal,
            self.scope.workspace,
            created_at=NOW,
        )

    def assignment(
        self,
        *,
        attempt: int = 1,
        replaces: str | None = None,
        authority_policy_generation: int = 3,
    ) -> ExecutionAssignment:
        return ExecutionAssignment(
            self.scope,
            f"assignment-{attempt}",
            "phase-a",
            "work-a",
            "runtime-a",
            attempt,
            self.profile,
            self.skills,
            AuthorityEvaluationRef(
                "authority-a",
                digest("authority"),
                authority_policy_generation,
                ("document.read", "ticket.read"),
                NOW,
            ),
            replaces_assignment_id=replaces,
            created_at=NOW,
        )

    def lease(self, *, attempt: int = 1) -> AssignmentLease:
        return AssignmentLease(
            f"lease-{attempt}",
            "worker-a",
            NOW,
            CLOCK_NOW + timedelta(minutes=5),
        )

    def result(self, *, assignment_id: str = "assignment-1") -> ExecutionResult:
        return ExecutionResult(
            self.scope,
            f"result-{assignment_id}",
            "phase-a",
            "work-a",
            assignment_id,
            digest("output"),
            ResultStatus.SUCCEEDED,
            (),
            (),
            (),
            (),
            ExecutionUsage(10, 5, 1, 0),
            NOW,
        )

    def verification(self, *, result_id: str = "result-assignment-1") -> ExecutionVerification:
        return ExecutionVerification(
            self.scope,
            "verification-a",
            "phase-a",
            "work-a",
            result_id,
            VerificationStatus.PENDING,
            digest("evidence"),
            (),
            created_at=NOW,
        )

    def thread(self, *, thread_id: str = "thread-a") -> CodexThreadBinding:
        return CodexThreadBinding(
            self.scope,
            "phase-a",
            "assignment-1",
            "runtime-a",
            CodexBindingKind.PHASE,
            thread_id,
            bound_at=NOW,
        )

    def write(
        self,
        record: ExecutionLedgerRecord,
        command_kind: LedgerCommandKind,
        *,
        expected_version: int,
        command_id: str,
        event_kind: ExecutionEventKind | None = None,
        event_id: str | None = None,
    ) -> AtomicLedgerWrite:
        aggregate_kind, aggregate_id = _aggregate(record)
        command = LedgerCommand.create(
            id=command_id,
            kind=command_kind,
            scope=self.scope,
            aggregate_kind=aggregate_kind,
            aggregate_id=aggregate_id,
            expected_version=expected_version,
            parameters=(),
            issued_by=self.principal,
            issued_at=NOW,
        )
        selected_kind = event_kind or _event_kind(command_kind)
        identifier = event_id or f"event-{command_id}"
        event = PendingExecutionEvent(
            identifier,
            self.scope,
            aggregate_kind,
            aggregate_id,
            selected_kind,
            f"ingest-{identifier}",
            f"correlation-{self.run}",
            CanonicalEventPayload.from_metadata(
                NormalizedExecutionMetadata(status=_record_status(record))
            ),
            EngineOwner.BOLTRIG,
            command.id,
            occurred_at=NOW,
        )
        return AtomicLedgerWrite(
            command,
            record,
            event,
            (
                OutboxIntent(
                    f"outbox-{identifier}",
                    "execution.timeline",
                    f"deliver-{identifier}",
                    NOW,
                ),
            ),
        )

    def runtime_event(
        self,
        record: ExecutionLedgerRecord,
        *,
        identifier: str,
        source_sequence: int,
    ) -> AtomicEventAppend:
        aggregate_kind, aggregate_id = _aggregate(record)
        event = PendingExecutionEvent(
            f"event-{identifier}",
            self.scope,
            aggregate_kind,
            aggregate_id,
            ExecutionEventKind.RUNTIME_OBSERVED,
            f"ingest-{identifier}",
            f"correlation-{self.run}",
            CanonicalEventPayload.from_metadata(
                NormalizedExecutionMetadata(runtime_event="turn.completed")
            ),
            EngineOwner.CODEX,
            source_sequence=source_sequence,
            occurred_at=NOW,
        )
        return AtomicEventAppend(
            event,
            (
                OutboxIntent(
                    f"outbox-{identifier}",
                    "execution.timeline",
                    f"deliver-{identifier}",
                    NOW,
                ),
            ),
        )


def running_assignment(values: LedgerValues) -> ExecutionAssignment:
    offered = values.assignment()
    claimed = replace(
        offered,
        status=AssignmentStatus.CLAIMED,
        lease=values.lease(),
        version=2,
    )
    return replace(claimed, status=AssignmentStatus.RUNNING, version=3)


def _aggregate(record: ExecutionLedgerRecord) -> tuple[ExecutionAggregateKind, str]:
    if type(record) is ExecutionRootRun:
        return (ExecutionAggregateKind.ROOT_RUN, record.scope.root_run_id)
    mapping = {
        ExecutionPhase: ExecutionAggregateKind.PHASE,
        ExecutionWorkItem: ExecutionAggregateKind.WORK_ITEM,
        ExecutionAssignment: ExecutionAggregateKind.ASSIGNMENT,
        ExecutionResult: ExecutionAggregateKind.RESULT,
        ExecutionVerification: ExecutionAggregateKind.VERIFICATION,
    }
    return (mapping[type(record)], cast(str, getattr(record, "id")))


def _event_kind(kind: LedgerCommandKind) -> ExecutionEventKind:
    return {
        LedgerCommandKind.CREATE_ROOT: ExecutionEventKind.CREATED,
        LedgerCommandKind.CREATE_PHASE: ExecutionEventKind.CREATED,
        LedgerCommandKind.ENQUEUE_WORK: ExecutionEventKind.CREATED,
        LedgerCommandKind.ASSIGN_WORK: ExecutionEventKind.CREATED,
        LedgerCommandKind.REPLACE_ASSIGNMENT: ExecutionEventKind.CREATED,
        LedgerCommandKind.RECORD_RESULT: ExecutionEventKind.RESULT_RECORDED,
        LedgerCommandKind.RECORD_VERIFICATION: ExecutionEventKind.VERIFICATION_RECORDED,
        LedgerCommandKind.TRANSITION_STATUS: ExecutionEventKind.STATUS_CHANGED,
        LedgerCommandKind.CANCEL: ExecutionEventKind.INTERRUPTED,
    }[kind]


def _record_status(record: ExecutionLedgerRecord) -> str:
    status = getattr(record, "status")
    return str(status.value)


__all__ = ["CLOCK_NOW", "LedgerValues", "NOW", "digest", "running_assignment"]
