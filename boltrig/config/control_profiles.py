"""Governed capability and model-endpoint operation composition."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Result
from boltrig.models import InvocationContext

from .control_capability_profiles import execute_capability_operation
from .control_model_endpoints import execute_model_endpoint_operation


async def execute_profile_operation(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
    *,
    model_catalogue: Any = None,
) -> Result | None:
    capability = await execute_capability_operation(
        store, loader, verb, params, context
    )
    if capability is not None:
        return capability
    return await execute_model_endpoint_operation(
        store, loader, verb, params, context, model_catalogue=model_catalogue
    )
