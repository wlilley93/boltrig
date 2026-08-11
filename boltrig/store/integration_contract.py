"""Store protocol fragment for integration catalogue and connection state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from boltrig.models.integrations import (
    IntegrationCatalogueRecord,
    IntegrationConnection,
)


class IntegrationStoreContract(Protocol):
    async def upsert_integration_catalogue(self, item: IntegrationCatalogueRecord) -> None: ...

    async def get_integration_catalogue(
        self, tenant_id: str, integration_id: str
    ) -> IntegrationCatalogueRecord | None: ...

    async def list_integration_catalogue(
        self, tenant_id: str
    ) -> list[IntegrationCatalogueRecord]: ...

    async def upsert_integration_connection(self, connection: IntegrationConnection) -> None: ...

    async def update_integration_connection_health_if_active(
        self,
        tenant_id: str,
        connection_id: str,
        health: str,
        checked_at: datetime,
    ) -> IntegrationConnection | None:
        """Update observation fields only while the connection remains active."""
        ...

    async def create_integration_connection(self, connection: IntegrationConnection) -> bool:
        """Create one active connection per adapter, atomically."""
        ...

    async def create_integration_connection_with_credential(
        self,
        connection: IntegrationConnection,
        credential: dict[str, Any],
    ) -> bool:
        """Atomically seal a credential and create its sole active connection."""
        ...

    async def get_integration_connection(
        self, tenant_id: str, connection_id: str
    ) -> IntegrationConnection | None: ...

    async def get_active_integration_connection_for_adapter(
        self, tenant_id: str, adapter_id: str
    ) -> IntegrationConnection | None:
        """Return exactly one active adapter connection; ambiguity fails closed."""
        ...

    async def list_integration_connections(self, tenant_id: str) -> list[IntegrationConnection]: ...

    async def revoke_integration_connection(
        self, tenant_id: str, connection_id: str
    ) -> IntegrationConnection | None: ...

    async def revoke_integration_connection_with_credential(
        self, tenant_id: str, connection_id: str
    ) -> tuple[IntegrationConnection | None, str | None, bool]:
        """Atomically revoke and delete only the connection-owned credential."""
        ...
