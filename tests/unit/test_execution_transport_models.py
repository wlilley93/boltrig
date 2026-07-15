from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone

import pytest

from boltrig.models import (
    CanonicalEventPayload,
    CodexBindingKind,
    CodexItemBinding,
    CodexThreadBinding,
    CodexTurnBinding,
    CommandParameter,
    CommandReplayDecision,
    EngineOwner,
    EventCount,
    ExecutionAggregateKind,
    ExecutionEventKind,
    ExecutionOutboxRecord,
    ExecutionScopeRef,
    LedgerCommand,
    LedgerCommandKind,
    NormalizedExecutionMetadata,
    OrganisationUserRef,
    OutboxStatus,
    PendingExecutionEvent,
    RecordedExecutionEvent,
    WorkspaceScopeRef,
    classify_command_replay,
)
from boltrig.models.execution_events import MAX_OUTBOX_ATTEMPTS
from boltrig.models.execution_scope import (
    MAX_CANONICAL_BYTES,
    MAX_COLLECTION_ITEMS,
    MAX_JSON_STRING_CHARS,
    MAX_SIGNED_BIGINT,
)

NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


def _scope(
    tenant: str = "org-1", workspace: str = "workspace-1", run: str = "run-1"
) -> ExecutionScopeRef:
    return ExecutionScopeRef(WorkspaceScopeRef(tenant, workspace), run)


def _principal(tenant: str = "org-1", user: str = "user-1") -> OrganisationUserRef:
    return OrganisationUserRef(tenant, user)


def _command(
    *,
    id: str = "command-1",
    kind: LedgerCommandKind = LedgerCommandKind.ASSIGN_WORK,
    scope: ExecutionScopeRef | None = None,
    aggregate_kind: ExecutionAggregateKind = ExecutionAggregateKind.WORK_ITEM,
    aggregate_id: str = "work-1",
    expected_version: int = 3,
    value: str = "worker-1",
    user: str = "user-1",
) -> LedgerCommand:
    selected = scope or _scope()
    return LedgerCommand.create(
        id=id,
        kind=kind,
        scope=selected,
        aggregate_kind=aggregate_kind,
        aggregate_id=aggregate_id,
        expected_version=expected_version,
        parameters=(CommandParameter("worker", value),),
        issued_by=_principal(selected.tenant_id, user),
        issued_at=NOW,
    )


def _recorded_event(scope: ExecutionScopeRef | None = None) -> RecordedExecutionEvent:
    selected = scope or _scope()
    pending = PendingExecutionEvent(
        "event-1",
        selected,
        ExecutionAggregateKind.ASSIGNMENT,
        "assignment-1",
        ExecutionEventKind.RUNTIME_OBSERVED,
        "ingest-thread-1-19",
        "run-1",
        CanonicalEventPayload.from_metadata(
            NormalizedExecutionMetadata(runtime_event="item.completed")
        ),
        EngineOwner.CODEX,
        source_sequence=19,
        occurred_at=NOW,
    )
    return RecordedExecutionEvent(selected, pending, 7, NOW + timedelta(seconds=1))


@pytest.mark.invariant("SEC-154")
def test_command_digest_is_server_computed_and_models_replay_vs_conflict() -> None:
    original = _command()
    replay = _command()
    changed = (
        _command(kind=LedgerCommandKind.CANCEL),
        _command(scope=_scope(tenant="org-2")),
        _command(scope=_scope(workspace="workspace-2")),
        _command(scope=_scope(run="run-2")),
        _command(aggregate_kind=ExecutionAggregateKind.ASSIGNMENT),
        _command(aggregate_id="work-2"),
        _command(expected_version=4),
        _command(value="worker-2"),
        _command(user="user-2"),
    )

    assert original.request_digest.startswith("sha256:")
    assert classify_command_replay(original, None) is CommandReplayDecision.NEW
    assert classify_command_replay(original, replay) is CommandReplayDecision.REPLAY
    assert all(item.request_digest != original.request_digest for item in changed)
    assert classify_command_replay(original, changed[0]) is CommandReplayDecision.CONFLICT
    with pytest.raises(TypeError, match="unexpected keyword"):
        LedgerCommand.create(request_digest="client-hash")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="sensitive key"):
        LedgerCommand.create(
            id="secret",
            kind=LedgerCommandKind.ASSIGN_WORK,
            scope=_scope(),
            aggregate_kind=ExecutionAggregateKind.WORK_ITEM,
            aggregate_id="work-1",
            expected_version=1,
            parameters=(CommandParameter("worker-api-key", "forbidden"),),
            issued_by=_principal(),
            issued_at=NOW,
        )


