"""Governed external-MCP probing and recoverable lifecycle transitions."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from boltrig.adapters.base import Result
from boltrig.adapters.mcp_discovery import McpProbeResult
from boltrig.models import (
    CredentialResolution,
    InvocationContext,
    McpProbeReceipt,
    McpToolSnapshot,
    utcnow,
)

from boltrig.kernel.revertible import EffectLog

from .control_lifecycle import _drop_orphaned_nouns, _unpublish_owned_verbs
from .control_rehydrate import is_mcp_consumer, reconcile_mcp_adapter
from .control_safety import ControlConflict, ensure_activation_safe

MCP_LIFECYCLE_VERBS = frozenset(
    {
        "control.mcp_server.probe",
        "control.mcp_server.activate",
        "control.mcp_server.deactivate",
        "control.mcp_server.retire",
        "control.mcp_server.restore",
        "control.mcp_server.update",
        "control.mcp_server.delete",
    }
)

def snapshot_digest(tools: tuple[McpToolSnapshot, ...]) -> str:
    payload = [
        {
            "name": tool.name,
            "description": tool.description,
            "consequence": tool.consequence,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
        }
        for tool in tools
    ]
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


async def owned_tool_snapshot(
    store: Any, tenant_id: str, server_id: str
) -> tuple[McpToolSnapshot, ...]:
    tools: list[McpToolSnapshot] = []
    prefix = f"{server_id}."
    for verb in sorted(
        await store.list_all_verbs(tenant_id), key=lambda item: item.id
    ):
        binding = await store.get_binding(tenant_id, verb.id)
        if binding is None or binding.target_ref != server_id:
            continue
        tools.append(
            McpToolSnapshot(
                name=(
                    verb.id[len(prefix) :]
                    if verb.id.startswith(prefix)
                    else verb.id
                ),
                description=verb.description,
                consequence=verb.consequence.value,
                input_schema=verb.input_schema,
                output_schema=verb.output_schema,
            )
        )
    return tuple(tools)


async def _server_state(
    store: Any, tenant_id: str, server_id: str
) -> tuple[Any, Any]:
    record = await store.get_adapter(tenant_id, server_id)
    lifecycle = await store.get_mcp_server_lifecycle(tenant_id, server_id)
    if (
        record is None
        or not is_mcp_consumer(record)
        or lifecycle is None
    ):
        raise LookupError("MCP server not found")
    return record, lifecycle


async def _adapter(
    store: Any,
    loader: Any,
    credentials: Any,
    tenant_id: str,
    record: Any,
) -> Any:
    adapter = await reconcile_mcp_adapter(
        store, credentials, loader, tenant_id, record
    )
    if adapter is None or not hasattr(adapter, "probe"):
        raise ControlConflict("MCP server cannot be reconstructed for probing")
    return adapter


def _receipt_view(receipt: McpProbeReceipt) -> dict[str, Any]:
    return {
        "probe_id": receipt.probe_id,
        "checked_at": receipt.observed_at.isoformat(),
        "outcome": receipt.outcome,
        "failure_code": receipt.failure_code,
        "tool_count": receipt.tool_count,
    }


async def _probe_once(
    store: Any,
    loader: Any,
    credentials: Any,
    tenant_id: str,
    record: Any,
    *,
    expected_config_revision: int,
) -> tuple[McpProbeReceipt, tuple[McpToolSnapshot, ...]]:
    adapter = await _adapter(
        store, loader, credentials, tenant_id, record
    )
    try:
        credential = await credentials.resolve_for_adapter(
            tenant_id, record.id
        )
    except CredentialResolution:
        result = McpProbeResult(False, "credential_unavailable", ())
    else:
        result = await adapter.probe(credential)
    observed_at = utcnow()
    receipt = McpProbeReceipt(
        tenant_id=tenant_id,
        server_id=record.id,
        probe_id=f"mcp_probe_{uuid.uuid4().hex}",
        outcome="succeeded" if result.succeeded else "failed",
        failure_code=result.failure_code,
        observed_at=observed_at,
        tool_count=len(result.tools),
    )
    persisted = await store.record_mcp_probe_receipt(
        receipt,
        expected_config_revision=expected_config_revision,
        last_known_tools=result.tools if result.succeeded else None,
    )
    if persisted is None:
        raise ControlConflict("MCP configuration changed during probe")
    return receipt, result.tools


async def _probe(
    store: Any,
    loader: Any,
    credentials: Any,
    context: InvocationContext,
    record: Any,
    *,
    expected_config_revision: int,
) -> Result:
    receipt, _ = await _probe_once(
        store,
        loader,
        credentials,
        context.tenant_id,
        record,
        expected_config_revision=expected_config_revision,
    )
    return Result.success(
        {
            "id": record.id,
            "state": (
                await store.get_mcp_server_lifecycle(
                    context.tenant_id, record.id
                )
            ).state,
            "probe": _receipt_view(receipt),
        }
    )


async def _publish_activation(
    store: Any,
    registry: Any,
    context: InvocationContext,
    record: Any,
    adapter: Any,
    *,
    expected_revision: int,
) -> list[str]:
    registered: list[str] = []
    transitioned = None
    # Revertible effects (kernel/revertible.py): the registry records the
    # exact inverse of every noun/verb/binding AT APPLY TIME. The ownership
    # scan this replaces DELETED the adapter's pre-existing rows on a failed
    # re-activation instead of restoring them.
    effects = EffectLog()
    try:
        registered = await registry.register_adapter_verbs(
            context.tenant_id, adapter, effects=effects
        )
        transitioned = await store.set_mcp_server_lifecycle(
            context.tenant_id,
            record.id,
            expected_state="inactive",
            expected_config_revision=expected_revision,
            new_state="active",
            changed_at=utcnow(),
        )
        if transitioned is None:
            raise ControlConflict("MCP lifecycle changed during activation")
        reviewer = str(context.extra.get("approved_by") or "")
        if not reviewer:
            raise PermissionError(
                "MCP activation requires the recorded HITL reviewer"
            )
        adapter.review_and_activate(reviewer)
    except Exception:
        current = await store.get_mcp_server_lifecycle(
            context.tenant_id, record.id
        )
        # A losing CAS must not unpublish/deactivate an identical winner.
        if (
            transitioned is None
            and current is not None
            and current.state == "active"
        ):
            raise
        # LIFO compensation from the log: added rows removed, displaced rows
        # restored, nouns this attempt created dropped, shared nouns untouched.
        await effects.revert()
        if getattr(adapter, "activated", False):
            adapter.activated = False
        if current is not None and current.state == "active":
            await store.set_mcp_server_lifecycle(
                context.tenant_id,
                record.id,
                expected_state="active",
                expected_config_revision=current.config_revision,
                new_state="inactive",
                changed_at=utcnow(),
            )
        raise
    return registered


async def _activate(
    store: Any,
    loader: Any,
    registry: Any,
    credentials: Any,
    context: InvocationContext,
    record: Any,
    lifecycle: Any,
    *,
    expected_config_revision: int | None = None,
) -> Result:
    if lifecycle.state != "inactive":
        raise ControlConflict("MCP server must be inactive before activation")
    if lifecycle.tools_observed_at is None:
        raise ControlConflict("MCP server must be probed before activation")
    approved_digest = snapshot_digest(lifecycle.last_known_tools)
    expected_revision = (
        lifecycle.config_revision
        if expected_config_revision is None
        else expected_config_revision
    )
    receipt, discovered = await _probe_once(
        store,
        loader,
        credentials,
        context.tenant_id,
        record,
        expected_config_revision=expected_revision,
    )
    if receipt.outcome != "succeeded":
        raise ControlConflict(
            f"MCP activation probe failed ({receipt.failure_code})"
        )
    if snapshot_digest(discovered) != approved_digest:
        raise ControlConflict(
            "MCP tool catalogue changed; review the new snapshot and retry"
        )
    adapter = await _adapter(store, loader, credentials, context.tenant_id, record)
    adapter.apply_tool_snapshot(discovered)
    await ensure_activation_safe(store, context.tenant_id, record.id, adapter)
    registered = await _publish_activation(
        store,
        registry,
        context,
        record,
        adapter,
        expected_revision=expected_revision,
    )
    return Result.success(
        {
            "id": record.id,
            "state": "active",
            "activated": True,
            "verbs": registered,
            "probe": _receipt_view(receipt),
        }
    )


async def _deactivate(
    store: Any,
    loader: Any,
    context: InvocationContext,
    record: Any,
    lifecycle: Any,
) -> Result:
    if lifecycle.state != "active":
        raise ControlConflict("MCP server is not active")
    transitioned = await store.set_mcp_server_lifecycle(
        context.tenant_id,
        record.id,
        expected_state="active",
        expected_config_revision=lifecycle.config_revision,
        new_state="inactive",
        changed_at=utcnow(),
    )
    if transitioned is None:
        raise ControlConflict("MCP lifecycle changed during deactivation")
    adapter = loader.peek(context.tenant_id, record.id)
    if adapter is not None:
        adapter.activated = False
    removed = await _unpublish_owned_verbs(
        store, context.tenant_id, record.id
    )
    await _drop_orphaned_nouns(store, context.tenant_id, removed)
    return Result.success(
        {
            "id": record.id,
            "state": "inert",
            "activated": False,
            "verbs": [verb.id for verb in removed],
        }
    )


async def _transition(
    store: Any,
    context: InvocationContext,
    record: Any,
    lifecycle: Any,
    *,
    expected_state: str,
    new_state: str,
) -> Result:
    if lifecycle.state != expected_state:
        raise ControlConflict(
            f"MCP server must be {expected_state} for this transition"
        )
    transitioned = await store.set_mcp_server_lifecycle(
        context.tenant_id,
        record.id,
        expected_state=expected_state,
        expected_config_revision=lifecycle.config_revision,
        new_state=new_state,
        changed_at=utcnow(),
    )
    if transitioned is None:
        raise ControlConflict("MCP lifecycle changed during transition")
    return Result.success(
        {
            "id": record.id,
            "state": "inert" if new_state == "inactive" else new_state,
            "activated": False,
        }
    )


async def execute_mcp_lifecycle_operation(
    store: Any,
    loader: Any,
    registry: Any,
    credentials: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    from .control_mcp_lifecycle_dispatch import (
        execute_mcp_lifecycle_dispatch,
    )

    return await execute_mcp_lifecycle_dispatch(
        store, loader, registry, credentials, verb, params, context
    )
