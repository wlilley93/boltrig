"""Durable, executable projections for deterministically generated adapters.

The original OpenAPI document is intentionally not retained: it can contain
examples, security-scheme extensions and other author content the runtime does
not need.  Instead this module persists the bounded operation and schema
projection the deterministic generator actually executes.  That projection is
enough to reconstruct the same inert/reviewed adapter on any kernel replica.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlsplit

from boltrig.adapters.base import VerbSpec
from boltrig.adapters.generator import GeneratedAdapter, _Operation
from boltrig.adapters.http_base import RateLimitConfig

GENERATED_ADAPTER_KIND = "boltrig.generated-openapi.v1"
GENERATED_ADAPTER_MODULE = "boltrig.adapters.generator"
MAX_GENERATED_PROJECTION_BYTES = 1024 * 1024
MAX_GENERATED_OPERATIONS = 512
_NON_EXECUTABLE_SCHEMA_KEYS = frozenset(
    {"example", "examples", "default", "$comment"}
)
_SCHEMA_NAME_MAPS = frozenset(
    {"properties", "patternProperties", "dependentSchemas", "$defs", "definitions"}
)


def is_generated_adapter_record(record: Any) -> bool:
    return bool(
        getattr(record, "source", None) == "generated"
        and getattr(record, "module_ref", None) == GENERATED_ADAPTER_MODULE
    )


def _schema_projection(value: Any, *, names_are_keys: bool = False) -> Any:
    """Drop non-executable schema annotations that commonly carry examples."""
    if isinstance(value, list):
        return [_schema_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    projected: dict[str, Any] = {}
    for key, item in value.items():
        if not names_are_keys and (
            key in _NON_EXECUTABLE_SCHEMA_KEYS
            or str(key).lower().startswith("x-")
        ):
            continue
        projected[str(key)] = _schema_projection(
            item,
            names_are_keys=not names_are_keys and key in _SCHEMA_NAME_MAPS,
        )
    return projected


def _verb_projection(spec: VerbSpec) -> dict[str, Any]:
    return {
        "verb_id": spec.verb_id,
        "noun_id": spec.noun_id,
        "input_schema": _schema_projection(spec.input_schema),
        "output_schema": _schema_projection(spec.output_schema),
        "consequence": spec.consequence,
        "description": spec.description,
        "rate_limit": spec.rate_limit,
        "degraded_mode": spec.degraded_mode,
        "idempotency_mode": spec.idempotency_mode,
    }


def generated_adapter_projection(adapter: GeneratedAdapter) -> str:
    """Return the canonical private reconstruction projection for ``adapter``."""
    payload = {
        "kind": GENERATED_ADAPTER_KIND,
        "base_url": adapter.base_url,
        "spec_title": adapter._spec_title,
        "rate_limit": {
            "max": adapter.rate_limit.max,
            "per": adapter.rate_limit.per,
            "scope": adapter.rate_limit.scope,
        },
        "operations": [
            asdict(operation) for operation in adapter._operations.values()
        ],
        "verbs": [_verb_projection(spec) for spec in adapter.describe()],
    }
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "generated adapter projection is not canonical JSON"
        ) from exc
    if len(encoded.encode("utf-8")) > MAX_GENERATED_PROJECTION_BYTES:
        raise ValueError("generated adapter projection exceeds the durable limit")
    # Validate the exact encoded form before any durable row is created.  This
    # prevents accepting a generator extension this version cannot reconstruct.
    generated_adapter_from_record(
        SimpleNamespace(
            id=adapter.id,
            source="generated",
            module_ref=GENERATED_ADAPTER_MODULE,
            spec_ref=encoded,
            activated=False,
        )
    )
    return encoded


def _bounded_string(
    value: Any,
    label: str,
    *,
    maximum: int = 2048,
    allow_empty: bool = False,
    allow_newlines: bool = False,
) -> str:
    allowed_controls = {"\n", "\r", "\t"} if allow_newlines else set()
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not allow_empty and not value)
        or any(ord(char) < 32 and char not in allowed_controls for char in value)
    ):
        raise ValueError(f"generated adapter {label} is invalid")
    return value


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 128:
        raise ValueError(f"generated adapter {label} is invalid")
    return tuple(
        _bounded_string(item, label, maximum=256) for item in value
    )


def _operation(value: Any) -> _Operation:
    if not isinstance(value, dict):
        raise ValueError("generated adapter operation is invalid")
    method = value.get("method")
    consequence = value.get("consequence")
    pagination = value.get("pagination")
    if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
        raise ValueError("generated adapter operation method is invalid")
    if consequence not in {"low", "high"}:
        raise ValueError("generated adapter consequence is invalid")
    if pagination not in {None, "link", "offset"}:
        raise ValueError("generated adapter pagination is invalid")
    if type(value.get("has_body")) is not bool:
        raise ValueError("generated adapter body marker is invalid")
    return _Operation(
        verb_id=_bounded_string(value.get("verb_id"), "verb id", maximum=256),
        noun_id=_bounded_string(value.get("noun_id"), "noun id", maximum=256),
        method=method,
        path=_bounded_string(
            value.get("path"), "operation path", allow_empty=True
        ),
        path_params=_string_tuple(value.get("path_params"), "path parameters"),
        query_params=_string_tuple(value.get("query_params"), "query parameters"),
        header_params=_string_tuple(value.get("header_params"), "header parameters"),
        has_body=value["has_body"],
        consequence=consequence,
        pagination=pagination,
        items_key=_bounded_string(
            value.get("items_key"), "items key", maximum=256
        ),
        next_key=_bounded_string(
            value.get("next_key"), "next key", maximum=256
        ),
    )


def _optional_mapping(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"generated adapter {label} is invalid")
    return value


def _verb(value: Any) -> VerbSpec:
    if not isinstance(value, dict):
        raise ValueError("generated adapter verb is invalid")
    input_schema = value.get("input_schema")
    output_schema = value.get("output_schema")
    consequence = value.get("consequence")
    idempotency = value.get("idempotency_mode")
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
        raise ValueError("generated adapter verb schema is invalid")
    if consequence not in {"low", "high"}:
        raise ValueError("generated adapter verb consequence is invalid")
    if idempotency not in {"cacheable", "disabled"}:
        raise ValueError("generated adapter idempotency mode is invalid")
    return VerbSpec(
        verb_id=_bounded_string(value.get("verb_id"), "verb id", maximum=256),
        noun_id=_bounded_string(value.get("noun_id"), "noun id", maximum=256),
        input_schema=input_schema,
        output_schema=output_schema,
        consequence=consequence,
        description=_bounded_string(
            value.get("description"),
            "verb description",
            maximum=8192,
            allow_empty=True,
            allow_newlines=True,
        ),
        rate_limit=_optional_mapping(value.get("rate_limit"), "rate limit"),
        degraded_mode=_optional_mapping(
            value.get("degraded_mode"), "degraded mode"
        ),
        idempotency_mode=idempotency,
    )


def _rate_limit(value: Any) -> RateLimitConfig:
    if not isinstance(value, dict):
        raise ValueError("generated adapter rate limit is invalid")
    maximum = value.get("max")
    per = value.get("per")
    scope = value.get("scope")
    if (
        type(maximum) is not int
        or not 0 <= maximum <= 1_000_000
        or per not in {"second", "minute", "hour"}
        or scope not in {"tenant", "verb"}
    ):
        raise ValueError("generated adapter rate limit is invalid")
    return RateLimitConfig(max=maximum, per=per, scope=scope)


def generated_adapter_from_record(record: Any) -> GeneratedAdapter:
    """Rebuild one generated adapter from its bounded private store projection."""
    if not is_generated_adapter_record(record) or not isinstance(
        getattr(record, "spec_ref", None), str
    ):
        raise ValueError("adapter has no generated reconstruction source")
    raw = record.spec_ref
    if len(raw.encode("utf-8")) > MAX_GENERATED_PROJECTION_BYTES:
        raise ValueError("generated adapter projection exceeds the durable limit")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ValueError("generated adapter projection is invalid") from exc
    if not isinstance(value, dict) or value.get("kind") != GENERATED_ADAPTER_KIND:
        raise ValueError("generated adapter projection kind is invalid")
    operations_raw = value.get("operations")
    verbs_raw = value.get("verbs")
    rate_limit = _rate_limit(value.get("rate_limit"))
    if (
        not isinstance(operations_raw, list)
        or not isinstance(verbs_raw, list)
        or len(operations_raw) > MAX_GENERATED_OPERATIONS
        or len(verbs_raw) != len(operations_raw)
    ):
        raise ValueError("generated adapter projection shape is invalid")
    operations_list = [_operation(item) for item in operations_raw]
    verbs = [_verb(item) for item in verbs_raw]
    operations = {item.verb_id: item for item in operations_list}
    if (
        len(operations) != len(operations_list)
        or set(operations) != {item.verb_id for item in verbs}
        or any(
            operation.noun_id != spec.noun_id
            or operation.consequence != spec.consequence
            for operation, spec in zip(operations_list, verbs, strict=True)
        )
    ):
        raise ValueError("generated adapter operation and verb sets disagree")
    base_url = _bounded_string(
        value.get("base_url"), "base URL", maximum=2048, allow_empty=True
    )
    if base_url:
        try:
            parsed_url = urlsplit(base_url)
            parsed_url.port
        except ValueError as exc:
            raise ValueError("generated adapter base URL is invalid") from exc
        if (
            parsed_url.scheme.lower() not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("generated adapter base URL is invalid")
    adapter = GeneratedAdapter(
        adapter_id=str(record.id),
        base_url=base_url,
        operations=operations,
        verbspecs=verbs,
        rate_limit=rate_limit,
        spec_title=_bounded_string(
            value.get("spec_title"),
            "spec title",
            maximum=1024,
            allow_empty=True,
        ),
    )
    adapter.review_gate.activated = bool(record.activated)
    setattr(
        adapter,
        "_boltrig_generated_runtime_stamp",
        (record.spec_ref, bool(record.activated)),
    )
    return adapter


def stamp_generated_adapter(adapter: Any, record: Any) -> None:
    adapter._boltrig_generated_runtime_stamp = (
        record.spec_ref,
        bool(record.activated),
    )


async def reconcile_generated_adapter(
    loader: Any, tenant_id: str, record: Any
) -> GeneratedAdapter | None:
    """Return a live instance matching the current durable generated record."""
    if not is_generated_adapter_record(record):
        return None
    expected = (record.spec_ref, bool(record.activated))
    current = loader.peek(tenant_id, record.id)
    if (
        current is not None
        and getattr(current, "_boltrig_generated_runtime_stamp", None)
        == expected
    ):
        return cast(GeneratedAdapter, current)
    loader.unload(tenant_id, record.id)
    try:
        adapter = generated_adapter_from_record(record)
    except ValueError:
        return None
    loader.register(tenant_id, adapter)
    return adapter


__all__ = [
    "GENERATED_ADAPTER_KIND",
    "generated_adapter_from_record",
    "generated_adapter_projection",
    "is_generated_adapter_record",
    "reconcile_generated_adapter",
    "stamp_generated_adapter",
]