@pytest.mark.invariant("SEC-153")
def test_codex_bindings_are_scoped_boltrig_owned_and_explicitly_observational() -> None:
    scope = _scope()
    phase_thread = CodexThreadBinding(
        scope, "phase-1", "assignment-1", "runtime-user-1",
        CodexBindingKind.PHASE, "thread-root", bound_at=NOW,
    )
    child_thread = CodexThreadBinding(
        scope, "phase-1", "assignment-1", "runtime-user-1",
        CodexBindingKind.NATIVE_OBSERVATION, "thread-child", "thread-root", NOW,
    )
    child_turn = CodexTurnBinding(
        scope, child_thread, CodexBindingKind.NATIVE_OBSERVATION,
        "turn-child", bound_at=NOW,
    )
    child_item = CodexItemBinding(
        scope, child_turn, CodexBindingKind.NATIVE_OBSERVATION,
        "item-child", bound_at=NOW,
    )

    assert phase_thread.engine_owner is EngineOwner.BOLTRIG
    assert child_item.runtime_source_owner is EngineOwner.CODEX
    assert child_item.kind is CodexBindingKind.NATIVE_OBSERVATION
    assert not hasattr(child_item, "may_mutate_ledger")
    with pytest.raises(ValueError, match="requires its parent"):
        CodexThreadBinding(
            scope, "phase-1", "assignment-1", "runtime-user-1",
            CodexBindingKind.NATIVE_OBSERVATION, "untrusted-child", bound_at=NOW,
        )
    with pytest.raises(ValueError, match="scopes differ"):
        CodexTurnBinding(
            _scope(workspace="workspace-2"), phase_thread,
            CodexBindingKind.PHASE, "turn-1", bound_at=NOW,
        )


