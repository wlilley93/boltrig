"""Adapter Studio (ADS): generate, source, activate, MCP register, inventory."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.kernel.control_routes import dispatch_control_route
from ._shared import require_author


def register(app, P, K) -> None:
    @app.post("/v1/adapters/generate")
    async def gen_adapter(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.adapter.generate", body, request=request
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.get("/v1/adapters/{adapter_id}/source")
    async def adapter_source(adapter_id: str, request: Request, k=K, p=P) -> JSONResponse:
        adapter = await k.loader.get(p.tenant_id, adapter_id)
        if adapter is None or not hasattr(adapter, "render_source"):
            return JSONResponse({"error": "no_source"}, status_code=404)
        return JSONResponse({"id": adapter_id, "source": adapter.render_source()})

    @app.post("/v1/adapters/{adapter_id}/activate")
    async def activate_adapter(
        adapter_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.adapter.activate",
            {"adapter_id": adapter_id, **body},
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/mcp/servers")
    async def register_mcp_server(
        body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.mcp_server.register", body, request=request
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.get("/v1/adapters")
    async def adapter_inventory(k=K, p=P) -> dict:
        await k.loader.refresh_health()
        records = await k.store.list_adapters(p.tenant_id)
        return {"adapters": [{"id": a.id, "runtime": a.runtime, "version": a.version,
                              "source": a.source, "activated": a.activated,
                              "health": k.loader.health_of(p.tenant_id, a.id)} for a in records]}
