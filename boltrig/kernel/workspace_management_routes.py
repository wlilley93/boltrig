"""Caller-scoped workspace record and membership management routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.models import WORKSPACE_ROLES


def _register_workspace_record_routes(
    app, P, K, audit, require_admin, authorize, workspace_view
) -> None:
    @app.get("/v1/workspaces")
    async def list_my_workspaces(k=K, p=P) -> JSONResponse:
        workspaces = await k.store.list_workspaces_for_user(
            p.tenant_id, p.subject
        )
        return JSONResponse(
            {"workspaces": [workspace_view(item) for item in workspaces]}
        )

    @app.post("/v1/workspaces")
    async def create_workspace(
        body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_admin(p)
        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse(
                {"status": "error", "reason": "name is required"}, status_code=400
            )
        params = {"name": name}
        if isinstance(body.get("settings"), dict):
            params["settings"] = body["settings"]
        output, pending = await dispatch_control_route(
            k, p, "control.workspace.create", params, request=request
        )
        if pending is not None:
            return pending
        workspace = (output or {}).get("workspace", {})
        await audit(
            k,
            p,
            "workspace.create",
            {
                "workspace_id": workspace.get("id"),
                "slug": workspace.get("slug"),
            },
        )
        return JSONResponse({"status": "ok", "workspace": workspace})

    @app.patch("/v1/workspaces/{workspace_id}")
    async def update_workspace(
        workspace_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        _, denied = await authorize(k, p, workspace_id)
        if denied is not None:
            return denied
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.workspace.update",
            {"workspace_id": workspace_id, **body},
            request=request,
        )
        if pending is not None:
            return pending
        workspace = (output or {}).get("workspace", {})
        await audit(
            k,
            p,
            "workspace.update",
            {"workspace_id": workspace_id, "status": workspace.get("status")},
        )
        return JSONResponse({"status": "ok", "workspace": workspace})


def _register_workspace_member_read_route(
    app, P, K, admin_roles, member_view
) -> None:
    @app.get("/v1/workspaces/{workspace_id}/members")
    async def list_workspace_members(
        workspace_id: str, k=K, p=P
    ) -> JSONResponse:
        if await k.store.get_workspace(p.tenant_id, workspace_id) is None:
            return JSONResponse(
                {"status": "error", "reason": "not_found"}, status_code=404
            )
        if p.role not in admin_roles:
            member = await k.store.get_workspace_member(
                p.tenant_id, workspace_id, p.subject
            )
            if member is None:
                return JSONResponse(
                    {
                        "status": "denied",
                        "reason": "not a member of that workspace",
                    },
                    status_code=403,
                )
        members = await k.store.list_workspace_members(p.tenant_id, workspace_id)
        return JSONResponse({"members": [member_view(item) for item in members]})


def _register_workspace_member_write_routes(
    app, P, K, audit, authorize
) -> None:
    @app.post("/v1/workspaces/{workspace_id}/members")
    async def add_workspace_member(
        workspace_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        _, denied = await authorize(k, p, workspace_id)
        if denied is not None:
            return denied
        user_id = (body.get("user_id") or "").strip()
        role = (body.get("role") or "member").strip()
        if not user_id:
            return JSONResponse(
                {"status": "error", "reason": "user_id is required"},
                status_code=400,
            )
        if role not in WORKSPACE_ROLES:
            return JSONResponse(
                {
                    "status": "error",
                    "reason": f"role must be one of {sorted(WORKSPACE_ROLES)}",
                },
                status_code=400,
            )
        if await k.store.get_user(p.tenant_id, user_id) is None:
            return JSONResponse(
                {"status": "error", "reason": "unknown user"}, status_code=404
            )
        params = {"workspace_id": workspace_id, "user_id": user_id, "role": role}
        if isinstance(body.get("permissions"), dict):
            params["permissions"] = body["permissions"]
        output, pending = await dispatch_control_route(
            k, p, "control.workspace.member.add", params, request=request
        )
        if pending is not None:
            return pending
        await audit(
            k,
            p,
            "workspace.member.add",
            {"workspace_id": workspace_id, "user": user_id, "role": role},
        )
        return JSONResponse(
            {"status": "ok", "member": (output or {}).get("member", {})}
        )

    @app.delete("/v1/workspaces/{workspace_id}/members/{user_id}")
    async def remove_workspace_member(
        workspace_id: str, user_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        _, denied = await authorize(k, p, workspace_id)
        if denied is not None:
            return denied
        _, pending = await dispatch_control_route(
            k,
            p,
            "control.workspace.member.remove",
            {"workspace_id": workspace_id, "user_id": user_id},
            request=request,
        )
        if pending is not None:
            return pending
        await audit(
            k,
            p,
            "workspace.member.remove",
            {"workspace_id": workspace_id, "user": user_id},
        )
        return JSONResponse(
            {"status": "ok", "workspace_id": workspace_id, "user": user_id}
        )


def register_workspace_management_routes(
    app,
    P,
    K,
    audit,
    require_admin,
    authorize,
    workspace_view,
    member_view,
    admin_roles,
) -> None:
    _register_workspace_record_routes(
        app, P, K, audit, require_admin, authorize, workspace_view
    )
    _register_workspace_member_read_route(app, P, K, admin_roles, member_view)
    _register_workspace_member_write_routes(app, P, K, audit, authorize)
