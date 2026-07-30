"""Governed model-endpoint mutations."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Result
from boltrig.models import InvocationContext, ModelEndpoint

from .control_approval import require_unchanged_approval_context


def _active_status(endpoint) -> str:
    return "active" if endpoint is None or endpoint.is_active else "retired"


async def _validated_fallback(store, tenant_id, endpoint_id, params):
    fallback_id = str(params.get("fallback") or "").strip() or None
    if fallback_id == endpoint_id:
        from .control_safety import ControlConflict

        raise ControlConflict("a model endpoint cannot fall back to itself")
    if fallback_id is None:
        return None
    fallback = await store.get_model_endpoint(tenant_id, fallback_id)
    if fallback is None:
        raise LookupError("fallback model endpoint not found")
    if not fallback.is_active:
        from .control_safety import ControlConflict

        raise ControlConflict("fallback model endpoint is retired")
    return fallback_id


async def execute_model_endpoint_operation(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    if not verb.startswith("control.model_endpoint."):
        return None
    await require_unchanged_approval_context(store, loader, verb, params, context)
    if verb in {
        "control.model_endpoint.retire",
        "control.model_endpoint.restore",
    }:
        endpoint = await store.set_model_endpoint_active(
            context.tenant_id,
            params["id"],
            verb.endswith(".restore"),
        )
        if endpoint is None:
            raise LookupError("model endpoint not found")
        return Result.success(
            {
                "id": endpoint.id,
                "model_endpoint_status": _active_status(endpoint),
            }
        )
    if verb != "control.model_endpoint.upsert":
        return None

    fallback_id = await _validated_fallback(
        store, context.tenant_id, params["id"], params
    )
    endpoint = ModelEndpoint(
        id=params["id"],
        tenant_id=context.tenant_id,
        kind=params["kind"],
        model=params["model"],
        base_url=params.get("base_url"),
        fallback=fallback_id,
        data_class=params.get("data_class", "standard"),
    )
    await store.upsert_model_endpoint(endpoint)
    current = await store.get_model_endpoint(context.tenant_id, endpoint.id)
    return Result.success(
        {
            "upserted": "model_endpoint",
            "id": endpoint.id,
            "model_endpoint_status": _active_status(current),
        }
    )
