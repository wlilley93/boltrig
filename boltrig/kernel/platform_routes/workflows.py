"""Workflow Studio (WFS): list, get, upsert, schedule, trigger, execute, runs."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.models import BoltrigError

from ._shared import require_author


def _visible(workflow, workspace_id) -> bool:
    """Keep workspace-scoped workflows invisible outside their workspace."""
    return workflow.workspace_id is None or workflow.workspace_id == workspace_id


def _register_read_routes(app, P, K) -> None:
    @app.get("/v1/workflows")
    async def list_workflows(k=K, p=P) -> dict:
        workflows = [
            workflow
            for workflow in await k.store.list_workflows(p.tenant_id)
            if _visible(workflow, p.active_workspace_id)
        ]
        return {
            "workflows": [
                {
                    "id": workflow.id,
                    "version": workflow.version,
                    "source": workflow.source.value,
                    "intent_tags": workflow.intent_tags,
                }
                for workflow in workflows
            ]
        }

    @app.get("/v1/workflows/{wf_id}")
    async def get_workflow(wf_id: str, k=K, p=P) -> JSONResponse:
        for workflow in await k.store.list_workflows(p.tenant_id):
            if workflow.id == wf_id and _visible(workflow, p.active_workspace_id):
                return JSONResponse(
                    {
                        "id": workflow.id,
                        "version": workflow.version,
                        "source": workflow.source.value,
                        "definition": workflow.definition,
                        "intent_tags": workflow.intent_tags,
                    }
                )
        return JSONResponse({"error": "unknown_workflow"}, status_code=404)

    @app.get("/v1/workflow-stats")
    async def workflow_stats(k=K, p=P) -> dict:
        return {"stats": await k.store.workflow_run_stats(p.tenant_id)}

    @app.get("/v1/workflows/{wf_id}/runs")
    async def workflow_runs(wf_id: str, k=K, p=P) -> JSONResponse:
        workflows = await k.store.list_workflows(p.tenant_id)
        workflow = next(
            (
                item
                for item in workflows
                if item.id == wf_id and _visible(item, p.active_workspace_id)
            ),
            None,
        )
        if workflow is None:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)
        recorded = await k.store.list_workflow_run_ids(p.tenant_id, wf_id, limit=100)
        from boltrig.kernel.run_access import visible_run_events

        runs = []
        for run_id in recorded:
            if await visible_run_events(k.store, p, run_id) is not None:
                runs.append(run_id)
        return JSONResponse({"workflow_id": wf_id, "runs": runs})


def _register_author_routes(app, P, K) -> None:
    @app.post("/v1/workflows")
    async def upsert_workflow(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.workflow.upsert", body, request=request
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", "id": (output or {}).get("id")})

    @app.post("/v1/workflows/{wf_id}/schedule")
    async def schedule_workflow(wf_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        try:
            require_author(p)
            output, pending = await dispatch_control_route(
                k,
                p,
                "control.workflow.schedule",
                {"workflow_id": wf_id, **body},
                request=request,
            )
            if pending is not None:
                return pending
            return JSONResponse({"status": "ok", **(output or {})})
        except (BoltrigError, ValueError) as exc:
            code = getattr(exc, "status_code", 400)
            return JSONResponse({"status": "error", "reason": str(exc)}, status_code=code)


def _register_run_routes(app, P, K) -> None:
    @app.post("/v1/workflows/{wf_id}/trigger")
    async def trigger_workflow(wf_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        try:
            output, pending = await dispatch_control_route(
                k,
                p,
                "control.workflow.trigger",
                {"workflow_id": wf_id, **body},
                request=request,
            )
            return pending or JSONResponse(output or {})
        except LookupError:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)

    @app.post("/v1/workflows/{wf_id}/execute")
    async def execute_workflow(wf_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        try:
            output, pending = await dispatch_control_route(
                k,
                p,
                "control.workflow.execute",
                {"workflow_id": wf_id, **body},
                request=request,
            )
            return pending or JSONResponse(output or {})
        except LookupError:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)


def register(app, P, K) -> None:
    _register_read_routes(app, P, K)
    _register_author_routes(app, P, K)
    _register_run_routes(app, P, K)
