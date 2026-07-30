"""Governed skill authoring, lifecycle, and test-spawn routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import audit_authoring, platform_state, require_author


async def _lifecycle(skill_id, action, request, kernel, principal) -> JSONResponse:
    require_author(principal)
    output, pending = await dispatch_control_route(
        kernel,
        principal,
        f"control.skill.{action}",
        {"id": skill_id},
        request=request,
    )
    return pending or JSONResponse({"status": "ok", **(output or {})})


async def _spawn(skill_id, body, request, kernel, principal) -> JSONResponse:
    spawner = platform_state(request).get("spawner")
    if spawner is None:
        return JSONResponse({"error": "spawner_unavailable"}, status_code=503)
    require_author(principal)
    result = await spawner.spawn(
        principal.tenant_id,
        body.get("task", f"test {skill_id}"),
        [skill_id],
        {},
        principal.context(extra=body.get("context", {})),
        partial_on_budget=True,
        grant_ceiling=principal.grants,
    )
    await audit_authoring(
        kernel,
        principal,
        "skill.test_spawn",
        {"skill": skill_id, "run_id": result.get("run_id")},
    )
    return JSONResponse(result)


def _register_upsert(app, P, K) -> None:
    @app.post("/v1/skills")
    async def upsert_skill(
        body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.skill.upsert", body, request=request
        )
        return pending or JSONResponse({"status": "ok", **(output or {})})


def _register_lifecycle(app, P, K) -> None:
    @app.post("/v1/skills/{skill_id}/archive")
    async def archive_skill(
        skill_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _lifecycle(skill_id, "archive", request, k, p)

    @app.post("/v1/skills/{skill_id}/restore")
    async def restore_skill(
        skill_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _lifecycle(skill_id, "restore", request, k, p)

    @app.post("/v1/skills/{skill_id:path}/archive")
    async def archive_nested_skill(
        skill_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _lifecycle(skill_id, "archive", request, k, p)

    @app.post("/v1/skills/{skill_id:path}/restore")
    async def restore_nested_skill(
        skill_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _lifecycle(skill_id, "restore", request, k, p)


def _register_test_spawn(app, P, K) -> None:
    @app.post("/v1/skills/{skill_id}/test-spawn")
    async def test_spawn(
        skill_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _spawn(skill_id, body, request, k, p)

    @app.post("/v1/skills/{skill_id:path}/test-spawn")
    async def test_spawn_nested_skill(
        skill_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _spawn(skill_id, body, request, k, p)


def register_skill_write_routes(app, P, K) -> None:
    _register_upsert(app, P, K)
    _register_lifecycle(app, P, K)
    _register_test_spawn(app, P, K)
