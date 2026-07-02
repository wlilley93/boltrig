"""Workflow Studio (WFS): list, get, upsert, schedule, trigger, execute, runs."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.models import BoltrigError
from ._shared import audit_authoring, platform_state, require_author


def register(app, P, K) -> None:
    @app.get("/v1/workflows")
    async def list_workflows(k=K, p=P) -> dict:
        wfs = await k.store.list_workflows(p.tenant_id)
        return {"workflows": [{"id": w.id, "version": w.version, "source": w.source.value,
                              "intent_tags": w.intent_tags} for w in wfs]}

    @app.get("/v1/workflows/{wf_id}")
    async def get_workflow(wf_id: str, k=K, p=P) -> JSONResponse:
        # The full stored definition (incl. steps) so the canvas can load + edit an
        # existing workflow. Tenant-scoped read; 404 if unknown.
        for w in await k.store.list_workflows(p.tenant_id):
            if w.id == wf_id:
                return JSONResponse({"id": w.id, "version": w.version,
                                     "source": w.source.value, "definition": w.definition,
                                     "intent_tags": w.intent_tags})
        return JSONResponse({"error": "unknown_workflow"}, status_code=404)

    @app.post("/v1/workflows")
    async def upsert_workflow(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        from boltrig.models import WorkflowDefinition, WorkflowSource

        require_author(p)
        wf = WorkflowDefinition(
            id=body["id"], tenant_id=p.tenant_id, version=body.get("version", "1.0.0"),
            source=WorkflowSource(body.get("source", "precreated")),
            definition=body.get("definition", {}), intent_tags=body.get("intent_tags", []),
        )
        await k.store.upsert_workflow(wf)
        await audit_authoring(k, p, "workflow.upsert", {"id": wf.id})
        return JSONResponse({"status": "ok", "id": wf.id})

    @app.post("/v1/workflows/{wf_id}/schedule")
    async def schedule_workflow(wf_id: str, body: dict, k=K, p=P) -> JSONResponse:
        from boltrig.workflows.generator import schedule_spec

        try:
            require_author(p)
            spec = schedule_spec(body["cron"], body.get("timezone", "UTC"))
            await audit_authoring(k, p, "workflow.schedule", {"id": wf_id, "cron": body["cron"]})
            return JSONResponse({"status": "ok", "id": wf_id, "schedule": spec})
        except (BoltrigError, ValueError) as e:
            code = getattr(e, "status_code", 400)
            return JSONResponse({"status": "error", "reason": str(e)}, status_code=code)

    @app.post("/v1/workflows/{wf_id}/trigger")
    async def trigger_workflow(wf_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        lib = platform_state(request).get("workflows")
        if lib is None:
            return JSONResponse({"error": "workflows_unavailable"}, status_code=503)
        try:
            desc = await lib.trigger(p.tenant_id, wf_id, body.get("inputs", {}))
            await audit_authoring(k, p, "workflow.trigger", {"id": wf_id, "run_id": desc.get("run_id"),
                                                    "durable": desc.get("durable")})
            return JSONResponse(desc)
        except LookupError:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)

    @app.post("/v1/workflows/{wf_id}/execute")
    async def execute_workflow(wf_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # Run the stored definition's steps through the chokepoint, each as its own
        # durable boundary (Round Seven interpreter). Steps run under the caller's
        # own grants - a step cannot escalate (SEC-50).
        lib = platform_state(request).get("workflows")
        if lib is None:
            return JSONResponse({"error": "workflows_unavailable"}, status_code=503)
        try:
            ctx = p.context()
            record = await lib.execute(p.tenant_id, wf_id, body.get("inputs", {}), ctx)
            await audit_authoring(k, p, "workflow.execute",
                         {"id": wf_id, "run_id": record.get("run_id"), "status": record.get("status")})
            return JSONResponse(record)
        except LookupError:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)

    @app.get("/v1/workflows/{wf_id}/runs")
    async def workflow_runs(wf_id: str, k=K, p=P) -> dict:
        events = await k.store.audit_query(p.tenant_id, limit=1000)
        runs = sorted({e.run_id for e in events if e.run_id})
        return {"workflow_id": wf_id, "runs": runs[:100]}
