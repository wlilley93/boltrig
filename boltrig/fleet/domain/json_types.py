"""JSON-compatible values used at orchestration boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONMapping: TypeAlias = Mapping[str, JSONValue]


@dataclass(frozen=True)
class CanonicalJSON:
    """Immutable, finite, canonical JSON copied at a trust boundary."""

    _encoded: bytes = field(repr=False)

    def __post_init__(self) -> None:
        try:
            value: JSONValue = json.loads(self._encoded)
            canonical = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("encoded value is not canonical JSON") from exc
        if canonical != self._encoded:
            raise ValueError("encoded value is not canonical JSON")

    @classmethod
    def from_value(cls, value: JSONValue) -> CanonicalJSON:
        try:
            encoded = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("value is not canonical JSON") from exc
        return cls(encoded)

    @classmethod
    def from_mapping(cls, value: JSONMapping) -> CanonicalJSON:
        return cls.from_value(dict(value))

    @classmethod
    def empty_mapping(cls) -> CanonicalJSON:
        return cls(b"{}")

    def to_value(self) -> JSONValue:
        value: JSONValue = json.loads(self._encoded)
        return value

    def to_mapping(self) -> dict[str, JSONValue]:
        value = self.to_value()
        if not isinstance(value, dict):
            raise ValueError("canonical JSON value is not an object")
        return value
