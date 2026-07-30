"""Admin Console (ADM): config get/put/history/rollback/export, credentials."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.kernel.control_routes import dispatch_control_route
from ._shared import can_author_route, platform_state, require_author


def _register_get_config(app, P, K) -> None:
    @app.get("/v1/admin/config/{section}")
    async def get_config(section: str, request: Request, k=K, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        if not can_author_route(p):
            return JSONResponse({"status": "denied", "reason": "admin_forbidden"}, status_code=403)
        value = admin.section(section)
        if section == "hierarchy":
            from boltrig.config.permanent_fleet import overlay_permanent_fleet_export

            manifest = await overlay_permanent_fleet_export(
                k.store, p.tenant_id, admin.export_dict()
            )
            value = manifest.get("hierarchy")
        return JSONResponse({"section": section, "value": value})


def _register_put_config(app, P, K) -> None:
    @app.put("/v1/admin/config/{section}")
    async def put_config(section: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        try:
            require_author(p)
            output, pending = await dispatch_control_route(
                k,
                p,
                "control.config.upsert",
                {"section": section, **body},
                request=request,
            )
            if pending is not None:
                return pending
            return JSONResponse({"status": "ok", **(output or {})})
        except ValueError:
            # BoltrigError propagates to the central handler (canonical envelope);
            # a bare ValueError never leaks internal text as the client reason.
            return JSONResponse({"status": "error", "reason": "invalid config"}, status_code=400)


def _register_config_history(app, P, K) -> None:
    @app.get("/v1/admin/config/{section}/history")
    async def config_history(section: str, request: Request, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None or not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        revs = await admin.history(section)
        return JSONResponse(
            {
                "section": section,
                "revisions": [
                    {
                        "id": r.id,
                        "version": r.version,
                        "actor": r.actor,
                        "rolled_back": r.rolled_back,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in revs
                ],
            }
        )


def _register_config_rollback(app, P, K) -> None:
    @app.post("/v1/admin/config/{section}/rollback")
    async def config_rollback(section: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        try:
            require_author(p)
            output, pending = await dispatch_control_route(
                k,
                p,
                "control.config.rollback",
                {"section": section, **body},
                request=request,
            )
            if pending is not None:
                return pending
            return JSONResponse({"status": "ok", **(output or {})})
        except ValueError:
            return JSONResponse({"status": "error", "reason": "invalid config"}, status_code=400)


def _register_config_inspection(app, P, K) -> None:
    @app.post("/v1/admin/config/export")
    async def config_export(request: Request, k=K, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None or not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        from boltrig.config.permanent_fleet import overlay_permanent_fleet_export

        manifest = await overlay_permanent_fleet_export(k.store, p.tenant_id, admin.export_dict())
        return JSONResponse({"manifest": manifest})

    @app.get("/v1/admin/credentials")
    async def admin_credentials(request: Request, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None or not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"credentials": admin.credential_refs()})  # refs only, never values


def register(app, P, K) -> None:
    _register_get_config(app, P, K)
    _register_put_config(app, P, K)
    _register_config_history(app, P, K)
    _register_config_rollback(app, P, K)
    _register_config_inspection(app, P, K)
