"""Rebuilding a live adapter instance from its persisted store row.

The loader is in-memory only, so a control-plane-registered adapter is a
store-only ("phantom") row on any kernel instance that did not register it:
after a restart the boot loop (``api.bootstrap._rehydrate_store_adapters``)
rebuilds every row it can, and the activation path rebuilds ON DEMAND so a
row registered on another replica can still be activated through the governed
verb. Both paths share this module.

Only shapes the kernel can rebuild HONESTLY are supported: the MCP consumer,
whose registration persists in the row's ``spec_ref`` as a small JSON object
(``{"url", "allow_internal"}``; rows written before the egress flag existed
hold the plain url string and read back with the guarded default). Generated
adapters keep no rehydration source (their OpenAPI document was inline at
generation, and ``spec_ref`` is a reference column, not a document store),
and an explicit ``credential_id`` binding is not recoverable - both refuse
loudly rather than reconstruct halfway.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["consumer_spec", "rehydratable", "rehydrate_adapter_instance"]

_MCP_CONSUMER_MODULE = "boltrig.adapters.mcp_consumer"


def consumer_spec(spec_ref: str | None) -> dict:
    """The persisted consumer spec: ``{"url": str|None, "allow_internal": bool}``.

    NEW registrations write JSON; rows written before the egress flag existed
    hold the plain url STRING, which reads as ``allow_internal: False`` - the
    guarded default, so an old row can never silently gain the internal
    waiver. Anything unrecognisable also fails to the guarded default.
    """
    if not spec_ref:
        return {"url": None, "allow_internal": False}
    try:
        parsed = json.loads(spec_ref)
    except ValueError:
        return {"url": spec_ref, "allow_internal": False}  # the legacy plain url
    if isinstance(parsed, dict) and isinstance(parsed.get("url"), str):
        return {"url": parsed["url"], "allow_internal": bool(parsed.get("allow_internal"))}
    return {"url": spec_ref, "allow_internal": False}


def rehydratable(record: Any) -> bool:
    """True when the store row carries everything an honest rebuild needs."""
    return record.module_ref == _MCP_CONSUMER_MODULE and bool(record.spec_ref)


async def rehydrate_adapter_instance(
    store: Any, credentials: Any, loader: Any, tenant_id: str, record: Any
) -> Any | None:
    """Rebuild and register the live instance for a rehydratable row.

    The persisted review gate stands (``record.activated``, SEC-22), and the
    default credential-id convention re-binds from its persisted ref row so
    activation/execution resolve the credential again. Returns ``None`` when
    the row has no honest reconstruction.
    """
    if not rehydratable(record):
        return None
    from boltrig.adapters.mcp_consumer import McpConsumerAdapter

    spec = consumer_spec(record.spec_ref)
    consumer = McpConsumerAdapter(
        record.id, url=spec["url"], allow_internal=spec["allow_internal"]
    )
    consumer.activated = bool(record.activated)
    loader.register(tenant_id, consumer)
    cred_id = f"{record.id}-mcp-token"  # bind_mcp_credential's default id
    if await store.get_credential_ref(tenant_id, cred_id) is not None:
        credentials.bind_adapter_credential(tenant_id, record.id, cred_id)
    return consumer
