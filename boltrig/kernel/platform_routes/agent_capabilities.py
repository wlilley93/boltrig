"""Author inventory and governed lifecycle for agent capability profiles."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.models import derive_familiar_genotype

from ._shared import require_author


def _view(capability: Any) -> dict[str, Any]:
    return {
        "name": capability.name,
        "runtime": capability.runtime,
        "supported_skills": capability.supported_skills,
        "max_depth": capability.max_depth,
        "is_ephemeral": capability.is_ephemeral,
        "cost_tier": capability.cost_tier,
        "model_endpoint": capability.model_endpoint,
        "vision_model_endpoint": capability.vision_model_endpoint,
        "source": capability.source,
        "is_active": capability.is_active,
        "status": "active" if capability.is_active else "retired",
        "familiar_genotype": derive_familiar_genotype(capability.name).as_view(),
    }


def register(app, P, K) -> None:
    @app.get("/v1/agent-capabilities")
    async def list_agent_capabilities(k=K, p=P) -> dict[str, Any]:
        require_author(p)
        capabilities = await k.store.list_all_capabilities(p.tenant_id)
        return {
            "agent_capabilities": [
                _view(item) for item in sorted(capabilities, key=lambda cap: cap.name)
            ]
        }

    async def lifecycle(
        name: str, action: str, request: Request, k: Any, p: Any
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            f"control.capability.{action}",
            {"name": name},
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/agent-capabilities/{name}/retire")
    async def retire_agent_capability(
        name: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await lifecycle(name, "retire", request, k, p)

    @app.post("/v1/agent-capabilities/{name}/restore")
    async def restore_agent_capability(
        name: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await lifecycle(name, "restore", request, k, p)
