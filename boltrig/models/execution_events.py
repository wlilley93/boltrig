"""Normalized execution events and transactional-outbox records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import cast

from .base import utcnow
from .execution_ledger import ExecutionAggregateKind
from .execution_scope import (
    MAX_COLLECTION_ITEMS,
    CanonicalPayload,
    EngineOwner,
    ExecutionScopeRef,
    JsonValue,
    _require_aware,
    _require_exact_enum,
    _require_exact_type,
    _require_identifier,
    _require_positive,
    _require_sha256,
)

MAX_OUTBOX_ATTEMPTS = 25


class ExecutionEventKind(str, Enum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    CLAIMED = "claimed"
    RELEASED = "released"
    RESULT_RECORDED = "result_recorded"
    VERIFICATION_RECORDED = "verification_recorded"
    APPROVAL_REQUESTED = "approval_requested"
    RUNTIME_OBSERVED = "runtime_observed"
    INTERRUPTED = "interrupted"


class OutboxStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class EventCount:
    name: str
    value: int

    def __post_init__(self) -> None:
        _require_identifier("event count name", self.name)
        _require_positive("event count value", self.value, allow_zero=True)


@dataclass(frozen=True)
class NormalizedExecutionMetadata:
    """Typed bounded metadata; raw App Server frames are never ledger payloads."""

    runtime_event: str | None = None
    status: str | None = None
    item_type: str | None = None
    message_code: str | None = None
    detail_digest: str | None = None
    references: tuple[str, ...] = ()
    counts: tuple[EventCount, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("runtime_event", self.runtime_event),
            ("status", self.status),
            ("item_type", self.item_type),
            ("message_code", self.message_code),
        ):
            if value is not None:
                _require_identifier(label, value)
        if self.detail_digest is not None:
            _require_sha256("detail_digest", self.detail_digest)
        _require_identifier_tuple("references", self.references)
        if len(self.references) > MAX_COLLECTION_ITEMS:
            raise ValueError("references exceed the collection limit")
        if type(self.counts) is not tuple:
            raise TypeError("counts must be an immutable tuple")
        if any(type(item) is not EventCount for item in self.counts):
            raise TypeError("counts must contain exact EventCount values")
        if len(self.counts) > MAX_COLLECTION_ITEMS:
            raise ValueError("counts exceed the collection limit")
        count_names = tuple(item.name for item in self.counts)
        if len(set(count_names)) != len(count_names):
            raise ValueError("event count names must be unique")


@dataclass(frozen=True)
class CanonicalEventPayload(CanonicalPayload):
    """Canonical bytes restricted to the normalized metadata schema."""

    def __post_init__(self) -> None:
        super().__post_init__()
        document = self.to_mapping()
        allowed = {
            "counts",
            "detail_digest",
            "item_type",
            "message_code",
            "references",
            "runtime_event",
            "status",
        }
        if not set(document).issubset(allowed):
            raise ValueError("event payload contains non-normalized fields")
        _validate_event_document(document)

    @classmethod
    def from_metadata(cls, metadata: NormalizedExecutionMetadata) -> CanonicalEventPayload:
        _require_exact_type("metadata", metadata, NormalizedExecutionMetadata)
        document: dict[str, JsonValue] = {}
        for key in ("runtime_event", "status", "item_type", "message_code", "detail_digest"):
            value = getattr(metadata, key)
            if value is not None:
                document[key] = cast(str, value)
        if metadata.references:
            document["references"] = list(metadata.references)
        if metadata.counts:
            document["counts"] = [
                {"name": item.name, "value": item.value} for item in metadata.counts
            ]
        return cls._from_mapping(document)


@dataclass(frozen=True)
class PendingExecutionEvent:
    """Validated event before the store assigns its canonical stream sequence."""

    id: str
    scope: ExecutionScopeRef
    aggregate_kind: ExecutionAggregateKind
    aggregate_id: str
    kind: ExecutionEventKind
    ingestion_idempotency_key: str
    correlation_id: str
    payload: CanonicalEventPayload
    source_owner: EngineOwner
    causation_command_id: str | None = None
    source_sequence: int | None = None
    occurred_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_identifier("event id", self.id)
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_exact_enum("aggregate kind", self.aggregate_kind, ExecutionAggregateKind)
        _require_identifier("aggregate_id", self.aggregate_id)
        _require_exact_enum("event kind", self.kind, ExecutionEventKind)
        _require_identifier("ingestion_idempotency_key", self.ingestion_idempotency_key)
        _require_identifier("correlation_id", self.correlation_id)
        _require_exact_type("payload", self.payload, CanonicalEventPayload)
        _require_exact_enum("source_owner", self.source_owner, EngineOwner)
        if self.causation_command_id is not None:
            _require_identifier("causation_command_id", self.causation_command_id)
        if self.source_sequence is not None:
            _require_positive("source_sequence", self.source_sequence, allow_zero=True)
        _require_aware("occurred_at", self.occurred_at)


@dataclass(frozen=True)
class RecordedExecutionEvent:
    scope: ExecutionScopeRef
    pending: PendingExecutionEvent
    sequence: int
    recorded_at: datetime = field(default_factory=utcnow)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_exact_type("pending", self.pending, PendingExecutionEvent)
        if self.scope != self.pending.scope:
            raise ValueError("recorded event and pending event scopes differ")
        _require_positive("sequence", self.sequence)
        recorded = _require_aware("recorded_at", self.recorded_at)
        if recorded < self.pending.occurred_at:
            raise ValueError("recorded_at cannot precede occurred_at")


@dataclass(frozen=True)
class ExecutionOutboxRecord:
    scope: ExecutionScopeRef
    id: str
    event: RecordedExecutionEvent
    destination: str
    delivery_key: str
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    created_at: datetime = field(default_factory=utcnow)
    available_at: datetime = field(default_factory=utcnow)
    claim_owner: str | None = None
    claimed_at: datetime | None = None
    claim_expires_at: datetime | None = None
    delivered_at: datetime | None = None
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_exact_type("scope", self.scope, ExecutionScopeRef)
        _require_identifier("outbox id", self.id)
        _require_exact_type("event", self.event, RecordedExecutionEvent)
        if self.scope != self.event.scope:
            raise ValueError("outbox and event scopes differ")
        _require_identifier("destination", self.destination)
        _require_identifier("delivery_key", self.delivery_key)
        if self.delivery_key == self.event.pending.ingestion_idempotency_key:
            raise ValueError("delivery key must be distinct from ingestion idempotency")
        _require_exact_enum("status", self.status, OutboxStatus)
        _require_positive("attempts", self.attempts, allow_zero=True)
        if self.attempts > MAX_OUTBOX_ATTEMPTS:
            raise ValueError("outbox attempts exceed the delivery limit")
        self._validate_times_and_claim()

    def _validate_times_and_claim(self) -> None:
        created = _require_aware("created_at", self.created_at)
        available = _require_aware("available_at", self.available_at)
        if created < self.event.recorded_at or available < created:
            raise ValueError("outbox creation/availability timeline is invalid")
        claim_values = (self.claim_owner, self.claimed_at, self.claim_expires_at)
        has_claim = all(value is not None for value in claim_values)
        if any(value is not None for value in claim_values) and not has_claim:
            raise ValueError("outbox claim owner, claimed_at, and expiry are atomic")
        claimed: datetime | None = None
        expires: datetime | None = None
        if has_claim:
            _require_identifier("claim_owner", self.claim_owner)
            claimed = _require_aware("claimed_at", self.claimed_at)
            expires = _require_aware("claim_expires_at", self.claim_expires_at)
            if claimed < available or expires <= claimed:
                raise ValueError("outbox claim timeline is invalid")
        if self.status is OutboxStatus.PENDING and has_claim:
            raise ValueError("pending outbox record cannot retain a claim")
        if self.status is not OutboxStatus.PENDING and (not has_claim or self.attempts < 1):
            raise ValueError("active or terminal delivery requires a claimed attempt")
        if self.delivered_at is not None:
            delivered = _require_aware("delivered_at", self.delivered_at)
            if claimed is None or expires is None or not (claimed <= delivered <= expires):
                raise ValueError("outbox delivery must occur inside its claim lease")
        if self.status is OutboxStatus.DELIVERED and self.delivered_at is None:
            raise ValueError("delivered outbox record must have delivered_at")
        if self.status is not OutboxStatus.DELIVERED and self.delivered_at is not None:
            raise ValueError("undelivered outbox record cannot have delivered_at")


def _require_identifier_tuple(label: str, values: object) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{label} must be an immutable tuple")
    normalized = tuple(_require_identifier(label, value) for value in cast(tuple[object, ...], values))
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must be unique")


def _validate_event_document(document: dict[str, JsonValue]) -> None:
    for key in ("runtime_event", "status", "item_type", "message_code"):
        value = document.get(key)
        if value is not None:
            _require_identifier(key, value)
    detail = document.get("detail_digest")
    if detail is not None:
        _require_sha256("detail_digest", detail)
    references = document.get("references", [])
    if type(references) is not list:
        raise TypeError("event references must be an exact list in canonical bytes")
    _require_identifier_tuple("references", tuple(cast(list[object], references)))
    counts = document.get("counts", [])
    if type(counts) is not list:
        raise TypeError("event counts must be an exact list in canonical bytes")
    names: list[str] = []
    for count_entry in cast(list[object], counts):
        if type(count_entry) is not dict or set(cast(dict[object, object], count_entry)) != {"name", "value"}:
            raise TypeError("event count entries must contain only name and value")
        item = cast(dict[str, object], count_entry)
        names.append(_require_identifier("event count name", item["name"]))
        _require_positive("event count value", item["value"], allow_zero=True)
    if len(set(names)) != len(names):
        raise ValueError("event count names must be unique")
