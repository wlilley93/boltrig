"""Skill inventory and exact author detail routes."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from boltrig.identity.rbac import can_author

from ._shared import require_author
from .authored_registry_views import skill_view


def register_skill_read_routes(app, P, K) -> None:
    @app.get("/v1/skills")
    async def list_skills(k=K, p=P) -> dict:
        skills = (
            await k.store.list_all_skills(p.tenant_id)
            if can_author(p.role)
            else await k.store.list_skills(p.tenant_id)
        )
        return {"skills": [skill_view(skill) for skill in skills]}

    async def detail(skill_id: str, k, p) -> JSONResponse:
        require_author(p)
        skill = await k.store.get_skill_any(p.tenant_id, skill_id)
        if skill is None:
            return JSONResponse(
                {"status": "error", "reason": "not_found"},
                status_code=404,
            )
        return JSONResponse({"skill": skill_view(skill, detail=True)})

    @app.get("/v1/skills/{skill_id}")
    async def get_skill(skill_id: str, k=K, p=P) -> JSONResponse:
        return await detail(skill_id, k, p)

    # Skill ids are hierarchical (for example ``authoring/control-plane``).
    @app.get("/v1/skills/{skill_id:path}")
    async def get_nested_skill(skill_id: str, k=K, p=P) -> JSONResponse:
        return await detail(skill_id, k, p)
