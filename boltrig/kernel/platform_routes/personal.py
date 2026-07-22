"""Personal agents (PA) - delegated-only (SEC-30)."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
import uuid
from boltrig.models import PersonalAgent
from ._shared import audit_authoring, platform_state

# Runtime names a worker capability. Codex is the only target agent runtime
# (decision 0012); script is the deterministic non-agent fallback. Everything
# else (pi/hermes/opencode/rivet and the old "*-worker" capability names) is
# staged-cutover residue and is refused at intake rather than recorded.
_DEFAULT_RUNTIME = "codex"
_SUPPORTED_RUNTIMES = frozenset({"codex", "script"})


def register(app, P, K) -> None:
    @app.post("/v1/me/agent")
    async def configure_personal_agent(body: dict, k=K, p=P) -> JSONResponse:
        runtime = body.get("runtime", _DEFAULT_RUNTIME)
        if not isinstance(runtime, str) or runtime.strip() not in _SUPPORTED_RUNTIMES:
            return JSONResponse({"status": "error", "reason": "invalid runtime"},
                                status_code=400)
        agent = PersonalAgent(id=uuid.uuid4().hex, tenant_id=p.tenant_id, user_id=p.subject,
                              runtime=runtime.strip(), skills=body.get("skills", []))
        await k.store.upsert_personal_agent(agent)
        return JSONResponse({"status": "ok", "id": agent.id, "owner": p.subject})

    @app.get("/v1/me/agent")
    async def get_personal_agent(k=K, p=P) -> JSONResponse:
        agent = await k.store.get_personal_agent(p.tenant_id, p.subject)
        if agent is None:
            return JSONResponse({"error": "no_personal_agent"}, status_code=404)
        return JSONResponse(
            {"id": agent.id, "runtime": agent.runtime, "skills": list(agent.skills)}
        )

    @app.delete("/v1/me/agent")
    async def delete_personal_agent(k=K, p=P) -> JSONResponse:
        deleted = await k.store.delete_personal_agent(p.tenant_id, p.subject)
        if not deleted:
            return JSONResponse({"error": "no_personal_agent"}, status_code=404)
        await audit_authoring(k, p, "personal_agent.delete", {})
        return JSONResponse({"status": "ok", "deleted": True})

    @app.post("/v1/me/agent/invoke")
    async def invoke_personal_agent(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        spawner = platform_state(request).get("spawner")
        if spawner is None:
            return JSONResponse({"error": "spawner_unavailable"}, status_code=503)
        agent = await k.store.get_personal_agent(p.tenant_id, p.subject)
        if agent is None:
            return JSONResponse({"error": "no_personal_agent"}, status_code=404)
        # delegated-only: on-behalf-of the owner, capped by the owner's grants (SEC-30)
        ctx = p.context(extra=body.get("context", {}))
        from dataclasses import replace

        ctx = replace(ctx, on_behalf_of=p.subject)
        result = await spawner.spawn(p.tenant_id, body.get("message", ""), list(agent.skills),
                                     {}, ctx, partial_on_budget=True, grant_ceiling=p.grants)
        await audit_authoring(k, p, "personal_agent.invoke", {"run_id": result.get("run_id")})
        return JSONResponse(result)
