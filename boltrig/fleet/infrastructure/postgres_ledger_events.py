"""Row<->object mapping for events, outbox, identities, and Codex bindings.

The six canonical records live in ``postgres_ledger_records``. This module covers
the remaining durable shapes the execution ledger persists: the normalized event
stream, the transactional outbox, workspace runtime identities, and the Codex
thread/turn/item binding tree.

Every field round-trips through a column of its own (0031). The outbox keeps both
the requested ``available_at`` an ``OutboxIntent`` submitted and the materialized
``max(requested, now)`` the delivery loop reads, so the submitted append can be
reconstructed exactly for replay comparison. ``runtime_identities.profile`` is
unused: ``RuntimeIdentity`` has no profile field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boltrig.fleet.infrastructure.postgres_ledger_codec import decode, encode
from boltrig.fleet.infrastructure.postgres_ledger_records import scope_of
from boltrig.fleet.ports.execution_ledger import OutboxIntent
from boltrig.models import (
    CanonicalEventPayload,
    CodexBindingKind,
    CodexItemBinding,
    CodexThreadBinding,
    CodexTurnBinding,
    EngineOwner,
    ExecutionAggregateKind,
    ExecutionEventKind,
    ExecutionOutboxRecord,
    ExecutionScopeRef,
    OrganisationUserRef,
    OutboxStatus,
    PendingExecutionEvent,
    RecordedExecutionEvent,
    RuntimeIdentity,
    RuntimeIdentityStatus,
    WorkspaceScopeRef,
)

Row = Any

EVENT_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "sequence", "event_id",
    "aggregate_kind", "aggregate_id", "kind", "idempotency_key", "correlation_id",
    "causation_command_id", "source_owner", "source_sequence", "payload",
    "occurred_at", "recorded_at",
]
OUTBOX_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "id", "event_sequence", "destination",
    "delivery_key", "status", "attempts", "claim_owner", "claimed_at",
    "claim_expires_at", "available_at", "requested_available_at", "intent_ordinal",
    "delivered_at", "created_at",
]
IDENTITY_COLS = [
    "tenant_id", "workspace_id", "id", "principal_user_id", "status", "generation",
    "created_at", "updated_at", "revoked_at",
]
THREAD_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "phase_id", "assignment_id",
    "runtime_identity_id", "kind", "thread_id", "native_parent_thread_id", "bound_at",
]
TURN_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "thread_id", "kind", "turn_id",
    "native_parent_turn_id", "bound_at",
]
ITEM_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "thread_id", "turn_id", "kind",
    "item_id", "native_parent_item_id", "bound_at",
]


def event_values(event: RecordedExecutionEvent) -> tuple[Any, ...]:
    scope = event.scope
    pending = event.pending
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id, event.sequence,
        pending.id, pending.aggregate_kind.value, pending.aggregate_id,
        pending.kind.value, pending.ingestion_idempotency_key, pending.correlation_id,
        pending.causation_command_id, pending.source_owner.value,
        pending.source_sequence, encode(pending.payload), pending.occurred_at,
        event.recorded_at,
    )


def row_to_event(row: Row) -> RecordedExecutionEvent:
    scope = scope_of(row)
    pending = PendingExecutionEvent(
        row["event_id"], scope, ExecutionAggregateKind(row["aggregate_kind"]),
        row["aggregate_id"], ExecutionEventKind(row["kind"]), row["idempotency_key"],
        row["correlation_id"], decode(CanonicalEventPayload, row["payload"]),
        EngineOwner(row["source_owner"]), row["causation_command_id"],
        row["source_sequence"], row["occurred_at"],
    )
    return RecordedExecutionEvent(scope, pending, row["sequence"], row["recorded_at"])


def outbox_values(
    record: ExecutionOutboxRecord, intent: OutboxIntent, ordinal: int
) -> tuple[Any, ...]:
    """Persist the materialized record together with the intent that requested it.

    ``available_at`` is the materialized ``max(requested, now)`` the delivery loop
    reads; ``requested_available_at`` and ``intent_ordinal`` preserve exactly what
    the caller submitted, so the append can be rebuilt for replay comparison.
    """

    scope = record.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id, record.id,
        record.event.sequence, record.destination, record.delivery_key,
        record.status.value, record.attempts, record.claim_owner, record.claimed_at,
        record.claim_expires_at, record.available_at, intent.available_at, ordinal,
        record.delivered_at, record.created_at,
    )


def row_to_outbox(row: Row, event: RecordedExecutionEvent) -> ExecutionOutboxRecord:
    return ExecutionOutboxRecord(
        scope_of(row), row["id"], event, row["destination"], row["delivery_key"],
        OutboxStatus(row["status"]), row["attempts"], row["created_at"],
        row["available_at"], row["claim_owner"], row["claimed_at"],
        row["claim_expires_at"], row["delivered_at"],
    )


def row_to_intent(row: Row) -> OutboxIntent:
    """Rebuild the submitted intent verbatim from its own columns."""

    return OutboxIntent(
        row["id"], row["destination"], row["delivery_key"], row["requested_available_at"]
    )


def identity_values(identity: RuntimeIdentity, *, now: datetime) -> tuple[Any, ...]:
    workspace = identity.workspace
    return (
        workspace.tenant_id, workspace.workspace_id, identity.id,
        identity.principal.user_id, identity.status.value, identity.generation,
        identity.created_at, now, identity.revoked_at,
    )


def row_to_identity(row: Row) -> RuntimeIdentity:
    workspace = WorkspaceScopeRef(row["tenant_id"], row["workspace_id"])
    return RuntimeIdentity(
        row["id"], OrganisationUserRef(workspace.tenant_id, row["principal_user_id"]),
        workspace, row["generation"], RuntimeIdentityStatus(row["status"]),
        row["created_at"], row["revoked_at"],
    )


def thread_values(binding: CodexThreadBinding) -> tuple[Any, ...]:
    scope = binding.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id, binding.phase_id,
        binding.assignment_id, binding.runtime_identity_id, binding.kind.value,
        binding.thread_id, binding.native_parent_thread_id, binding.bound_at,
    )


def row_to_thread(row: Row) -> CodexThreadBinding:
    return CodexThreadBinding(
        scope_of(row), row["phase_id"], row["assignment_id"],
        row["runtime_identity_id"], CodexBindingKind(row["kind"]), row["thread_id"],
        row["native_parent_thread_id"], row["bound_at"],
    )


def turn_values(binding: CodexTurnBinding) -> tuple[Any, ...]:
    scope = binding.scope
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id,
        binding.thread.thread_id, binding.kind.value, binding.turn_id,
        binding.native_parent_turn_id, binding.bound_at,
    )


def row_to_turn(row: Row, thread: CodexThreadBinding) -> CodexTurnBinding:
    return CodexTurnBinding(
        scope_of(row), thread, CodexBindingKind(row["kind"]), row["turn_id"],
        row["native_parent_turn_id"], row["bound_at"],
    )


def item_values(binding: CodexItemBinding) -> tuple[Any, ...]:
    scope = binding.scope
    turn = binding.turn
    return (
        scope.tenant_id, scope.workspace_id, scope.root_run_id,
        turn.thread.thread_id, turn.turn_id, binding.kind.value, binding.item_id,
        binding.native_parent_item_id, binding.bound_at,
    )


def row_to_item(row: Row, turn: CodexTurnBinding) -> CodexItemBinding:
    return CodexItemBinding(
        scope_of(row), turn, CodexBindingKind(row["kind"]), row["item_id"],
        row["native_parent_item_id"], row["bound_at"],
    )


def scope_ref(tenant_id: str, workspace_id: str, root_run_id: str) -> ExecutionScopeRef:
    return ExecutionScopeRef(WorkspaceScopeRef(tenant_id, workspace_id), root_run_id)


__all__ = [
    "EVENT_COLS", "IDENTITY_COLS", "ITEM_COLS", "OUTBOX_COLS", "THREAD_COLS",
    "TURN_COLS", "event_values", "identity_values", "item_values", "outbox_values",
    "row_to_event", "row_to_identity", "row_to_intent", "row_to_item", "row_to_outbox",
    "row_to_thread", "row_to_turn", "scope_ref", "thread_values", "turn_values",
]
