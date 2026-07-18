"""Short-lived model-proxy credentials with no MCP or Opbox authority."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
import re
from typing import NoReturn

from .model_proxy_scope import (
    MAX_SIGNED_BIGINT,
    ModelProxyGrantBinding,
    _identifier,
    _positive,
)

MAX_MODEL_PROXY_GRANT_TTL_SECONDS = 120
_BEARER = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_RAW_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _aware(label: str, value: object) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{label} must be an exact datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _raw_digest(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if _RAW_SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def validate_model_proxy_revocation_reason(value: object) -> str:
    return _identifier("revocation reason", value)


def validate_model_proxy_identifier(label: str, value: object) -> str:
    return _identifier(label, value)


def validate_model_proxy_generation(value: object) -> int:
    return _positive("generation", value)


def validate_model_proxy_ttl_seconds(value: object) -> int:
    ttl = _positive("ttl_seconds", value)
    if ttl > MAX_MODEL_PROXY_GRANT_TTL_SECONDS:
        raise ValueError("ttl_seconds must be between 1 and 120")
    return ttl


class ModelProxyGrantStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ModelProxyGrantConflict(RuntimeError):
    """An issuance attempt conflicted with retained security state."""


class ActiveModelProxyGenerationConflict(ModelProxyGrantConflict):
    """The exact cell already has an active grant for this generation."""


class StaleModelProxyGeneration(ModelProxyGrantConflict):
    """The generation is stale or its scope has been terminally cancelled."""


class ModelProxyClockRollback(ModelProxyGrantConflict):
    """The store observed time moving backwards and permanently failed closed."""


@dataclass(frozen=True)
class ModelProxyGrantDraft:
    """Untimestamped issuance intent; only an authoritative store may mint time."""

    grant_id: str
    binding: ModelProxyGrantBinding
    bearer_digest: str = field(repr=False)
    startup_request_digest: str = field(repr=False)
    ttl_seconds: int
    generation: int

    def __post_init__(self) -> None:
        _identifier("grant_id", self.grant_id)
        if type(self.binding) is not ModelProxyGrantBinding:
            raise TypeError("binding must be an exact ModelProxyGrantBinding")
        _raw_digest("bearer digest", self.bearer_digest)
        _raw_digest("startup request digest", self.startup_request_digest)
        validate_model_proxy_ttl_seconds(self.ttl_seconds)
        validate_model_proxy_generation(self.generation)


@dataclass(frozen=True)
class StoredModelProxyGrant:
    """Digest-only retained metadata; never a source of domain authority."""

    grant_id: str
    binding: ModelProxyGrantBinding
    bearer_digest: str = field(repr=False)
    startup_request_digest: str = field(repr=False)
    issued_at: datetime
    expires_at: datetime
    generation: int
    status: ModelProxyGrantStatus = ModelProxyGrantStatus.ACTIVE
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        _identifier("grant_id", self.grant_id)
        if type(self.binding) is not ModelProxyGrantBinding:
            raise TypeError("binding must be an exact ModelProxyGrantBinding")
        _raw_digest("bearer digest", self.bearer_digest)
        _raw_digest("startup request digest", self.startup_request_digest)
        issued = _aware("issued_at", self.issued_at)
        expires = _aware("expires_at", self.expires_at)
        validate_model_proxy_generation(self.generation)
        lifetime = expires - issued
        if lifetime <= timedelta(0) or lifetime > timedelta(seconds=120):
            raise ValueError("model-proxy grant lifetime must be between 1 and 120 seconds")
        self._validate_terminal()

    def _validate_terminal(self) -> None:
        if type(self.status) is not ModelProxyGrantStatus:
            raise TypeError("status must be an exact ModelProxyGrantStatus")
        if self.status is ModelProxyGrantStatus.REVOKED:
            if self.revoked_at is None or self.revocation_reason is None:
                raise ValueError("revoked grants require a timestamp and reason")
            revoked = _aware("revoked_at", self.revoked_at)
            validate_model_proxy_revocation_reason(self.revocation_reason)
            if revoked < self.issued_at:
                raise ValueError("revoked_at cannot precede issued_at")
        elif self.revoked_at is not None or self.revocation_reason is not None:
            raise ValueError("non-revoked grants cannot carry revocation metadata")

    def active_at(self, now: datetime, *, generation: int) -> bool:
        current = _aware("now", now)
        if type(generation) is not int or not 1 <= generation <= MAX_SIGNED_BIGINT:
            return False
        return (
            self.status is ModelProxyGrantStatus.ACTIVE
            and self.issued_at <= current < self.expires_at
            and self.generation == generation
        )

    def revoke(self, *, now: datetime, reason: str) -> StoredModelProxyGrant:
        if self.status is not ModelProxyGrantStatus.ACTIVE:
            return self
        current = max(_aware("now", now), self.issued_at)
        return replace(
            self,
            status=ModelProxyGrantStatus.REVOKED,
            revoked_at=current,
            revocation_reason=validate_model_proxy_revocation_reason(reason),
        )

    def expire(self) -> StoredModelProxyGrant:
        return (
            self
            if self.status is not ModelProxyGrantStatus.ACTIVE
            else replace(self, status=ModelProxyGrantStatus.EXPIRED)
        )


class ModelProxyBearer:
    """Opaque write-once 256-bit bearer for one isolated handoff."""

    __slots__ = ("_sealed", "_value")
    _sealed: bool
    _value: str

    def __init__(self, value: str) -> None:
        if type(value) is not str:
            raise TypeError("model-proxy bearer must be an exact string")
        decoded = b""
        if _BEARER.fullmatch(value) is not None:
            try:
                decoded = base64.urlsafe_b64decode(value + "=")
            except (ValueError, UnicodeError):
                decoded = b""
        canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
        if len(decoded) != 32 or canonical != value:
            raise ValueError("model-proxy bearer must encode exactly 256 random bits")
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("model-proxy bearers are immutable")

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "ModelProxyBearer(<redacted>)"

    __str__ = __repr__

    def __reduce__(self) -> NoReturn:
        raise TypeError("model-proxy bearers cannot be serialized")


@dataclass(frozen=True)
class ModelProxyGrantReceipt:
    grant_id: str
    binding: ModelProxyGrantBinding
    issued_at: datetime
    expires_at: datetime
    generation: int

    def __post_init__(self) -> None:
        _identifier("grant_id", self.grant_id)
        if type(self.binding) is not ModelProxyGrantBinding:
            raise TypeError("binding must be an exact ModelProxyGrantBinding")
        issued, expires = _aware("issued_at", self.issued_at), _aware("expires_at", self.expires_at)
        lifetime = expires - issued
        if lifetime <= timedelta(0) or lifetime > timedelta(seconds=120):
            raise ValueError("model-proxy receipt lifetime must be between 1 and 120 seconds")
        validate_model_proxy_generation(self.generation)


@dataclass(frozen=True)
class IssuedModelProxyGrant:
    receipt: ModelProxyGrantReceipt
    bearer: ModelProxyBearer

    def __post_init__(self) -> None:
        if type(self.receipt) is not ModelProxyGrantReceipt:
            raise TypeError("receipt must be an exact ModelProxyGrantReceipt")
        if type(self.bearer) is not ModelProxyBearer:
            raise TypeError("bearer must be an exact ModelProxyBearer")

    def __repr__(self) -> str:
        return f"IssuedModelProxyGrant(receipt={self.receipt!r}, bearer=<redacted>)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("issued model-proxy grants cannot be serialized")


__all__ = [name for name in globals() if name.startswith("ModelProxy") or name.startswith("Stored")]
__all__ += [
    "ActiveModelProxyGenerationConflict",
    "StaleModelProxyGeneration",
    "validate_model_proxy_generation",
    "validate_model_proxy_identifier",
    "validate_model_proxy_revocation_reason",
    "validate_model_proxy_ttl_seconds",
]
