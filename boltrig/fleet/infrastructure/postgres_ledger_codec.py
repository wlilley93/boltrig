"""Generic domain<->JSON codec for the durable execution-ledger adapter.

The canonical execution records are frozen dataclasses built from nested value
objects, enums, timezone-aware datetimes, tuples, and ``CanonicalPayload`` byte
blobs. ``encode`` lowers any such object to JSON-native Python; ``decode``
reconstructs it exactly from the resolved field types, so ``decode(cls,
encode(obj)) == obj`` for every ledger value. The codec drives both the JSONB
value-object columns and the whole ``AtomicLedgerWrite`` stored on each command
row (used for command replay/conflict classification).
"""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Union, get_args, get_origin, get_type_hints

from boltrig.fleet.ports.execution_ledger import (
    AtomicLedgerWrite,
    ExecutionLedgerRecord,
    OutboxIntent,
)
from boltrig.models import (
    ExecutionAssignment,
    ExecutionPhase,
    ExecutionResult,
    ExecutionRootRun,
    ExecutionVerification,
    ExecutionWorkItem,
    LedgerCommand,
    PendingExecutionEvent,
)
from boltrig.models.execution_scope import CanonicalPayload

_NONE = type(None)
_HINTS: dict[type, dict[str, Any]] = {}

_RECORD_BY_KIND: dict[str, type] = {
    "root_run": ExecutionRootRun,
    "phase": ExecutionPhase,
    "work_item": ExecutionWorkItem,
    "assignment": ExecutionAssignment,
    "result": ExecutionResult,
    "verification": ExecutionVerification,
}


def _hints(cls: type) -> dict[str, Any]:
    cached = _HINTS.get(cls)
    if cached is None:
        cached = get_type_hints(cls)
        _HINTS[cls] = cached
    return cached


def encode(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, CanonicalPayload):
        return value.to_mapping()
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    if is_dataclass(value):
        return {
            field.name: encode(getattr(value, field.name))
            for field in fields(value)
            if field.init
        }
    raise TypeError(f"cannot encode {type(value)!r}")


def decode(hint: Any, data: Any) -> Any:
    origin = get_origin(hint)
    if origin is Union or origin is types.UnionType:
        if data is None:
            return None
        concrete = [arg for arg in get_args(hint) if arg is not _NONE]
        return decode(concrete[0], data)
    if data is None:
        return None
    if origin in (tuple, list):
        item_type = get_args(hint)[0]
        return tuple(decode(item_type, item) for item in data)
    if isinstance(hint, type):
        if issubclass(hint, Enum):
            return hint(data)
        if issubclass(hint, datetime):
            return datetime.fromisoformat(data)
        if issubclass(hint, CanonicalPayload):
            return hint._from_mapping(data)
        if is_dataclass(hint):
            resolved = _hints(hint)
            return hint(
                **{
                    field.name: decode(resolved[field.name], data[field.name])
                    for field in fields(hint)
                    if field.init
                }
            )
    return data


def decode_seq(cls: type, data: Any) -> tuple[Any, ...]:
    return tuple(decode(cls, item) for item in (data or ()))


def write_to_json(write: AtomicLedgerWrite) -> Any:
    return encode(write)


def write_from_json(data: Any) -> AtomicLedgerWrite:
    record_cls = _RECORD_BY_KIND[data["command"]["aggregate_kind"]]
    command = decode(LedgerCommand, data["command"])
    record: ExecutionLedgerRecord = decode(record_cls, data["record"])
    event = decode(PendingExecutionEvent, data["event"])
    outbox = tuple(decode(OutboxIntent, item) for item in data["outbox"])
    return AtomicLedgerWrite(command, record, event, outbox)


__all__ = ["decode", "decode_seq", "encode", "write_from_json", "write_to_json"]
