"""Dispatch the governed external-MCP lifecycle state machine."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.models import InvocationContext

from .control_approval import require_unchanged_approval_context
from .control_mcp_mutations import execute_mcp_registration_mutation
from .control_safety import ControlConflict


def _approved_revision(context: InvocationContext) -> int:
    resource = context.extra.get("approval_resource_context")
    server = resource.get("mcp_server") if isinstance(resource, dict) else None
    revision = server.get("config_revision") if isinstance(server, dict) else None
    if type(revision) is not int or revision < 1:
        raise PermissionError("approved MCP configuration revision is missing")
    return revision


async def _dispatch_current_mcp(
    store: Any,
    loader: Any,
    registry: Any,
    credentials: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
    record: Any,
    lifecycle: Any,
    expected_revision: int,
) -> Result:
    from .control_mcp_lifecycle import (
        _activate,
        _deactivate,
        _probe,
        _transition,
    )

    if verb in {
        "control.mcp_server.update",
        "control.mcp_server.delete",
    }:
        return await execute_mcp_registration_mutation(
            store, loader, credentials, verb, params, context, record
        )
    if verb == "control.mcp_server.probe":
        if lifecycle.state == "retired":
            raise ControlConflict("retired MCP servers cannot be probed")
        return await _probe(
            store,
            loader,
            credentials,
            context,
            record,
            expected_config_revision=expected_revision,
        )
    if verb == "control.mcp_server.activate":
        if registry is None:
            return Result.failure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    "MCP adapter registry is unavailable",
                )
            )
        return await _activate(
            store,
            loader,
            registry,
            credentials,
            context,
            record,
            lifecycle,
            expected_config_revision=expected_revision,
        )
    if verb == "control.mcp_server.deactivate":
        return await _deactivate(store, loader, context, record, lifecycle)
    expected_state, new_state = (
        ("inactive", "retired")
        if verb == "control.mcp_server.retire"
        else ("retired", "inactive")
    )
    return await _transition(
        store,
        context,
        record,
        lifecycle,
        expected_state=expected_state,
        new_state=new_state,
    )


async def execute_mcp_lifecycle_dispatch(
    store: Any,
    loader: Any,
    registry: Any,
    credentials: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    from .control_mcp_lifecycle import (
        MCP_LIFECYCLE_VERBS,
        _server_state,
    )

    if verb not in MCP_LIFECYCLE_VERBS:
        return None
    await require_unchanged_approval_context(
        store, loader, verb, params, context
    )
    if loader is None or credentials is None:
        return Result.failure(
            AdapterError(
                ErrorClass.UNAVAILABLE,
                "MCP lifecycle collaborators are unavailable",
            )
        )
    expected_revision = _approved_revision(context)
    record, lifecycle = await _server_state(
        store, context.tenant_id, str(params["server_id"])
    )
    if lifecycle.config_revision != expected_revision:
        raise ControlConflict("MCP configuration changed before execution")
    return await _dispatch_current_mcp(
        store,
        loader,
        registry,
        credentials,
        verb,
        params,
        context,
        record,
        lifecycle,
        expected_revision,
    )


__all__ = ["execute_mcp_lifecycle_dispatch"]
