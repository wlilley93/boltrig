"""Boltrig-owned opaque mappings to Codex App Server identifiers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .base import utcnow
from .execution_ledger import AssignmentId, PhaseId
from .execution_scope import (
    EngineOwner,
    ExecutionScopeRef,
    _require_aware,
    _require_exact_enum,
    _require_exact_type,
    _require_identifier,
)


class CodexBindingKind(str, Enum):
    """Trusted mapping classification assigned only by Boltrig."""

    PHASE = "phase"
    NATIVE_OBSERVATION = "native_observation"


@dataclass(frozen=True)
class CodexThreadBinding:
    scope: ExecutionScopeRef
    phase_id: PhaseId
    assignment_id: AssignmentId
    runtime_identity_id: str
    kind: CodexBindingKind
    thread_id: str
    native_parent_thread_id: str | None = None
    bound_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)
    runtime_source_owner: EngineOwner = field(default=EngineOwner.CODEX, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        for label, value in (
            ("phase_id", self.phase_id),
            ("assignment_id", self.assignment_id),
            ("runtime_identity_id", self.runtime_identity_id),
            ("thread_id", self.thread_id),
        ):
            _require_identifier(label, value)
        _require_exact_enum("binding kind", self.kind, CodexBindingKind)
        if self.native_parent_thread_id is not None:
            _require_identifier("native_parent_thread_id", self.native_parent_thread_id)
            if self.native_parent_thread_id == self.thread_id:
                raise ValueError("Codex thread cannot be its own native parent")
        _require_binding_shape(self.kind, self.native_parent_thread_id, "thread")
        _require_aware("bound_at", self.bound_at)


@dataclass(frozen=True)
class CodexTurnBinding:
    scope: ExecutionScopeRef
    thread: CodexThreadBinding
    kind: CodexBindingKind
    turn_id: str
    native_parent_turn_id: str | None = None
    bound_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)
    runtime_source_owner: EngineOwner = field(default=EngineOwner.CODEX, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_exact_type("thread", self.thread, CodexThreadBinding)
        if self.scope != self.thread.scope:
            raise ValueError("turn and thread execution scopes differ")
        _require_exact_enum("binding kind", self.kind, CodexBindingKind)
        _require_identifier("turn_id", self.turn_id)
        if self.native_parent_turn_id is not None:
            _require_identifier("native_parent_turn_id", self.native_parent_turn_id)
            if self.native_parent_turn_id == self.turn_id:
                raise ValueError("Codex turn cannot be its own native parent")
        _require_descendant_kind(self.thread.kind, self.kind, "turn")
        if self.thread.kind is CodexBindingKind.PHASE:
            _require_binding_shape(self.kind, self.native_parent_turn_id, "turn")
        elif self.native_parent_turn_id is not None:
            raise ValueError("native-thread turn must not claim a second native parent")
        _require_aware("bound_at", self.bound_at)


@dataclass(frozen=True)
class CodexItemBinding:
    scope: ExecutionScopeRef
    turn: CodexTurnBinding
    kind: CodexBindingKind
    item_id: str
    native_parent_item_id: str | None = None
    bound_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)
    runtime_source_owner: EngineOwner = field(default=EngineOwner.CODEX, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_exact_type("turn", self.turn, CodexTurnBinding)
        if self.scope != self.turn.scope:
            raise ValueError("item and turn execution scopes differ")
        _require_exact_enum("binding kind", self.kind, CodexBindingKind)
        _require_identifier("item_id", self.item_id)
        if self.native_parent_item_id is not None:
            _require_identifier("native_parent_item_id", self.native_parent_item_id)
            if self.native_parent_item_id == self.item_id:
                raise ValueError("Codex item cannot be its own native parent")
        _require_descendant_kind(self.turn.kind, self.kind, "item")
        if self.turn.kind is CodexBindingKind.PHASE:
            _require_binding_shape(self.kind, self.native_parent_item_id, "item")
        elif self.native_parent_item_id is not None:
            raise ValueError("native-turn item must not claim a second native parent")
        _require_aware("bound_at", self.bound_at)


def _require_binding_shape(kind: CodexBindingKind, parent_id: str | None, label: str) -> None:
    if kind is CodexBindingKind.PHASE and parent_id is not None:
        raise ValueError(f"phase {label} binding cannot name a native parent")
    if kind is CodexBindingKind.NATIVE_OBSERVATION and parent_id is None:
        raise ValueError(f"native observation {label} binding requires its parent id")


def _require_descendant_kind(
    parent: CodexBindingKind, child: CodexBindingKind, label: str
) -> None:
    if parent is CodexBindingKind.NATIVE_OBSERVATION and child is not parent:
        raise ValueError(f"native observation parent cannot produce a phase {label} binding")
