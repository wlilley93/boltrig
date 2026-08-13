"""Governed agent-capability profile mutations."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Result
from boltrig.models import AgentCapability, InvocationContext

from .capability_model_routes import (
    CapabilityRouteValidationError,
    validated_capability_routes,
)
from .control_approval import require_unchanged_approval_context
from .control_safety import ControlConflict


async def execute_capability_operation(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    if verb not in {
        "control.capability.upsert",
        "control.capability.retire",
        "control.capability.restore",
    }:
        return None
    await require_unchanged_approval_context(store, loader, verb, params, context)
    if verb != "control.capability.upsert":
        capability = await store.set_capability_active(
            context.tenant_id,
            params["name"],
            verb.endswith(".restore"),
        )
        if capability is None:
            raise LookupError("capability not found")
        return Result.success(
            {
                "id": capability.name,
                "capability_status": (
                    "active" if capability.is_active else "retired"
                ),
            }
        )

    try:
        endpoint_id, vision_endpoint_id, model_routes, _ = (
            await validated_capability_routes(store, context.tenant_id, params)
        )
    except CapabilityRouteValidationError as error:
        if error.missing:
            raise LookupError(str(error)) from None
        raise ControlConflict(str(error)) from None
    capability = AgentCapability(
        name=params["name"],
        tenant_id=context.tenant_id,
        runtime=params["runtime"],
        supported_skills=params.get("supported_skills", ["*"]),
        max_depth=int(params.get("max_depth", 1)),
        is_ephemeral=bool(params.get("is_ephemeral", True)),
        cost_tier=params.get("cost_tier", "standard"),
        model_endpoint=endpoint_id,
        vision_model_endpoint=vision_endpoint_id,
        model_routes=model_routes,
        source="control-plane",
    )
    await store.upsert_capability(capability, preserve_status=True)
    current = next(
        item
        for item in await store.list_all_capabilities(context.tenant_id)
        if item.name == capability.name
    )
    return Result.success(
        {
            "upserted": "capability",
            "id": capability.name,
            "capability_status": "active" if current.is_active else "retired",
        }
    )
