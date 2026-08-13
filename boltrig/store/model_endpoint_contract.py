"""Atomic revisioned model endpoint persistence contract."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from boltrig.models import ModelEndpoint


_MODEL_ENDPOINT_REFERENCE_LOCK_PREFIX = "model-endpoints:"


async def lock_model_endpoint_reference_graph(conn: Any, tenant_id: str) -> None:
    """Serialize endpoint state with capability and fallback reference writes."""

    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"{_MODEL_ENDPOINT_REFERENCE_LOCK_PREFIX}{tenant_id}",
    )


@dataclass(frozen=True, slots=True)
class ModelEndpointReferenceSnapshot:
    """Canonical affected-consumer set bound to a model-endpoint approval."""

    capabilities: tuple[str, ...]
    fallbacks: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, values in (
            ("capabilities", self.capabilities),
            ("fallbacks", self.fallbacks),
        ):
            if any(type(value) is not str for value in values):
                raise TypeError(f"model endpoint {label} must be exact strings")
            if values != tuple(sorted(set(values))):
                raise ValueError(f"model endpoint {label} must be sorted and unique")

    def approval_context(self) -> dict[str, list[str]]:
        return {
            "capabilities": list(self.capabilities),
            "fallbacks": list(self.fallbacks),
        }

    @classmethod
    def parse_approval_context(cls, value: Any) -> "ModelEndpointReferenceSnapshot":
        if type(value) is not dict or set(value) != {"capabilities", "fallbacks"}:
            raise TypeError("approved model endpoint references are invalid")
        capabilities = value["capabilities"]
        fallbacks = value["fallbacks"]
        if type(capabilities) is not list or type(fallbacks) is not list:
            raise TypeError("approved model endpoint references are invalid")
        return cls(tuple(capabilities), tuple(fallbacks))


def canonical_model_endpoint_references(
    capabilities: Iterable[str], fallbacks: Iterable[str]
) -> ModelEndpointReferenceSnapshot:
    return ModelEndpointReferenceSnapshot(
        tuple(sorted(set(capabilities))),
        tuple(sorted(set(fallbacks))),
    )


class ModelEndpointStoreContract(Protocol):
    async def upsert_model_endpoint(self, endpoint: ModelEndpoint) -> None: ...

    async def compare_and_upsert_model_endpoint(
        self,
        endpoint: ModelEndpoint,
        expected: ModelEndpoint | None,
        *,
        expected_fallback: ModelEndpoint | None,
        expected_references: ModelEndpointReferenceSnapshot,
    ) -> bool: ...

    async def get_model_endpoint(
        self, tenant_id: str, endpoint_id: str
    ) -> ModelEndpoint | None: ...

    async def list_model_endpoints(self, tenant_id: str) -> list[ModelEndpoint]: ...

    async def model_endpoint_references(
        self, tenant_id: str, endpoint_id: str
    ) -> ModelEndpointReferenceSnapshot: ...

    async def set_model_endpoint_active(
        self, tenant_id: str, endpoint_id: str, active: bool
    ) -> ModelEndpoint | None: ...

    async def compare_and_set_model_endpoint_active(
        self,
        tenant_id: str,
        endpoint_id: str,
        active: bool,
        expected: ModelEndpoint,
    ) -> ModelEndpoint | None: ...


__all__ = [
    "ModelEndpointReferenceSnapshot",
    "ModelEndpointStoreContract",
    "canonical_model_endpoint_references",
    "lock_model_endpoint_reference_graph",
]
