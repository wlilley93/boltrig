"""Shared scope fences and bounded canonical values for execution records."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Self, TypeAlias, cast

from .base import RunId, TenantId, UserId, WorkspaceId

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

MAX_IDENTIFIER_CHARS = 160
MAX_CANONICAL_BYTES = 32_768
MAX_JSON_DEPTH = 8
MAX_COLLECTION_ITEMS = 128
MAX_TOTAL_JSON_NODES = 512
MAX_JSON_KEY_CHARS = 80
MAX_JSON_STRING_CHARS = 4_096
MAX_SIGNED_BIGINT = 2**63 - 1

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "refresh_token",
        "jwt",
        "oauth_token",
        "oauthtoken",
        "secret",
        "session_token",
        "sessiontoken",
        "set_cookie",
        "token",
    }
)


def _contains_control_character(value: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)


def _require_identifier(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    text = value
    if (
        not text
        or text != text.strip()
        or len(text) > MAX_IDENTIFIER_CHARS
        or _contains_control_character(text)
    ):
        raise ValueError(f"{label} must be a bounded, non-empty, trimmed identifier")
    return text


def _require_bounded_text(label: str, value: object, *, maximum: int = 512) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    text = value
    if (
        not text
        or value != text.strip()
        or len(text) > maximum
        or _contains_control_character(text)
    ):
        raise ValueError(f"{label} must be non-empty, trimmed, and at most {maximum} chars")
    return text


def _require_sha256(label: str, value: object) -> str:
    text = _require_identifier(label, value)
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase sha256 digest")
    return text


def _require_positive(label: str, value: object, *, allow_zero: bool = False) -> int:
    if type(value) is not int:
        raise TypeError(f"{label} must be an exact integer")
    number = value
    minimum = 0 if allow_zero else 1
    if number < minimum or number > MAX_SIGNED_BIGINT:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{label} must be {qualifier} and fit a signed BIGINT")
    return number


def _require_aware(label: str, value: object) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{label} must be an exact datetime")
    timestamp = value
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return timestamp


def _require_exact_type(label: str, value: object, expected: type[object]) -> None:
    if type(value) is not expected:
        raise TypeError(f"{label} must be an exact {expected.__name__}")


def _require_exact_enum(label: str, value: object, expected: type[Enum]) -> None:
    if type(value) is not expected:
        raise TypeError(f"{label} must be an exact {expected.__name__}")


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalized_key(key)
    compact = normalized.replace("_", "")
    sensitive_suffixes = (
        "_api_key",
        "_cookie",
        "_credential",
        "_password",
        "_private_key",
        "_secret",
        "_token",
    )
    sensitive_prefixes = ("authorization_", "credential_", "password_", "secret_")
    return (
        normalized in _SENSITIVE_KEYS
        or compact in {"bearer", "jwt", "oauthtoken", "sessiontoken"}
        or normalized.endswith(sensitive_suffixes)
        or normalized.startswith(sensitive_prefixes)
    )


def _validate_json(value: object, *, depth: int, budget: list[int]) -> None:
    budget[0] += 1
    if budget[0] > MAX_TOTAL_JSON_NODES:
        raise ValueError("canonical payload has too many values")
    if depth > MAX_JSON_DEPTH:
        raise ValueError("canonical payload exceeds maximum nesting depth")
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("canonical payload numbers must be finite")
        return
    if type(value) is str:
        if len(value) > MAX_JSON_STRING_CHARS:
            raise ValueError("canonical payload string is too long")
        return
    if type(value) is list:
        items = cast(list[object], value)
        if len(items) > MAX_COLLECTION_ITEMS:
            raise ValueError("canonical payload collection is too large")
        for item in items:
            _validate_json(item, depth=depth + 1, budget=budget)
        return
    if type(value) is dict:
        document = cast(dict[object, object], value)
        if len(document) > MAX_COLLECTION_ITEMS:
            raise ValueError("canonical payload collection is too large")
        for key, item in document.items():
            if type(key) is not str:
                raise TypeError("canonical payload keys must be exact strings")
            text = key
            if not text or len(text) > MAX_JSON_KEY_CHARS:
                raise ValueError("canonical payload key is empty or too long")
            if _is_sensitive_key(text):
                raise ValueError("canonical payload contains a sensitive key")
            _validate_json(item, depth=depth + 1, budget=budget)
        return
    raise TypeError("canonical payload contains a non-JSON value")


class EngineOwner(str, Enum):
    BOLTRIG = "boltrig"
    CODEX = "codex"
    OPBOX = "opbox"


@dataclass(frozen=True)
class WorkspaceScopeRef:
    tenant_id: TenantId
    workspace_id: WorkspaceId

    def __post_init__(self) -> None:
        _require_identifier("tenant_id", self.tenant_id)
        _require_identifier("workspace_id", self.workspace_id)


@dataclass(frozen=True)
class OrganisationUserRef:
    tenant_id: TenantId
    user_id: UserId

    def __post_init__(self) -> None:
        _require_identifier("tenant_id", self.tenant_id)
        _require_identifier("user_id", self.user_id)


@dataclass(frozen=True)
class ExecutionScopeRef:
    workspace: WorkspaceScopeRef
    root_run_id: RunId

    def __post_init__(self) -> None:
        _require_exact_type("workspace", self.workspace, WorkspaceScopeRef)
        _require_identifier("root_run_id", self.root_run_id)

    @property
    def tenant_id(self) -> TenantId:
        return self.workspace.tenant_id

    @property
    def workspace_id(self) -> WorkspaceId:
        return self.workspace.workspace_id


@dataclass(frozen=True)
class CanonicalPayload:
    """Exact immutable canonical JSON copied at the durable trust boundary."""

    _encoded: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self._encoded) is not bytes:
            raise TypeError("canonical payload must be exact immutable bytes")
        copied = memoryview(self._encoded).tobytes()
        if len(copied) > MAX_CANONICAL_BYTES:
            raise ValueError("canonical payload exceeds byte limit")
        try:
            value = cast(object, json.loads(copied))
            _validate_json(value, depth=0, budget=[0])
            canonical = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("canonical payload is not valid JSON") from exc
        if type(value) is not dict:
            raise ValueError("canonical payload must be a JSON object")
        if canonical != copied:
            raise ValueError("canonical payload bytes are not canonical")
        object.__setattr__(self, "_encoded", copied)

    @classmethod
    def _from_mapping(cls, value: Mapping[str, JsonValue]) -> Self:
        document: object = dict(value)
        _validate_json(document, depth=0, budget=[0])
        encoded = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return cls(encoded)

    @classmethod
    def empty(cls) -> Self:
        return cls(b"{}")

    @property
    def encoded(self) -> bytes:
        return memoryview(self._encoded).tobytes()

    def to_mapping(self) -> dict[str, JsonValue]:
        value = cast(object, json.loads(self._encoded))
        _validate_json(value, depth=0, budget=[0])
        if type(value) is not dict:
            raise ValueError("canonical payload must be a JSON object")
        return cast(dict[str, JsonValue], value)
