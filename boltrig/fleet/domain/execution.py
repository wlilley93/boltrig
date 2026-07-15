"""Vendor-neutral lifecycle types for a bounded agent execution phase."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from boltrig.models import (
    OrganisationUserRef,
    PhaseMode as _CanonicalPhaseMode,
    RunId,
    WorkItemId,
    WorkspaceId,
    utcnow,
)

from .json_types import CanonicalJSON

PhaseId = str
PhaseMode = _CanonicalPhaseMode


def _require_identifier(label: str, value: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty, trimmed identifier")


class SandboxPolicy(str, Enum):
    """Boltrig-owned sandbox ceiling passed to an execution runtime."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"


class ApprovalState(str, Enum):
    """Current durable approval state; messages cannot modify it."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PhaseStatus(str, Enum):
    """Canonical phase lifecycle projected by runtime-specific events."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    INTERRUPTING = "interrupting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RuntimeEventKind(str, Enum):
    """Stable event vocabulary emitted by every runtime adapter."""

    THREAD_STARTED = "thread.started"
    TURN_STARTED = "turn.started"
    ITEM_STARTED = "item.started"
    ITEM_UPDATED = "item.updated"
    ITEM_COMPLETED = "item.completed"
    APPROVAL_REQUESTED = "approval.requested"
    TURN_COMPLETED = "turn.completed"
    WARNING = "runtime.warning"
    ERROR = "runtime.error"
    UNKNOWN = "runtime.unknown"


@dataclass(frozen=True)
class ProfileRef:
    """Immutable reference to a reusable agent birth configuration."""

    name: str
    version: str

    def __post_init__(self) -> None:
        _require_identifier("profile name", self.name)
        _require_identifier("profile version", self.version)


@dataclass(frozen=True)
class SkillVersionRef:
    """A selected skill version; this reference grants no authority."""

    name: str
    version: str

    def __post_init__(self) -> None:
        _require_identifier("skill name", self.name)
        _require_identifier("skill version", self.version)


@dataclass(frozen=True)
class PhaseRef:
    """Boltrig's canonical identity for one bounded execution phase."""

    root_run_id: RunId
    phase_id: PhaseId
    principal: OrganisationUserRef
    workspace_id: WorkspaceId
    work_item_id: WorkItemId | None = None

    def __post_init__(self) -> None:
        _require_identifier("root_run_id", self.root_run_id)
        _require_identifier("phase_id", self.phase_id)
        if type(self.principal) is not OrganisationUserRef:
            raise TypeError("principal must be an exact OrganisationUserRef")
        _require_identifier("workspace_id", self.workspace_id)
        if self.work_item_id is not None:
            _require_identifier("work_item_id", self.work_item_id)


@dataclass(frozen=True)
class PhaseAssignmentRef:
    """The exact assignment allowed to operate a phase runtime."""

    phase: PhaseRef
    assignment_id: str

    def __post_init__(self) -> None:
        _require_identifier("assignment_id", self.assignment_id)


@dataclass(frozen=True)
class RuntimeThreadRef:
    """Opaque binding from a Boltrig phase to a runtime thread."""

    assignment: PhaseAssignmentRef
    runtime: str
    thread_id: str

    def __post_init__(self) -> None:
        _require_identifier("runtime", self.runtime)
        _require_identifier("thread_id", self.thread_id)


@dataclass(frozen=True)
class RuntimeTurnRef:
    """Opaque binding to one turn inside a runtime thread."""

    thread: RuntimeThreadRef
    turn_id: str

    def __post_init__(self) -> None:
        _require_identifier("turn_id", self.turn_id)


@dataclass(frozen=True)
class RuntimeEvent:
    """Normalized runtime event suitable for a durable Boltrig event log."""

    event_id: str
    assignment: PhaseAssignmentRef
    kind: RuntimeEventKind
    thread: RuntimeThreadRef | None = None
    turn: RuntimeTurnRef | None = None
    item_id: str | None = None
    source_sequence: int | None = None
    payload: CanonicalJSON = field(default_factory=CanonicalJSON.empty_mapping)
    occurred_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        _require_identifier("event_id", self.event_id)
        if self.item_id is not None:
            _require_identifier("item_id", self.item_id)
        if self.thread is not None and self.thread.assignment != self.assignment:
            raise ValueError("runtime event thread belongs to another assignment")
        if self.turn is not None:
            if self.thread is not None and self.turn.thread != self.thread:
                raise ValueError("runtime event turn and thread bindings disagree")
            if self.turn.thread.assignment != self.assignment:
                raise ValueError("runtime event turn belongs to another assignment")
        if self.source_sequence is not None and self.source_sequence < 0:
            raise ValueError("runtime event source_sequence must be non-negative")


@dataclass(frozen=True)
class RecordedRuntimeEvent:
    """A runtime event with the canonical sequence assigned by the event log."""

    event: RuntimeEvent
    sequence: int

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("recorded runtime event sequence must be positive")
