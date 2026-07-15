"""Operator console snapshots for desktop, mobile, and TUI clients."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from boltrig.models import AuditEvent, HITLRequest
from boltrig.observability.model_telemetry import model_telemetry

from boltrig.kernel.hitl_response_auth import hitl_request_visible

from ._shared import RunScope, dept_run_ids, platform_state, scope_depts
from .observability import _items, _read_status_provider


_MAX_LIMIT = 200


def _clamp_limit(value: int) -> int:
    return max(1, min(int(value or 50), _MAX_LIMIT))


def _ws_visible(p: Any, workspace_id: str | None) -> bool:
    active = getattr(p, "active_workspace_id", None)
    return workspace_id is None or workspace_id == active


def _visible_event(e: AuditEvent, run_scope: RunScope, p: Any) -> bool:
    return run_scope.permits(e.run_id, e.parent_run_id) and _ws_visible(
        p, e.workspace_id
    )


def _cost(events: list[AuditEvent]) -> dict[str, Any]:
    total = 0
    by_actor: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for event in events:
        cost = int(event.cost_micros or 0)
        total += cost
        by_actor[event.actor] = by_actor.get(event.actor, 0) + cost
        by_status[event.status] = by_status.get(event.status, 0) + 1
    return {
        "total_cost_micros": total,
        "by_actor": dict(sorted(by_actor.items())),
        "by_status": dict(sorted(by_status.items())),
    }


def _budget_row(b: Any) -> dict[str, Any]:
    return {
        "id": b.id,
        "scope_type": b.scope_type,
        "window": b.window,
        "hard_stop": b.hard_stop,
        "token_limit": b.token_limit,
        "spent_tokens": b.spent_tokens,
        "cost_limit_micros": b.cost_limit_micros,
        "spent_micros": b.spent_micros,
    }


def _run_row(event: AuditEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "ts": event.ts.isoformat(),
        "run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "workspace_id": event.workspace_id,
        "actor": event.actor,
        "action_type": event.action_type.value,
        "verb": event.verb,
        "status": event.status,
        "tokens_used": event.tokens_used or 0,
        "cost_micros": event.cost_micros or 0,
        "latency_ms": event.latency_ms,
    }


def _approval_row(req: HITLRequest) -> dict[str, Any]:
    return {
        "id": req.id,
        "run_id": req.run_id,
        "work_item_id": req.work_item_id,
        "type": req.type.value,
        "urgency": req.urgency.value,
        "status": req.status.value,
        "question": req.question[:240],
        "options": req.options[:10],
        "assignee": req.assignee,
        "timeout_at": req.timeout_at.isoformat() if req.timeout_at else None,
    }


async def _platform_snapshot(request: Request, p: Any) -> dict[str, Any]:
    raw = await _read_status_provider(platform_state(request).get("status"), p)
    return {
        "components": _items(raw.get("components", []), limit=20),
        "runtimes": _items(raw.get("runtimes", []), limit=50),
    }


def _scope_budget(b: Any, depts: list[str] | None) -> bool:
    return not (b.scope_type == "department" and depts is not None and b.id not in depts)


def register(app, P, K) -> None:
    @app.get("/v1/console/overview")
    async def console_overview(request: Request, limit: int = 50, k=K, p=P) -> dict:
        row_limit = _clamp_limit(limit)
        depts = scope_depts(p)
        run_scope = await dept_run_ids(k, p, depts)
        events = await k.store.audit_query(p.tenant_id, limit=10_000)
        visible = [e for e in events if _visible_event(e, run_scope, p)]
        recent = sorted(visible, key=lambda e: e.ts, reverse=True)[:row_limit]
        pending = await k.hitl.list_pending(p.tenant_id)
        active_workspace = getattr(p, "active_workspace_id", None)
        approvals = []
        for req in pending:
            if await hitl_request_visible(k, p, req):
                approvals.append(_approval_row(req))
            if len(approvals) == row_limit:
                break
        budgets = [
            _budget_row(b) for b in await k.store.list_budgets(p.tenant_id)
            if _scope_budget(b, depts)
        ]

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "tenant_id": p.tenant_id,
            "workspace_id": active_workspace,
            "scope": depts or "all",
            "platform": await _platform_snapshot(request, p),
            "models": model_telemetry(visible, limit=row_limit),
            "cost": _cost(visible),
            "budgets": budgets,
            "recent_runs": [_run_row(event) for event in recent],
            "approvals": approvals,
            "counts": {
                "visible_events": len(visible),
                "recent_runs": len(recent),
                "pending_approvals": len(approvals),
            },
        }
