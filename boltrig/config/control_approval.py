"""Mutable-resource fingerprints included in governed control approvals."""

from __future__ import annotations

from typing import Any

from boltrig.models import AdapterFailure, InvocationContext
from boltrig.workflows.snapshot import workflow_snapshot_digest

_WORKFLOW_ACTIONS = frozenset(
    {
        "control.workflow.schedule",
        "control.workflow.trigger",
        "control.workflow.execute",
    }
)


async def _workflow_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    workflow_id = params["workflow_id"]
    workflow = next(
        (
            item
            for item in await store.list_workflows(context.tenant_id)
            if item.id == workflow_id
            and (item.workspace_id is None or item.workspace_id == context.workspace_id)
        ),
        None,
    )
    if workflow is None:
        raise AdapterFailure(
            "workflow not found", status_code=404, reason="control_resource_not_found"
        )
    return {"workflow_sha256": workflow_snapshot_digest(workflow)}


async def _adapter_context(
    store: Any, loader: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    if loader is None:
        raise AdapterFailure(
            "adapter loader not wired",
            status_code=503,
            reason="control_dependency_unavailable",
        )
    adapter = await loader.get(context.tenant_id, params["adapter_id"])
    if adapter is None:
        raise AdapterFailure(
            "adapter not found", status_code=404, reason="control_resource_not_found"
        )
    record = await store.get_adapter(context.tenant_id, params["adapter_id"])
    verbs = [
        {
            "id": item.verb_id,
            "input": item.input_schema,
            "output": item.output_schema,
            "consequence": item.consequence,
        }
        for item in adapter.describe()
    ]
    return {
        "adapter": {
            "id": adapter.id,
            "version": adapter.version,
            "runtime": adapter.runtime,
            "source": getattr(adapter, "source", None),
            "activated": bool(record and record.activated),
            "verbs": verbs,
        }
    }


async def control_approval_context(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any] | None:
    """Return state that must remain identical between approval and execution."""
    if verb in _WORKFLOW_ACTIONS:
        return await _workflow_context(store, params, context)
    if verb == "control.adapter.activate":
        return await _adapter_context(store, loader, params, context)
    return None


async def require_unchanged_approval_context(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> None:
    """Close the gate-to-mutation race by rechecking the approved resource state."""
    fingerprint = context.extra.get("approval_request_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise PermissionError("exact approval evidence is missing")
    expected = context.extra.get("approval_resource_context")
    from boltrig.kernel.hitl import canonical_approval_value

    current = canonical_approval_value(
        await control_approval_context(store, loader, verb, params, context)
    )
    if expected != current:
        raise PermissionError("approved resource changed before execution")
