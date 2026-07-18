"""Server-digested, idempotent commands for execution-ledger mutations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .base import utcnow
from .execution_ledger import ExecutionAggregateKind
from .execution_scope import (
    CanonicalPayload,
    ExecutionScopeRef,
    JsonScalar,
    OrganisationUserRef,
    _require_aware,
    _require_exact_enum,
    _require_exact_type,
    _require_identifier,
    _require_positive,
)


class LedgerCommandKind(str, Enum):
    CREATE_ROOT = "create_root"
    CREATE_PHASE = "create_phase"
    ENQUEUE_WORK = "enqueue_work"
    ASSIGN_WORK = "assign_work"
    REPLACE_ASSIGNMENT = "replace_assignment"
    RECORD_RESULT = "record_result"
    RECORD_VERIFICATION = "record_verification"
    TRANSITION_STATUS = "transition_status"
    CANCEL = "cancel"


class CommandReplayDecision(str, Enum):
    NEW = "new"
    REPLAY = "replay"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class CommandParameter:
    name: str
    value: JsonScalar

    def __post_init__(self) -> None:
        _require_identifier("command parameter name", self.name)
        if self.value is not None and type(self.value) not in {str, int, float, bool}:
            raise TypeError("command parameter must be an exact JSON scalar")


@dataclass(frozen=True)
class CanonicalCommandPayload(CanonicalPayload):
    """Bounded scalar command parameters; no untyped request body is retained."""

    def __post_init__(self) -> None:
        super().__post_init__()
        allowed = {str, int, float, bool, type(None)}
        if any(type(value) not in allowed for value in self.to_mapping().values()):
            raise TypeError("command payload values must be exact JSON scalars")

    @classmethod
    def from_parameters(cls, parameters: tuple[CommandParameter, ...]) -> CanonicalCommandPayload:
        if type(parameters) is not tuple:
            raise TypeError("command parameters must be an immutable tuple")
        if any(type(parameter) is not CommandParameter for parameter in parameters):
            raise TypeError("command parameters must contain exact CommandParameter values")
        if len({parameter.name for parameter in parameters}) != len(parameters):
            raise ValueError("command parameter names must be unique")
        return cls._from_mapping({parameter.name: parameter.value for parameter in parameters})


@dataclass(frozen=True)
class LedgerCommand:
    """The request digest is computed from all policy-relevant routing fields."""

    id: str
    kind: LedgerCommandKind
    scope: ExecutionScopeRef
    aggregate_kind: ExecutionAggregateKind
    aggregate_id: str
    expected_version: int
    payload: CanonicalCommandPayload
    issued_by: OrganisationUserRef
    issued_at: datetime = field(default_factory=utcnow)
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_identifier("command id", self.id)
        _require_exact_enum("command kind", self.kind, LedgerCommandKind)
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_exact_enum("aggregate kind", self.aggregate_kind, ExecutionAggregateKind)
        _require_identifier("aggregate id", self.aggregate_id)
        _require_positive("expected_version", self.expected_version, allow_zero=True)
        _require_exact_type("payload", self.payload, CanonicalCommandPayload)
        _require_exact_type("issued_by", self.issued_by, OrganisationUserRef)
        if self.issued_by.tenant_id != self.scope.tenant_id:
            raise ValueError("command principal and execution scope tenants differ")
        _require_aware("issued_at", self.issued_at)
        request = {
            "aggregate_id": self.aggregate_id,
            "aggregate_kind": self.aggregate_kind.value,
            "command_kind": self.kind.value,
            "expected_version": self.expected_version,
            "issued_by_user_id": self.issued_by.user_id,
            "payload": self.payload.to_mapping(),
            "root_run_id": self.scope.root_run_id,
            "tenant_id": self.scope.tenant_id,
            "workspace_id": self.scope.workspace_id,
        }
        encoded = json.dumps(request, separators=(",", ":"), sort_keys=True).encode("utf-8")
        digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        object.__setattr__(self, "request_digest", digest)

    @classmethod
    def create(
        cls,
        *,
        id: str,
        kind: LedgerCommandKind,
        scope: ExecutionScopeRef,
        aggregate_kind: ExecutionAggregateKind,
        aggregate_id: str,
        expected_version: int,
        parameters: tuple[CommandParameter, ...],
        issued_by: OrganisationUserRef,
        issued_at: datetime | None = None,
    ) -> LedgerCommand:
        return cls(
            id=id,
            kind=kind,
            scope=scope,
            aggregate_kind=aggregate_kind,
            aggregate_id=aggregate_id,
            expected_version=expected_version,
            payload=CanonicalCommandPayload.from_parameters(parameters),
            issued_by=issued_by,
            issued_at=issued_at or utcnow(),
        )


def classify_command_replay(
    incoming: LedgerCommand, stored: LedgerCommand | None
) -> CommandReplayDecision:
    _require_exact_type("incoming", incoming, LedgerCommand)
    if stored is None:
        return CommandReplayDecision.NEW
    _require_exact_type("stored", stored, LedgerCommand)
    if incoming.id != stored.id:
        raise ValueError("replay comparison requires the same command id")
    if incoming.request_digest == stored.request_digest:
        return CommandReplayDecision.REPLAY
    return CommandReplayDecision.CONFLICT
