"""Store protocol fragment for canonical capability routing.

Reads are DETERMINISTICALLY ORDERED (priority, then id). The resolver turns a
list of eligible bindings into exactly one execution plan, so an unstable list
order would make routing non-deterministic in the one place the doctrine is
least willing to tolerate it.
"""

from __future__ import annotations

from typing import Protocol

from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    RoutingPolicy,
    SourceOperation,
)


class CapabilityRoutingStoreContract(Protocol):
    async def upsert_provider_connection(self, connection: ProviderConnection) -> None: ...

    async def get_provider_connection(
        self, tenant_id: str, connection_id: str
    ) -> ProviderConnection | None: ...

    async def list_provider_connections(
        self, tenant_id: str
    ) -> list[ProviderConnection]: ...

    async def upsert_source_operation(self, operation: SourceOperation) -> None: ...

    async def get_source_operation(
        self, tenant_id: str, operation_id: str
    ) -> SourceOperation | None: ...

    async def list_source_operations(
        self, tenant_id: str, connection_id: str | None = None
    ) -> list[SourceOperation]: ...

    # A second binding for the same capability ADDS a row; it never replaces the
    # first. The identity is binding_id (SPEC §8), which is what makes the
    # doctrine's multiple eligible implementations expressible at all.
    async def upsert_capability_binding(self, binding: CapabilityBinding) -> None: ...

    # The review action. Returns None where the binding does not exist, so an
    # approval naming a stale id reports that rather than silently succeeding.
    async def set_capability_binding_status(
        self, tenant_id: str, binding_id: str, status: str, reviewed_by: str | None
    ) -> CapabilityBinding | None: ...

    # ``source_operation_id`` is the REVERSE lookup the approval gate needs:
    # given a bare provider verb, which capabilities does it implement? Without
    # it the gate can only match names, and a capability blocked by an operator
    # governs only the spelling nobody uses.
    async def list_capability_bindings(
        self,
        tenant_id: str,
        capability_id: str | None = None,
        *,
        source_operation_id: str | None = None,
    ) -> list[CapabilityBinding]: ...

    async def upsert_routing_policy(self, policy: RoutingPolicy) -> None: ...

    async def list_routing_policies(
        self, tenant_id: str, capability_id: str | None = None
    ) -> list[RoutingPolicy]: ...
