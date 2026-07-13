"""Hatchet/local task wiring for memory projection catch-up."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from boltrig.models import TenantIsolation

TASK_MEMORY_PROJECTION = "boltrig-memory-projection"


class MemoryProjectionInput(BaseModel):
    """Pure-data input for one memory projection write/delete."""

    tenant_id: str
    projection_id: str
    operation: str
    row_id: str
    ctx_envelope: dict[str, Any]
    fact: dict[str, Any] | None = None
    fact_id: str | None = None
    projection_ref: str | None = None


async def memory_projection_body(kernel: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one queued projection operation through the configured memory fanout."""
    env = payload.get("ctx_envelope") or {}
    if payload["tenant_id"] != env.get("tenant_id"):
        raise TenantIsolation(
            f"projection payload tenant '{payload['tenant_id']}' != "
            f"envelope tenant '{env.get('tenant_id')}'"
        )
    adapter = kernel.loader.peek(payload["tenant_id"], "memory")
    fanout = getattr(adapter, "_projections", None)
    process = getattr(fanout, "process", None)
    if not callable(process):
        raise RuntimeError("memory projection task requested but no queued fanout is wired")
    return await process(payload)


def register_local_memory_projection_task(executor: Any, kernel: Any) -> None:
    """Register the projection body on the local executor seam."""
    register = getattr(executor, "register_task", None)
    if register is None:
        return

    async def _memory_projection(payload: dict[str, Any]) -> dict[str, Any]:
        return await memory_projection_body(kernel, payload)

    register(TASK_MEMORY_PROJECTION, _memory_projection)


def register_hatchet_memory_projection_task(
    hatchet: Any,
    resources: Any,
) -> dict[str, Any]:
    """Register the projection body on a live Hatchet client."""

    @hatchet.task(name=TASK_MEMORY_PROJECTION, input_validator=MemoryProjectionInput)
    async def memory_projection(inp: MemoryProjectionInput, ctx) -> dict:  # noqa: ARG001
        res = await resources()
        return await memory_projection_body(res["kernel"], inp.model_dump())

    return {TASK_MEMORY_PROJECTION: memory_projection}
