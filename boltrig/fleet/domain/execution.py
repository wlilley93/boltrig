"""Vendor-neutral lifecycle types for a bounded agent execution phase."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import unicodedata

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
MAX_IDENTIFIER_CHARS = 160
MAX_SIGNED_BIGINT = 2**63 - 1


def _contains_unsafe_identifier_character(value: str) -> bool:
    return any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
    )


def _require_identifier(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    text = value
    if (
        not text
        or text != text.strip()
        or len(text) > MAX_IDENTIFIER_CHARS
        or _contains_unsafe_identifier_character(text)
    ):
        raise ValueError(f"{label} must be a bounded, control-free, trimmed identifier")
    return text


def _require_exact_type(label: str, value: object, expected: type[object]) -> None:
    if type(value) is not expected:
        raise TypeError(f"{label} must be an exact {expected.__name__}")


def _require_aware_datetime(label: str, value: object) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{label} must be an exact datetime")
    timestamp = value
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return timestamp


def _require_signed_bigint(label: str, value: object, *, minimum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{label} must be an exact integer")
    number = value
    if not minimum <= number <= MAX_SIGNED_BIGINT:
        qualifier = "non-negative" if minimum == 0 else "positive"
        raise ValueError(f"{label} must be {qualifier} and fit a signed BIGINT")
    return number


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
    NATIVE_SUBAGENT_STARTED = "subagent.started"
    NATIVE_SUBAGENT_ACTIVITY = "subagent.activity"
    NATIVE_SUBAGENT_COMPLETED = "subagent.completed"
    APPROVAL_REQUESTED = "approval.requested"
    # The runtime reporting what a turn actually consumed. Without this the fleet
    # has no usage signal at all from the sole agent runtime, so `price_micros`
    # prices every turn at zero tokens and a tenant's cost ledger stays empty
    # however much it spends.
    TOKEN_USAGE = "turn.token_usage"
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
        _require_exact_type("phase", self.phase, PhaseRef)
        _require_identifier("assignment_id", self.assignment_id)


@dataclass(frozen=True)
class RuntimeThreadRef:
    """Opaque binding from a Boltrig phase to a runtime thread."""

    assignment: PhaseAssignmentRef
    runtime: str
    thread_id: str

    def __post_init__(self) -> None:
        _require_exact_type("assignment", self.assignment, PhaseAssignmentRef)
        _require_identifier("runtime", self.runtime)
        _require_identifier("thread_id", self.thread_id)


@dataclass(frozen=True)
class RuntimeTurnRef:
    """Opaque binding to one turn inside a runtime thread."""

    thread: RuntimeThreadRef
    turn_id: str

    def __post_init__(self) -> None:
        _require_exact_type("thread", self.thread, RuntimeThreadRef)
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
        _require_exact_type("assignment", self.assignment, PhaseAssignmentRef)
        _require_exact_type("kind", self.kind, RuntimeEventKind)
        if self.item_id is not None:
            _require_identifier("item_id", self.item_id)
        if self.thread is not None:
            _require_exact_type("thread", self.thread, RuntimeThreadRef)
            if self.thread.assignment != self.assignment:
                raise ValueError("runtime event thread belongs to another assignment")
        if self.turn is not None:
            _require_exact_type("turn", self.turn, RuntimeTurnRef)
            if self.thread is not None and self.turn.thread != self.thread:
                raise ValueError("runtime event turn and thread bindings disagree")
            if self.turn.thread.assignment != self.assignment:
                raise ValueError("runtime event turn belongs to another assignment")
        if self.source_sequence is not None:
            _require_signed_bigint("source_sequence", self.source_sequence, minimum=0)
        _require_exact_type("payload", self.payload, CanonicalJSON)
        _require_aware_datetime("occurred_at", self.occurred_at)


@dataclass(frozen=True)
class RecordedRuntimeEvent:
    """A runtime event with the canonical sequence assigned by the event log."""

    event: RuntimeEvent
    sequence: int

    def __post_init__(self) -> None:
        _require_exact_type("event", self.event, RuntimeEvent)
        _require_signed_bigint("sequence", self.sequence, minimum=1)
