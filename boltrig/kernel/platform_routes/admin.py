"""Admin Console (ADM): config get/put/history/rollback/export, credentials."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.models import BoltrigError
from ._shared import audit_authoring, can_author_route, platform_state, require_author


def register(app, P, K) -> None:
    @app.get("/v1/admin/config/{section}")
    async def get_config(section: str, request: Request, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        if not can_author_route(p):
            return JSONResponse({"status": "denied", "reason": "admin_forbidden"}, status_code=403)
        return JSONResponse({"section": section, "value": admin.section(section)})

    @app.put("/v1/admin/config/{section}")
    async def put_config(section: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        try:
            require_author(p)
            rev = await admin.update_section(section, body.get("value"), p.subject)
            await audit_authoring(k, p, "config.update", {"section": section, "revision": rev.id})
            return JSONResponse({"status": "ok", "section": section, "revision": rev.id})
        except (BoltrigError, ValueError) as e:
            code = getattr(e, "status_code", 400)
            return JSONResponse({"status": "error", "reason": str(e)}, status_code=code)

    @app.get("/v1/admin/config/{section}/history")
    async def config_history(section: str, request: Request, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None or not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        revs = await admin.history(section)
        return JSONResponse({"section": section, "revisions": [
            {"id": r.id, "version": r.version, "actor": r.actor, "rolled_back": r.rolled_back,
             "created_at": r.created_at.isoformat()} for r in revs]})

    @app.post("/v1/admin/config/{section}/rollback")
    async def config_rollback(section: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        try:
            require_author(p)
            value = await admin.rollback(section, int(body["revision_id"]), p.subject)
            await audit_authoring(k, p, "config.rollback", {"section": section, "to": body["revision_id"]})
            return JSONResponse({"status": "ok", "section": section, "value": value})
        except (BoltrigError, ValueError) as e:
            code = getattr(e, "status_code", 400)
            return JSONResponse({"status": "error", "reason": str(e)}, status_code=code)

    @app.post("/v1/admin/config/export")
    async def config_export(request: Request, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None or not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"manifest": admin.export_dict()})

    @app.get("/v1/admin/credentials")
    async def admin_credentials(request: Request, p=P) -> JSONResponse:
        admin = platform_state(request).get("admin")
        if admin is None or not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"credentials": admin.credential_refs()})  # refs only, never values
