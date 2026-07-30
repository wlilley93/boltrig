"""Store-authoritative adapter provider for the dispatch chokepoint."""

from __future__ import annotations

from typing import Any


class AuthoritativeAdapterProvider:
    """Reconcile mutable external-MCP instances before returning them."""

    def __init__(self, store: Any, loader: Any, credentials: Any) -> None:
        self._store = store
        self._loader = loader
        self._credentials = credentials

    async def __call__(self, tenant_id: str, adapter_id: str) -> Any | None:
        record = await self._store.get_adapter(tenant_id, adapter_id)
        if record is None:
            # A replica may retain an instance after another replica deleted its
            # durable registration. Absence is authoritative.
            self._loader.unload(tenant_id, adapter_id)
            self._credentials.replace_adapter_credential_binding(
                tenant_id, adapter_id, None
            )
            return None
        from boltrig.config.control_rehydrate import (
            is_mcp_consumer,
            reconcile_mcp_adapter,
        )
        from boltrig.config.control_generated_adapter import (
            is_generated_adapter_record,
            reconcile_generated_adapter,
        )

        if is_generated_adapter_record(record):
            adapter = await reconcile_generated_adapter(
                self._loader, tenant_id, record
            )
            return adapter if record.activated else None
        if not is_mcp_consumer(record):
            return await self._loader.get(tenant_id, adapter_id)
        adapter = await reconcile_mcp_adapter(
            self._store,
            self._credentials,
            self._loader,
            tenant_id,
            record,
        )
        lifecycle = await self._store.get_mcp_server_lifecycle(
            tenant_id, adapter_id
        )
        return (
            adapter
            if lifecycle is not None and lifecycle.state == "active"
            else None
        )


__all__ = ["AuthoritativeAdapterProvider"]
