"""Workflow Studio (WFS): list, get, upsert, schedule, trigger, execute, runs."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.workflows.scheduler import workflow_schedule_state

from ._shared import require_author


def _visible(workflow, workspace_id) -> bool:
    """Keep workspace-scoped workflows invisible outside their workspace."""
    return workflow.workspace_id is None or workflow.workspace_id == workspace_id


def _lifecycle(workflow, schedule_record=None) -> dict:
    raw = dict(workflow.definition.get("_boltrig_lifecycle") or {})
    legacy_schedule = raw.get("schedule", workflow.definition.get("schedule"))
    schedule = (
        {
            "type": "cron",
            "cron": schedule_record.cron,
            "timezone": schedule_record.timezone,
        }
        if schedule_record is not None
        else legacy_schedule
    )
    return {
        "status": raw.get("status", "active"),
        "schedule": schedule,
        "schedule_state": workflow_schedule_state(
            schedule_record,
            legacy_schedule=(
                legacy_schedule
                if schedule_record is None and isinstance(legacy_schedule, dict)
                else None
            ),
        ),
    }


_OCCURRENCE_REASONS = frozenset(
    {
        "manual_retry_requested",
        "schedule_dispatch_failed",
        "workflow_execution_failed",
        "occurrence_snapshot_changed",
        "scheduled_workflow_unavailable",
        "scheduled_workflow_archived",
        "scheduling_authority_not_bound",
        "scheduling_authority_revoked",
        "scheduling_workspace_membership_revoked",
        "scheduling_trigger_grant_revoked",
        "durable_executor_required",
    }
)


def _occurrence_receipt(occurrence) -> dict:
    reason = (
        occurrence.reason
        if occurrence.reason in _OCCURRENCE_REASONS
        else ("workflow_occurrence_failed" if occurrence.reason else None)
    )
    if occurrence.status in {"succeeded", "failed"}:
        engine_outcome = {"status": "settled", "recovery": "not_applicable"}
    elif occurrence.status == "queued":
        engine_outcome = {
            "status": "pending_or_unknown",
            "recovery": "engine_terminal_reconciliation_unavailable",
        }
    else:
        engine_outcome = {
            "status": "not_enqueued",
            "recovery": "not_applicable",
        }
    return {
        "scheduled_for": occurrence.scheduled_for.isoformat(),
        "run_id": occurrence.run_id,
        "status": ("enqueued" if occurrence.status == "queued" else occurrence.status),
        "claimed_at": (
            occurrence.claimed_at.isoformat() if occurrence.claimed_at is not None else None
        ),
        "enqueued_at": (
            occurrence.enqueued_at.isoformat() if occurrence.enqueued_at is not None else None
        ),
        "outcome_at": (
            occurrence.outcome_at.isoformat() if occurrence.outcome_at is not None else None
        ),
        "engine_outcome": engine_outcome,
        "reason": reason,
        "retry": {
            "attempts": occurrence.attempts,
            "manual_retries": occurrence.manual_retries,
            "last_retry_at": (
                occurrence.last_retry_at.isoformat()
                if occurrence.last_retry_at is not None
                else None
            ),
        },
    }


def _register_read_routes(app, P, K) -> None:
    @app.get("/v1/workflows")
    async def list_workflows(k=K, p=P) -> dict:
        workflows = [
            workflow
            for workflow in await k.store.list_workflows(p.tenant_id)
            if _visible(workflow, p.active_workspace_id)
        ]
        schedules = {
            schedule.workflow_id: schedule
            for schedule in await k.store.list_workflow_schedules(p.tenant_id)
        }
        return {
            "workflows": [
                {
                    "id": workflow.id,
                    "version": workflow.version,
                    "source": workflow.source.value,
                    "intent_tags": workflow.intent_tags,
                    **_lifecycle(workflow, schedules.get(workflow.id)),
                }
                for workflow in workflows
            ]
        }

    @app.get("/v1/workflows/{wf_id}")
    async def get_workflow(wf_id: str, k=K, p=P) -> JSONResponse:
        schedule = await k.store.get_workflow_schedule(p.tenant_id, wf_id)
        for workflow in await k.store.list_workflows(p.tenant_id):
            if workflow.id == wf_id and _visible(workflow, p.active_workspace_id):
                return JSONResponse(
                    {
                        "id": workflow.id,
                        "version": workflow.version,
                        "source": workflow.source.value,
                        "definition": workflow.definition,
                        "intent_tags": workflow.intent_tags,
                        **_lifecycle(workflow, schedule),
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
    @app.get("/v1/workflows/{wf_id}/schedule/occurrences")
    async def workflow_schedule_occurrences(wf_id: str, limit: int = 25, k=K, p=P) -> JSONResponse:
        require_author(p)
        workflow = next(
            (
                item
                for item in await k.store.list_workflows(p.tenant_id)
                if item.id == wf_id and _visible(item, p.active_workspace_id)
            ),
            None,
        )
        if workflow is None:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)
        bounded = max(1, min(limit, 50))
        rows = await k.store.list_workflow_schedule_occurrences(
            p.tenant_id,
            wf_id,
            limit=bounded + 1,
        )
        return JSONResponse(
            {
                "workflow_id": wf_id,
                "occurrences": [_occurrence_receipt(row) for row in rows[:bounded]],
                "truncated": len(rows) > bounded,
                "backfill": {
                    "status": "unavailable",
                    "reason": "historical_backfill_not_supported_by_canonical_claim",
                },
            }
        )

    @app.post("/v1/workflows/{wf_id}/schedule/occurrences/{scheduled_for}/retry")
    async def retry_workflow_schedule_occurrence(
        wf_id: str,
        scheduled_for: str,
        body: dict,
        request: Request,
        k=K,
        p=P,
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.workflow.schedule_occurrence.retry",
            {
                "workflow_id": wf_id,
                "scheduled_for": scheduled_for,
                "run_id": body.get("run_id"),
                **({"approval_id": body.get("approval_id")} if body.get("approval_id") else {}),
            },
            request=request,
        )
        return pending or JSONResponse({"status": "ok", **(output or {})})


def _register_author_mutation_routes(app, P, K) -> None:
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
        except ValueError:
            # BoltrigError propagates to the central handler (canonical envelope);
            # a bare ValueError never leaks internal text as the client reason.
            return JSONResponse({"status": "error", "reason": "invalid schedule"}, status_code=400)

    for action in ("unschedule", "archive", "restore"):

        async def lifecycle(wf_id: str, request: Request, k=K, p=P, _action=action) -> JSONResponse:
            require_author(p)
            output, pending = await dispatch_control_route(
                k,
                p,
                f"control.workflow.{_action}",
                {"workflow_id": wf_id},
                request=request,
            )
            return pending or JSONResponse({"status": "ok", **(output or {})})

        app.add_api_route(
            f"/v1/workflows/{{wf_id}}/{action}",
            lifecycle,
            methods=["POST"],
            name=f"{action}_workflow",
        )


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
    _register_author_mutation_routes(app, P, K)
    _register_run_routes(app, P, K)
    from boltrig.kernel.workflow_trigger_routes import (
        register_workflow_trigger_routes,
    )

    register_workflow_trigger_routes(app, P, K)
