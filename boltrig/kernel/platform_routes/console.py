"""Operator console snapshots for desktop, mobile, and TUI clients."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from boltrig.models import AuditEvent, HITLRequest
from boltrig.observability.model_telemetry import model_telemetry
from boltrig.store.base import MAX_OBSERVABILITY_PAGE

from boltrig.kernel.hitl_response_auth import hitl_request_visible

from ._shared import platform_state, scope_depts
from .observability import _items, _read_status_provider


_MAX_LIMIT = 200


def _clamp_limit(value: int) -> int:
    return max(1, min(int(value or 50), _MAX_LIMIT))


class _BatchedVisibilityStore:
    """Read-through batch cache over the store for HITL visibility checks.

    ``hitl_request_visible`` costs up to three store reads per pending request
    (the related work item, a workspace-membership probe, tenant permissions) -
    an N+1 across the pending list. The related work items are prefetched in
    ONE ref query and the membership/permission reads are memoized, so the
    overview stays O(1) queries regardless of pending count. A prefetch miss
    falls through to the real store (correctness over caching).
    """

    def __init__(self, store: Any, items: list[Any]) -> None:
        self._store = store
        self._by_id = {item.id: item for item in items}
        self._by_run = {
            item.hatchet_run_id: item for item in items if item.hatchet_run_id
        }
        self._perms: dict[str, Any] = {}
        self._members: dict[tuple[str, str, str], Any] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def get_work_item(self, tenant_id, item_id, *args, **kwargs):
        item = self._by_id.get(item_id)
        if item is not None and item.tenant_id == tenant_id:
            return item
        return await self._store.get_work_item(tenant_id, item_id, *args, **kwargs)

    async def get_work_item_by_run_id(self, tenant_id, run_id, *args, **kwargs):
        # A direct id match wins over a hatchet-run alias, mirroring the store.
        item = self._by_id.get(run_id) or self._by_run.get(run_id)
        if item is not None and item.tenant_id == tenant_id:
            return item
        return await self._store.get_work_item_by_run_id(
            tenant_id, run_id, *args, **kwargs
        )

    async def get_tenant_permissions(self, tenant_id):
        if tenant_id not in self._perms:
            self._perms[tenant_id] = await self._store.get_tenant_permissions(
                tenant_id
            )
        return self._perms[tenant_id]

    async def get_workspace_member(self, tenant_id, workspace_id, user_id):
        key = (tenant_id, workspace_id, user_id)
        if key not in self._members:
            self._members[key] = await self._store.get_workspace_member(*key)
        return self._members[key]


class _VisibilityKernel:
    """The two attributes hitl_request_visible reads off the kernel."""

    def __init__(self, kernel: Any, store: Any) -> None:
        self.store = store
        self.grants = kernel.grants


async def _visibility_kernel(k: Any, tenant_id: str, pending: list[Any]) -> Any:
    refs = {
        ref
        for req in pending
        for ref in (req.work_item_id, req.run_id)
        if ref
    }
    items = (
        await k.store.list_work_items_by_refs(tenant_id, sorted(refs))
        if refs
        else []
    )
    return _VisibilityKernel(k, _BatchedVisibilityStore(k.store, items))


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
        active_workspace = getattr(p, "active_workspace_id", None)
        # Scoped + bounded in the store (SEC-69 idiom): the department/workspace
        # run-scope predicate and the event workspace filter run inside the
        # query under a clamped page, not load-then-filter in Python.
        visible = await k.store.audit_query_scoped(
            p.tenant_id,
            departments=depts,
            workspace_id=active_workspace,
            match_parent=True,
            limit=MAX_OBSERVABILITY_PAGE,
        )
        recent = sorted(visible, key=lambda e: e.ts, reverse=True)[:row_limit]
        pending = await k.hitl.list_pending(p.tenant_id)
        approvals = []
        if pending:
            visibility = await _visibility_kernel(k, p.tenant_id, pending)
            for req in pending:
                if await hitl_request_visible(visibility, p, req):
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
