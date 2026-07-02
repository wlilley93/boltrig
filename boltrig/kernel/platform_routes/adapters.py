"""Adapter Studio (ADS): generate, source, activate, MCP register, inventory."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.config.control_plane import register_mcp_consumer
from ._shared import audit_authoring, require_author


def register(app, P, K) -> None:
    @app.post("/v1/adapters/generate")
    async def gen_adapter(body: dict, k=K, p=P) -> JSONResponse:
        from boltrig.adapters.generator import generate_adapter_from_spec

        require_author(p)
        gen = generate_adapter_from_spec(body["spec"], adapter_id=body["adapter_id"])
        k.loader.register(p.tenant_id, gen)  # loaded but inert until activated
        await audit_authoring(k, p, "adapter.generate", {"id": body["adapter_id"], "activated": False})
        return JSONResponse({"status": "ok", "id": gen.id, "activated": gen.activated,
                             "verbs": [v.verb_id for v in gen.describe()]})

    @app.get("/v1/adapters/{adapter_id}/source")
    async def adapter_source(adapter_id: str, request: Request, k=K, p=P) -> JSONResponse:
        adapter = await k.loader.get(p.tenant_id, adapter_id)
        if adapter is None or not hasattr(adapter, "render_source"):
            return JSONResponse({"error": "no_source"}, status_code=404)
        return JSONResponse({"id": adapter_id, "source": adapter.render_source()})

    @app.post("/v1/adapters/{adapter_id}/activate")
    async def activate_adapter(adapter_id: str, body: dict, k=K, p=P) -> JSONResponse:
        require_author(p)
        adapter = await k.loader.get(p.tenant_id, adapter_id)
        if adapter is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        reviewer = body.get("reviewer") or p.subject
        if hasattr(adapter, "review_and_activate"):
            adapter.review_and_activate(reviewer)
        verbs = await k.registry.register_adapter_verbs(p.tenant_id, adapter)  # bind only now
        await audit_authoring(k, p, "adapter.activate", {"id": adapter_id, "reviewer": reviewer})
        return JSONResponse({"status": "ok", "id": adapter_id, "verbs": verbs})

    @app.post("/v1/mcp/servers")
    async def register_mcp_server(body: dict, k=K, p=P) -> JSONResponse:
        require_author(p)
        register_mcp_consumer(k.loader, p.tenant_id, body)  # inert pending review (SEC-22)
        await audit_authoring(k, p, "mcp.register", {"id": body["id"], "activated": False})
        return JSONResponse({"status": "ok", "id": body["id"], "activated": False})

    @app.get("/v1/adapters")
    async def adapter_inventory(k=K, p=P) -> dict:
        await k.loader.refresh_health()
        records = await k.store.list_adapters(p.tenant_id)
        return {"adapters": [{"id": a.id, "runtime": a.runtime, "version": a.version,
                              "source": a.source, "activated": a.activated,
                              "health": k.loader.health_of(p.tenant_id, a.id)} for a in records]}
