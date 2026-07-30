"""Rebuilding a live adapter instance from its persisted store row.

The loader is in-memory only, so a control-plane-registered adapter is a
store-only ("phantom") row on any kernel instance that did not register it:
after a restart the boot loop (``api.bootstrap._rehydrate_store_adapters``)
rebuilds every row it can, and the activation path rebuilds ON DEMAND so a
row registered on another replica can still be activated through the governed
verb. Both paths share this module.

Only shapes the kernel can rebuild HONESTLY are supported: the MCP consumer
persists its private endpoint configuration, while a generated adapter persists
the bounded executable projection derived from its OpenAPI document (never the
whole author document). Both retain their durable review-gate state.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

log = logging.getLogger("boltrig.config.control_rehydrate")

__all__ = [
    "consumer_spec",
    "is_mcp_consumer",
    "reconcile_mcp_adapter",
    "rehydratable",
    "rehydrate_adapter_instance",
    "stamp_mcp_consumer",
]

_MCP_CONSUMER_MODULE = "boltrig.adapters.mcp_consumer"


class ConsumerSpec(TypedDict):
    url: str | None
    allow_internal: bool
    credential_id: str | None
    credential_binding_explicit: bool


def consumer_spec(spec_ref: str | None) -> ConsumerSpec:
    """Read the private, persisted consumer reconstruction spec.

    NEW registrations write JSON; rows written before the egress flag existed
    hold the plain url STRING, which reads as ``allow_internal: False`` - the
    guarded default, so an old row can never silently gain the internal
    waiver. Anything unrecognisable also fails to the guarded default.
    """
    if not spec_ref:
        return {
            "url": None,
            "allow_internal": False,
            "credential_id": None,
            "credential_binding_explicit": False,
        }
    try:
        parsed = json.loads(spec_ref)
    except ValueError:
        return {
            "url": spec_ref,
            "allow_internal": False,
            "credential_id": None,
            "credential_binding_explicit": False,
        }
    if isinstance(parsed, dict) and isinstance(parsed.get("url"), str):
        credential_id = parsed.get("credential_id")
        return {
            "url": parsed["url"],
            "allow_internal": bool(parsed.get("allow_internal")),
            "credential_id": (
                credential_id
                if isinstance(credential_id, str) and credential_id
                else None
            ),
            "credential_binding_explicit": "credential_id" in parsed,
        }
    return {
        "url": spec_ref,
        "allow_internal": False,
        "credential_id": None,
        "credential_binding_explicit": False,
    }


def is_mcp_consumer(record: Any) -> bool:
    """Whether an adapter row is the canonical external-MCP consumer shape."""
    return bool(record.module_ref == _MCP_CONSUMER_MODULE)


def rehydratable(record: Any) -> bool:
    """True when the store row carries everything an honest rebuild needs."""
    from .control_generated_adapter import is_generated_adapter_record

    return bool(
        record.spec_ref
        and (is_mcp_consumer(record) or is_generated_adapter_record(record))
    )


def _runtime_stamp(record: Any, lifecycle: Any) -> tuple[Any, ...]:
    return (
        record.spec_ref,
        lifecycle.created_at,
        getattr(lifecycle, "config_revision", 1),
        lifecycle.state,
        lifecycle.tools_observed_at,
    )


def stamp_mcp_consumer(adapter: Any, record: Any, lifecycle: Any) -> None:
    """Stamp the durable MCP generation/config represented by a live instance."""
    adapter._boltrig_mcp_runtime_stamp = _runtime_stamp(record, lifecycle)


async def _credential_id(store: Any, tenant_id: str, record: Any) -> str | None:
    spec = consumer_spec(record.spec_ref)
    if spec["credential_binding_explicit"]:
        return spec["credential_id"]
    legacy_id = f"{record.id}-mcp-token"
    return (
        legacy_id
        if await store.has_credential_ref(tenant_id, legacy_id)
        else None
    )


async def rehydrate_adapter_instance(
    store: Any,
    credentials: Any,
    loader: Any,
    tenant_id: str,
    record: Any,
    *,
    lifecycle: Any = None,
) -> Any | None:
    """Rebuild and register the live instance for a rehydratable row.

    The persisted review gate stands (``record.activated``, SEC-22), and the
    private credential-id binding (or the legacy default convention) re-binds
    from its persisted ref row so activation/execution resolve the credential
    again. Returns ``None`` when the row has no honest reconstruction.
    """
    if not rehydratable(record):
        return None
    from .control_generated_adapter import (
        is_generated_adapter_record,
        reconcile_generated_adapter,
    )

    if is_generated_adapter_record(record):
        return await reconcile_generated_adapter(loader, tenant_id, record)
    from boltrig.adapters.mcp_consumer import McpConsumerAdapter

    spec = consumer_spec(record.spec_ref)
    consumer = McpConsumerAdapter(
        record.id, url=spec["url"], allow_internal=spec["allow_internal"]
    )
    lifecycle = lifecycle or await store.get_mcp_server_lifecycle(
        tenant_id, record.id
    )
    if lifecycle is None:
        return None
    consumer.activated = lifecycle.state == "active"
    snapshot = lifecycle.last_known_tools
    if lifecycle.state == "active":
        from .control_mcp_lifecycle import owned_tool_snapshot

        published = await owned_tool_snapshot(store, tenant_id, record.id)
        snapshot = published or snapshot
    # Rehydrate must never be able to refuse the process a start. The snapshot here
    # is ALREADY STORED, so raising cannot prevent bad data arriving - it can only
    # convert one unusable adapter into an unbootable kernel. Measured on the beelink
    # 2026-07-30: `opbox` publishes 633 verbs, MCP_MAX_TOOL_SNAPSHOT was 500, and the
    # kernel died at startup with "MCP tool snapshot is out of bounds" on every boot.
    # The bound belongs at INGEST (snapshot_from_response), where refusing is
    # meaningful because the data can still be rejected. Here we degrade: this one
    # adapter does not load, and everything else serves.
    try:
        consumer.apply_tool_snapshot(snapshot)
    except ValueError:
        log.exception(
            "adapter %s for tenant %s has an unusable stored tool snapshot "
            "(%d tools); skipping it rather than failing startup",
            record.id,
            tenant_id,
            len(snapshot),
        )
        return None
    stamp_mcp_consumer(consumer, record, lifecycle)
    loader.register(tenant_id, consumer)
    credentials.replace_adapter_credential_binding(
        tenant_id,
        record.id,
        await _credential_id(store, tenant_id, record),
    )
    return consumer


async def reconcile_mcp_adapter(
    store: Any,
    credentials: Any,
    loader: Any,
    tenant_id: str,
    record: Any,
) -> Any | None:
    """Return only a live MCP instance matching current durable authority."""
    lifecycle = await store.get_mcp_server_lifecycle(tenant_id, record.id)
    if lifecycle is None:
        loader.unload(tenant_id, record.id)
        credentials.replace_adapter_credential_binding(
            tenant_id, record.id, None
        )
        return None
    current = loader.peek(tenant_id, record.id)
    expected = _runtime_stamp(record, lifecycle)
    if current is not None and getattr(
        current, "_boltrig_mcp_runtime_stamp", None
    ) == expected:
        return current
    spec = consumer_spec(record.spec_ref)
    unstamped_matches = (
        current is not None
        and getattr(current, "runtime", None) == "mcp"
        and (
            getattr(current, "_rpc", None) is not None
            or (
                getattr(current, "_url", None) == spec["url"]
                and bool(current._transport.allow_internal)
                == spec["allow_internal"]
            )
        )
    )
    if unstamped_matches:
        current.activated = lifecycle.state == "active"
        current.apply_tool_snapshot(lifecycle.last_known_tools)
        stamp_mcp_consumer(current, record, lifecycle)
        credentials.replace_adapter_credential_binding(
            tenant_id,
            record.id,
            await _credential_id(store, tenant_id, record),
        )
        return current
    loader.unload(tenant_id, record.id)
    return await rehydrate_adapter_instance(
        store,
        credentials,
        loader,
        tenant_id,
        record,
        lifecycle=lifecycle,
    )
