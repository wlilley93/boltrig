"""Tenant-scoped Cognee model binding through the normal chat connection."""

from __future__ import annotations

import asyncio
from typing import Any

from boltrig.identity import load_ai_key_material, resolve_ai_key
from boltrig.identity.bifrost_user_binding import (
    BifrostUserBindingUnavailable,
    BifrostUserGateway,
)
from boltrig.identity.bifrost_user_transport import BifrostUserTransport

from .cognee import CogneeRuntimeModel


class CogneeModelUnavailable(RuntimeError):
    """The caller's governed chat model cannot currently serve Cognee."""


class CogneeModelBindingResolver:
    """Use ``resolve_ai_key`` for the same scoped connection as ordinary chat.

    The provider key never leaves the kernel.  It is used only to ensure the
    caller's existing Bifrost binding, after which Cognee receives the narrower
    virtual key and exact model route for this one async operation.
    """

    def __init__(
        self,
        store: Any,
        *,
        gateway: BifrostUserGateway | None = None,
        transport: BifrostUserTransport | None = None,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._transport = transport
        self._lock = asyncio.Lock()

    async def resolve(self, tenant_id: str, context: Any) -> CogneeRuntimeModel | None:
        if str(getattr(context, "tenant_id", "")) != tenant_id:
            raise CogneeModelUnavailable("AI connection scope is unavailable")
        user_id = getattr(context, "on_behalf_of", None)
        if user_id is None and getattr(context, "actor_tier", None) == "human":
            user_id = getattr(context, "actor", None)
        resolution = await resolve_ai_key(
            self._store,
            tenant_id,
            workspace_id=getattr(context, "workspace_id", None),
            user_id=user_id,
            modality="text",
        )
        if resolution.is_default:
            return None
        try:
            gateway, transport = await self._collaborators()
            binding = await gateway.load(self._store, tenant_id, resolution)
            if binding is None or not await gateway.is_usable(binding):
                material = await load_ai_key_material(self._store, tenant_id, resolution)
                if material is None:
                    raise CogneeModelUnavailable("The connected AI provider needs attention")
                binding = await gateway.ensure(self._store, tenant_id, resolution, material)
            endpoint, api_key, headers = transport.openai_compatible_route(binding.virtual_key)
        except CogneeModelUnavailable:
            raise
        except BifrostUserBindingUnavailable as error:
            raise CogneeModelUnavailable("The connected AI provider is unavailable") from error
        return CogneeRuntimeModel(
            model_id=binding.model_id,
            endpoint=endpoint,
            api_key=api_key,
            extra_headers=headers,
        )

    async def _collaborators(
        self,
    ) -> tuple[BifrostUserGateway, BifrostUserTransport]:
        """Lazily compose transport without serialising independent operations."""

        async with self._lock:
            if self._gateway is None:
                self._gateway = BifrostUserGateway()
            if self._transport is None:
                self._transport = BifrostUserTransport()
            return self._gateway, self._transport


__all__ = [
    "CogneeModelBindingResolver",
    "CogneeModelUnavailable",
]
