"""Immutable policy values for a fail-closed Codex runtime rollout."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum

MAX_CANARY_SCOPES = 10_000
CANARY_BUCKETS = 10_000
MIN_CANARY_HASH_KEY_BYTES = 32
MAX_CANARY_HASH_KEY_BYTES = 64

_IDENTIFIER = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _identifier(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if len(value) > 128 or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded canonical identifier")
    return value


def _generation(value: object) -> int:
    if type(value) is not int:
        raise TypeError("policy generation must be an exact integer")
    if value < 1:
        raise ValueError("policy generation must be positive")
    return value


def _sha256(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase sha256 digest")
    return value


def _document_digest(document: object) -> str:
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class CodexRolloutMode(str, Enum):
    """Server-owned rollout stage; disabled is the default."""

    OFF = "off"
    SHADOW = "shadow"
    CANARY = "canary"
    DEFAULT = "default"


class RootWorkload(str, Enum):
    """Governed root characteristic used to prohibit write shadowing."""

    BOUNDED_READ_ONLY = "bounded_read_only"
    WRITE_CAPABLE = "write_capable"


class CodexCompatibility(str, Enum):
    """Server-derived compatibility fact, never a caller-supplied route hint."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class EngineRoute(str, Enum):
    """The immutable runtime route selected when a root is created."""

    LEGACY = "legacy"
    CODEX_APP_SERVER = "codex_app_server"
    LEGACY_PRIMARY_CODEX_SHADOW = "legacy_primary_codex_shadow"


class ExecutionResultSource(str, Enum):
    """Execution path whose output Boltrig may validate and commit for the root."""

    LEGACY = "legacy"
    CODEX_APP_SERVER = "codex_app_server"


class RoutingReason(str, Enum):
    """Stable audit reason codes for persisted routing decisions."""

    ROLLOUT_OFF = "rollout_off"
    EMERGENCY_ROLLBACK = "emergency_rollback"
    ROOT_INELIGIBLE = "root_ineligible"
    READ_ONLY_SHADOW = "read_only_shadow"
    CANARY_SCOPE_NOT_ALLOWLISTED = "canary_scope_not_allowlisted"
    CANARY_NOT_SELECTED = "canary_not_selected"
    CANARY_SELECTED = "canary_selected"
    DEFAULT_SELECTED = "default_selected"


@dataclass(frozen=True, slots=True, order=True)
class RootRouteScope:
    """Exact tenant/workspace/root identity used by the server-side router."""

    tenant_id: str
    workspace_id: str
    root_run_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _identifier("tenant_id", self.tenant_id))
        object.__setattr__(
            self, "workspace_id", _identifier("workspace_id", self.workspace_id)
        )
        object.__setattr__(
            self, "root_run_id", _identifier("root_run_id", self.root_run_id)
        )

    def canonical_bytes(self) -> bytes:
        return "\x1f".join(
            (self.tenant_id, self.workspace_id, self.root_run_id)
        ).encode("ascii")


@dataclass(frozen=True, slots=True, order=True)
class CanaryScope:
    """One exact tenant/workspace allowlist cell; wildcards are impossible."""

    tenant_id: str
    workspace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _identifier("tenant_id", self.tenant_id))
        object.__setattr__(
            self, "workspace_id", _identifier("workspace_id", self.workspace_id)
        )

    def contains(self, root: RootRouteScope) -> bool:
        if type(root) is not RootRouteScope:
            raise TypeError("root scope must be an exact RootRouteScope")
        return self.tenant_id == root.tenant_id and self.workspace_id == root.workspace_id


