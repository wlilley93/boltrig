"""Author-facing workflow-trigger management routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.identity.provisioning import ensure_user_record

from .control_routes import dispatch_control_route
from .platform_routes._shared import require_author
from .workflow_trigger_delivery import delivery_view, trigger_view
from .workflow_trigger_finalization import discover_finalizations


async def _visible_workflow(store, principal, workflow_id: str):
    return next(
        (
            workflow
            for workflow in await store.list_workflows(principal.tenant_id)
            if workflow.id == workflow_id
            and (
                workflow.workspace_id is None
                or workflow.workspace_id == principal.active_workspace_id
            )
        ),
        None,
    )


def _register_list_route(app, P, K) -> None:
    @app.get("/v1/workflows/{wf_id}/triggers")
    async def list_workflow_triggers(wf_id: str, k=K, p=P) -> JSONResponse:
        require_author(p)
        workflow = await _visible_workflow(k.store, p, wf_id)
        if workflow is None:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)
        triggers = await k.store.list_workflow_triggers(p.tenant_id, wf_id)
        return JSONResponse(
            {"workflow_id": wf_id, "triggers": [trigger_view(t) for t in triggers]}
        )


def _register_finalization_route(app, P, K) -> None:
    @app.get("/v1/workflows/{wf_id}/trigger-finalizations")
    async def list_workflow_trigger_finalizations(
        wf_id: str, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        workflow = await _visible_workflow(k.store, p, wf_id)
        if workflow is None:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)
        finalizations = await discover_finalizations(k.store, k.hitl, p, workflow)
        return JSONResponse(
            {"workflow_id": wf_id, "finalizations": finalizations}
        )


def _register_create_route(app, P, K) -> None:
    @app.post("/v1/workflows/{wf_id}/triggers")
    async def create_workflow_trigger(
        wf_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        await ensure_user_record(k.store, p)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.workflow.trigger_binding.create",
            {"workflow_id": wf_id, **body},
            request=request,
        )
        return pending or JSONResponse({"status": "ok", **(output or {})})


def _action_handler(action: str, K, P):
    async def change_workflow_trigger(
        wf_id: str,
        trigger_id: str,
        request: Request,
        body: dict | None = None,
        k=K,
        p=P,
    ) -> JSONResponse:
        require_author(p)
        params = {"workflow_id": wf_id, "trigger_id": trigger_id}
        approval_id = (body or {}).get("approval_id")
        if approval_id:
            params["approval_id"] = approval_id
        output, pending = await dispatch_control_route(
            k,
            p,
            f"control.workflow.trigger_binding.{action}",
            params,
            request=request,
        )
        return pending or JSONResponse({"status": "ok", **(output or {})})

    return change_workflow_trigger


def _register_action_routes(app, P, K) -> None:
    for action in ("enable", "disable", "rotate"):
        app.add_api_route(
            f"/v1/workflows/{{wf_id}}/triggers/{{trigger_id}}/{action}",
            _action_handler(action, K, P),
            methods=["POST"],
            name=f"{action}_workflow_trigger",
        )


def _register_delivery_route(app, P, K) -> None:
    @app.get("/v1/workflows/{wf_id}/triggers/{trigger_id}/deliveries")
    async def list_workflow_trigger_deliveries(
        wf_id: str, trigger_id: str, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        workflow = await _visible_workflow(k.store, p, wf_id)
        trigger = await k.store.get_workflow_trigger(p.tenant_id, trigger_id)
        if (
            workflow is None
            or trigger is None
            or trigger.workflow_id != wf_id
            or trigger.workspace_id != workflow.workspace_id
        ):
            return JSONResponse({"error": "unknown_trigger"}, status_code=404)
        rows = await k.store.list_workflow_trigger_deliveries(
            p.tenant_id, trigger_id, limit=50
        )
        return JSONResponse(
            {
                "workflow_id": wf_id,
                "trigger_id": trigger_id,
                "deliveries": [delivery_view(row) for row in rows],
            }
        )


def register_author_workflow_trigger_routes(app, P, K) -> None:
    _register_list_route(app, P, K)
    _register_finalization_route(app, P, K)
    _register_create_route(app, P, K)
    _register_action_routes(app, P, K)
    _register_delivery_route(app, P, K)
