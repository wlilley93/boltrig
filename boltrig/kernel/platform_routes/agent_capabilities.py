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
        "model_routes": capability.model_routes,
        "source": capability.source,
        "is_active": capability.is_active,
        "status": "active" if capability.is_active else "retired",
        # NULL means org-wide: every workspace sees this profile (0083). The UI
        # needs to tell a shared agent from one this workspace authored, because
        # a workspace-scoped profile of the same name SHADOWS the org-wide one.
        "workspace_id": capability.workspace_id,
        "scope": "organisation" if capability.workspace_id is None else "workspace",
        "familiar_genotype": derive_familiar_genotype(capability.name).as_view(),
    }


def register(app, P, K) -> None:
    @app.get("/v1/agent-capabilities")
    async def list_agent_capabilities(k=K, p=P) -> dict[str, Any]:
        require_author(p)
        # An author operating INSIDE a workspace sees that workspace's roster
        # plus the org-wide profiles - the same union a spawn there can route to,
        # so the inventory and the routing answer cannot disagree. An author at
        # org scope sees every row, which is the admin inventory read; the
        # response says which of the two it is rather than leaving the caller to
        # infer it from the rows.
        workspace_id = p.active_workspace_id
        capabilities = await k.store.list_all_capabilities(
            p.tenant_id,
            workspace_id=workspace_id,
            enforce_workspace=workspace_id is not None,
        )
        return {
            "active_workspace_id": workspace_id,
            "scope": "organisation" if workspace_id is None else "workspace",
            "agent_capabilities": [
                _view(item)
                for item in sorted(
                    capabilities, key=lambda cap: (cap.workspace_id or "", cap.name)
                )
            ],
        }

    async def lifecycle(
        name: str,
        action: str,
        request: Request,
        k: Any,
        p: Any,
        workspace_id: str | None,
    ) -> JSONResponse:
        require_author(p)
        # workspace_id is a HINT the verb re-decides. A caller already inside a
        # workspace can only name their own (config/capability_scope.py refuses
        # the rest), so passing it here can widen nothing.
        params: dict[str, Any] = {"name": name}
        if workspace_id:
            params["workspace_id"] = workspace_id
        output, pending = await dispatch_control_route(
            k,
            p,
            f"control.capability.{action}",
            params,
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/agent-capabilities/{name}/retire")
    async def retire_agent_capability(
        name: str, request: Request, workspace_id: str | None = None, k=K, p=P
    ) -> JSONResponse:
        return await lifecycle(name, "retire", request, k, p, workspace_id)

    @app.post("/v1/agent-capabilities/{name}/restore")
    async def restore_agent_capability(
        name: str, request: Request, workspace_id: str | None = None, k=K, p=P
    ) -> JSONResponse:
        return await lifecycle(name, "restore", request, k, p, workspace_id)