def _canary_scopes(values: object) -> tuple[CanaryScope, ...]:
    if type(values) is not tuple:
        raise TypeError("canary allowlist must be an immutable tuple")
    if len(values) > MAX_CANARY_SCOPES:
        raise ValueError(f"canary allowlist exceeds {MAX_CANARY_SCOPES} scopes")
    if any(type(value) is not CanaryScope for value in values):
        raise TypeError("canary allowlist entries must be exact CanaryScope values")
    if len(values) != len(set(values)):
        raise ValueError("canary allowlist must not contain duplicate scopes")
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class CodexRolloutPolicy:
    """One immutable, server-owned rollout policy generation."""

    generation: int
    mode: CodexRolloutMode = CodexRolloutMode.OFF
    emergency_rollback: bool = False
    canary_percentage: int = 0
    canary_allowlist: tuple[CanaryScope, ...] = ()
    canary_hash_key: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "generation", _generation(self.generation))
        if type(self.mode) is not CodexRolloutMode:
            raise TypeError("rollout mode must be an exact CodexRolloutMode")
        if type(self.emergency_rollback) is not bool:
            raise TypeError("emergency_rollback must be an exact boolean")
        if type(self.canary_percentage) is not int:
            raise TypeError("canary_percentage must be an exact integer")
        if not 0 <= self.canary_percentage <= 100:
            raise ValueError("canary_percentage must be between 0 and 100")
        scopes = _canary_scopes(self.canary_allowlist)
        object.__setattr__(self, "canary_allowlist", scopes)
        self._validate_canary_configuration()

    def _validate_canary_configuration(self) -> None:
        configured = (
            self.canary_percentage != 0
            or bool(self.canary_allowlist)
            or self.canary_hash_key is not None
        )
        if self.mode is not CodexRolloutMode.CANARY:
            if configured:
                raise ValueError("canary settings are valid only in canary mode")
            return
        if type(self.canary_hash_key) is not bytes:
            raise TypeError("canary_hash_key must be immutable bytes in canary mode")
        if not MIN_CANARY_HASH_KEY_BYTES <= len(self.canary_hash_key) <= MAX_CANARY_HASH_KEY_BYTES:
            raise ValueError(
                "canary_hash_key must contain between 32 and 64 bytes"
            )

    @property
    def digest(self) -> str:
        key_digest = (
            None
            if self.canary_hash_key is None
            else f"sha256:{hashlib.sha256(self.canary_hash_key).hexdigest()}"
        )
        return _document_digest(
            {
                "canary_allowlist": [
                    {"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id}
                    for scope in self.canary_allowlist
                ],
                "canary_hash_key_digest": key_digest,
                "canary_percentage": self.canary_percentage,
                "emergency_rollback": self.emergency_rollback,
                "generation": self.generation,
                "mode": self.mode.value,
            }
        )


@dataclass(frozen=True, slots=True)
class RootRoutingFacts:
    """Trusted server facts; prompts, metadata, and route hints are absent."""

    scope: RootRouteScope
    expected_policy_generation: int
    workload: RootWorkload
    compatibility: CodexCompatibility

    def __post_init__(self) -> None:
        if type(self.scope) is not RootRouteScope:
            raise TypeError("scope must be an exact RootRouteScope")
        object.__setattr__(
            self,
            "expected_policy_generation",
            _generation(self.expected_policy_generation),
        )
        if type(self.workload) is not RootWorkload:
            raise TypeError("workload must be an exact RootWorkload")
        if type(self.compatibility) is not CodexCompatibility:
            raise TypeError("compatibility must be an exact CodexCompatibility")


_ROUTE_RESULT_SOURCES = {
    EngineRoute.LEGACY: ExecutionResultSource.LEGACY,
    EngineRoute.CODEX_APP_SERVER: ExecutionResultSource.CODEX_APP_SERVER,
    EngineRoute.LEGACY_PRIMARY_CODEX_SHADOW: ExecutionResultSource.LEGACY,
}
_REASON_ROUTES = {
    RoutingReason.ROLLOUT_OFF: EngineRoute.LEGACY,
    RoutingReason.EMERGENCY_ROLLBACK: EngineRoute.LEGACY,
    RoutingReason.ROOT_INELIGIBLE: EngineRoute.LEGACY,
    RoutingReason.READ_ONLY_SHADOW: EngineRoute.LEGACY_PRIMARY_CODEX_SHADOW,
    RoutingReason.CANARY_SCOPE_NOT_ALLOWLISTED: EngineRoute.LEGACY,
    RoutingReason.CANARY_NOT_SELECTED: EngineRoute.LEGACY,
    RoutingReason.CANARY_SELECTED: EngineRoute.CODEX_APP_SERVER,
    RoutingReason.DEFAULT_SELECTED: EngineRoute.CODEX_APP_SERVER,
}
_CANARY_REASONS = {
    RoutingReason.CANARY_NOT_SELECTED,
    RoutingReason.CANARY_SELECTED,
}


@dataclass(frozen=True, slots=True)
class RootEngineDecision:
    """Persistable root decision; a timestamp is deliberately not synthesized."""

    scope: RootRouteScope
    workload: RootWorkload
    compatibility: CodexCompatibility
    policy_generation: int
    policy_digest: str
    route: EngineRoute
    execution_result_source: ExecutionResultSource
    reason_code: RoutingReason
    canary_bucket: int | None = None

    def __post_init__(self) -> None:
        if type(self.scope) is not RootRouteScope:
            raise TypeError("scope must be an exact RootRouteScope")
        if type(self.workload) is not RootWorkload:
            raise TypeError("workload must be an exact RootWorkload")
        if type(self.compatibility) is not CodexCompatibility:
            raise TypeError("compatibility must be an exact CodexCompatibility")
        object.__setattr__(self, "policy_generation", _generation(self.policy_generation))
        object.__setattr__(
            self, "policy_digest", _sha256("policy digest", self.policy_digest)
        )
        self._validate_outcome()

    def _validate_outcome(self) -> None:
        if type(self.route) is not EngineRoute:
            raise TypeError("route must be an exact EngineRoute")
        if type(self.execution_result_source) is not ExecutionResultSource:
            raise TypeError(
                "execution_result_source must be an exact ExecutionResultSource"
            )
        if type(self.reason_code) is not RoutingReason:
            raise TypeError("reason_code must be an exact RoutingReason")
        if _ROUTE_RESULT_SOURCES[self.route] is not self.execution_result_source:
            raise ValueError("route and execution result source disagree")
        if _REASON_ROUTES[self.reason_code] is not self.route:
            raise ValueError("reason code and route disagree")
        if self.route is EngineRoute.LEGACY_PRIMARY_CODEX_SHADOW and (
            self.workload is not RootWorkload.BOUNDED_READ_ONLY
            or self.reason_code is not RoutingReason.READ_ONLY_SHADOW
        ):
            raise ValueError("Codex shadow decisions must be bounded and read-only")
        if self.canary_bucket is None:
            if self.reason_code in _CANARY_REASONS:
                raise ValueError("percentage-based canary decisions require a bucket")
        elif (
            type(self.canary_bucket) is not int
            or not 0 <= self.canary_bucket < CANARY_BUCKETS
            or self.reason_code not in _CANARY_REASONS
        ):
            raise ValueError("canary bucket must match a percentage-based canary reason")

    @property
    def digest(self) -> str:
        return _document_digest(
            {
                "canary_bucket": self.canary_bucket,
                "compatibility": self.compatibility.value,
                "policy_digest": self.policy_digest,
                "policy_generation": self.policy_generation,
                "reason_code": self.reason_code.value,
                "execution_result_source": self.execution_result_source.value,
                "route": self.route.value,
                "root_run_id": self.scope.root_run_id,
                "tenant_id": self.scope.tenant_id,
                "workload": self.workload.value,
                "workspace_id": self.scope.workspace_id,
            }
        )


__all__ = [
    "CANARY_BUCKETS",
    "CanaryScope",
    "CodexCompatibility",
    "CodexRolloutMode",
    "CodexRolloutPolicy",
    "EngineRoute",
    "ExecutionResultSource",
    "RootEngineDecision",
    "RootRouteScope",
    "RootRoutingFacts",
    "RootWorkload",
    "RoutingReason",
]
