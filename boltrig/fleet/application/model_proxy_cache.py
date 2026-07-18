"""Internal immutable cache values for model-proxy issuance."""

from __future__ import annotations

from dataclasses import dataclass, field

from boltrig.fleet.application.model_proxy_deadline import ModelProxyIssuanceDeadline
from boltrig.fleet.domain.model_proxy_grant import ModelProxyGrantReceipt
from boltrig.fleet.domain.model_proxy_scope import ModelProxyGrantBinding


@dataclass(frozen=True)
class ModelProxyCacheKey:
    binding: ModelProxyGrantBinding
    request_id: str


@dataclass(frozen=True)
class ModelProxyStartupFingerprint:
    ttl_seconds: int
    generation: int


@dataclass(frozen=True, repr=False)
class CachedModelProxyBearer:
    fingerprint: ModelProxyStartupFingerprint
    receipt: ModelProxyGrantReceipt
    deadline: ModelProxyIssuanceDeadline
    secret: str = field(repr=False)


__all__ = ["CachedModelProxyBearer", "ModelProxyCacheKey", "ModelProxyStartupFingerprint"]
