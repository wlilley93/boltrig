"""Personal agents (PA) - delegated-only (SEC-30)."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
import uuid
from boltrig.models import PersonalAgent
from ._shared import audit_authoring, platform_state


def register(app, P, K) -> None:
    @app.post("/v1/me/agent")
    async def configure_personal_agent(body: dict, k=K, p=P) -> JSONResponse:
        agent = PersonalAgent(id=uuid.uuid4().hex, tenant_id=p.tenant_id, user_id=p.subject,
                              runtime=body.get("runtime", "pi-worker"), skills=body.get("skills", []))
        await k.store.upsert_personal_agent(agent)
        return JSONResponse({"status": "ok", "id": agent.id, "owner": p.subject})

    @app.post("/v1/me/agent/invoke")
    async def invoke_personal_agent(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        spawner = platform_state(request).get("spawner")
        agent = await k.store.get_personal_agent(p.tenant_id, p.subject)
        if spawner is None or agent is None:
            return JSONResponse({"error": "no_personal_agent"}, status_code=404)
        # delegated-only: on-behalf-of the owner, capped by the owner's grants (SEC-30)
        ctx = p.context(extra=body.get("context", {}))
        from dataclasses import replace

        ctx = replace(ctx, on_behalf_of=p.subject)
        result = await spawner.spawn(p.tenant_id, body.get("message", ""), list(agent.skills),
                                     {}, ctx, partial_on_budget=True, grant_ceiling=p.grants)
        await audit_authoring(k, p, "personal_agent.invoke", {"run_id": result.get("run_id")})
        return JSONResponse(result)