@pytest.mark.invariant("SEC-154")
def test_event_payload_is_exact_bounded_sensitive_free_and_normalized() -> None:
    payload = CanonicalEventPayload.from_metadata(
        NormalizedExecutionMetadata(
            runtime_event="item.completed",
            status="completed",
            references=("evidence-1",),
            counts=(EventCount("tokens", 42),),
        )
    )
    assert payload.to_mapping()["runtime_event"] == "item.completed"
    assert type(payload.encoded) is bytes
    source = bytes(bytearray(b'{"status":"copied"}'))
    copied = CanonicalEventPayload(source)
    assert copied.encoded == source and copied._encoded is not source
    with pytest.raises(TypeError, match="exact immutable bytes"):
        CanonicalEventPayload(bytearray(b"{}"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sensitive key"):
        CanonicalEventPayload(b'{"access-token":"forbidden"}')
    for key in ("bearer", "jwt", "OAuthToken", "sessionToken"):
        with pytest.raises(ValueError, match="sensitive key"):
            CanonicalEventPayload._from_mapping({key: "forbidden"})
    with pytest.raises(ValueError, match="non-normalized"):
        CanonicalEventPayload(b'{"jsonrpc":"2.0","method":"turn/started"}')
    too_many = b'{"references":[' + b','.join(
        b'"id"' for _ in range(MAX_COLLECTION_ITEMS + 1)
    ) + b"]}"
    with pytest.raises(ValueError, match="collection is too large"):
        CanonicalEventPayload(too_many)
    long_string = b'{"status":"' + b"x" * (MAX_JSON_STRING_CHARS + 1) + b'"}'
    with pytest.raises(ValueError, match="string is too long"):
        CanonicalEventPayload(long_string)
    oversized = b'{"references":[' + b','.join(b'"' + b"x" * 300 + b'"' for _ in range(128)) + b"]}"
    assert len(oversized) > MAX_CANONICAL_BYTES
    with pytest.raises(ValueError, match="byte limit"):
        CanonicalEventPayload(oversized)
    nested = b'{"status":{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":1}}}}}}}}}'
    with pytest.raises(ValueError, match="nesting depth"):
        CanonicalEventPayload(nested)
    with pytest.raises(ValueError, match="collection limit"):
        NormalizedExecutionMetadata(references=tuple(f"ref-{index}" for index in range(129)))


@pytest.mark.invariant("SEC-154")
def test_durable_values_reject_controls_and_signed_bigint_overflow() -> None:
    for value in ("user\x00name", "user\x1fname", "user\x7fname", "user\x85name"):
        with pytest.raises(ValueError, match="bounded"):
            OrganisationUserRef("org-1", value)
    with pytest.raises(ValueError, match="signed BIGINT"):
        EventCount("tokens", MAX_SIGNED_BIGINT + 1)


@pytest.mark.invariant("FR-RUN-20")
def test_pending_recorded_event_and_outbox_keep_scopes_and_keys_distinct() -> None:
    scope = _scope()
    recorded = _recorded_event(scope)
    created = NOW + timedelta(seconds=2)
    outbox = ExecutionOutboxRecord(
        scope, "outbox-1", recorded, "execution.events", "delivery-event-1",
        created_at=created, available_at=created,
    )

    assert "sequence" not in {item.name for item in fields(PendingExecutionEvent)}
    assert recorded.sequence == 7
    assert outbox.delivery_key != recorded.pending.ingestion_idempotency_key
    assert outbox.scope.tenant_id == "org-1"
    with pytest.raises(ValueError, match="distinct"):
        ExecutionOutboxRecord(
            scope, "outbox-2", recorded, "execution.events",
            recorded.pending.ingestion_idempotency_key,
            created_at=created, available_at=created,
        )
    with pytest.raises(ValueError, match="scopes differ"):
        RecordedExecutionEvent(
            _scope(workspace="workspace-2"), recorded.pending, 8,
            NOW + timedelta(seconds=1),
        )


def test_outbox_claim_lease_attempt_and_timeline_invariants() -> None:
    scope = _scope()
    recorded = _recorded_event(scope)
    created = NOW + timedelta(seconds=2)
    claimed = created + timedelta(seconds=1)
    expires = claimed + timedelta(minutes=1)
    outbox = ExecutionOutboxRecord(
        scope, "outbox-1", recorded, "execution.events", "delivery-1",
        OutboxStatus.DELIVERED, 1, created, created, "publisher-1",
        claimed, expires, claimed + timedelta(seconds=5),
    )
    assert outbox.claim_owner == "publisher-1"
    with pytest.raises(ValueError, match="atomic"):
        ExecutionOutboxRecord(
            scope, "outbox-2", recorded, "execution.events", "delivery-2",
            OutboxStatus.IN_FLIGHT, 1, created, created, "publisher-1",
        )
    with pytest.raises(ValueError, match="claimed attempt"):
        ExecutionOutboxRecord(
            scope, "outbox-3", recorded, "execution.events", "delivery-3",
            OutboxStatus.IN_FLIGHT, 0, created, created,
        )
    with pytest.raises(ValueError, match="delivery limit"):
        ExecutionOutboxRecord(
            scope, "outbox-4", recorded, "execution.events", "delivery-4",
            attempts=MAX_OUTBOX_ATTEMPTS + 1, created_at=created, available_at=created,
        )
    with pytest.raises(ValueError, match="inside its claim lease"):
        ExecutionOutboxRecord(
            scope, "outbox-5", recorded, "execution.events", "delivery-5",
            OutboxStatus.DELIVERED, 1, created, created, "publisher-1",
            claimed, expires, expires + timedelta(seconds=1),
        )
