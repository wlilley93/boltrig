"""Skill Studio (SKS) routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.config.control_plane import upsert_skill_record
from ._shared import audit_authoring, platform_state, require_author


def register(app, P, K) -> None:
    @app.get("/v1/skills")
    async def list_skills(k=K, p=P) -> dict:
        # Use the public store method - the old getattr(_skills) only existed on the
        # in-memory store, so this list rendered empty on Postgres.
        skills = await k.store.list_skills(p.tenant_id)
        return {"skills": [{"id": s.id, "version": s.version, "extends": s.extends,
                            "tool_grants": s.tool_grants, "locale": s.locale} for s in skills]}

    @app.post("/v1/skills")
    async def upsert_skill(body: dict, k=K, p=P) -> JSONResponse:
        require_author(p)
        skill = await upsert_skill_record(k.store, p.tenant_id, body)
        await audit_authoring(k, p, "skill.upsert", {"id": skill.id, "version": skill.version})
        return JSONResponse({"status": "ok", "id": skill.id, "version": skill.version})

    @app.post("/v1/skills/{skill_id}/test-spawn")
    async def test_spawn(skill_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # runs under the AUTHOR's grants (ceiling) - never escalates (SEC-29, C4)
        plat = platform_state(request)
        spawner = plat.get("spawner")
        if spawner is None:
            return JSONResponse({"error": "spawner_unavailable"}, status_code=503)
        require_author(p)
        ctx = p.context(extra=body.get("context", {}))
        result = await spawner.spawn(
            p.tenant_id, body.get("task", f"test {skill_id}"), [skill_id], {}, ctx,
            partial_on_budget=True, grant_ceiling=p.grants,
        )
        await audit_authoring(k, p, "skill.test_spawn", {"skill": skill_id, "run_id": result.get("run_id")})
        return JSONResponse(result)
