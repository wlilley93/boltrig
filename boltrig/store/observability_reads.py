"""Scope-filtered audit reads for the observability surface (memory + PG parity).

The console/cost/telemetry/audit-search routes used to load the tenant's whole
work table (twice, via the old ``dept_run_ids`` helper) plus a 10k-row audit
slice per request and filter in Python. These reads push the run-scope
predicate (visible/hidden run ids derived from work_items by department +
workspace, hidden-wins on a shared ref) and the event-row workspace filter
into the query itself, before the clamped LIMIT - the same SEC-69 bounding
idiom as /v1/work.
"""

from __future__ import annotations

from typing import Any

from .base import clamp_observability_page
from .rows import _audit
from .workspace_scope import (
    append_work_workspace_clause,
    work_item_workspace_visible,
)


def _run_ref(item: Any) -> Any:
    # The durable run identity (models.work.work_item_run_id): hatchet id first,
    # so an item with a hatchet_run_id contributes ONLY that ref, never its id.
    return item.hatchet_run_id or item.id


class ObservabilityReadsMem:
    async def audit_query_scoped(
        self,
        tenant_id,
        *,
        departments=None,
        workspace_id=None,
        match_parent=False,
        run_id=None,
        limit=200,
    ):
        items = [w for (tenant, _), w in self._work.items() if tenant == tenant_id]
        allowed = None if departments is None else set(departments)

        def _visible(w) -> bool:
            dept_ok = allowed is None or w.owner_member in allowed
            return dept_ok and work_item_workspace_visible(w, workspace_id, True)

        visible = {_run_ref(w) for w in items if _visible(w)}
        hidden = {_run_ref(w) for w in items if not _visible(w)}

        def _permits(event) -> bool:
            refs = {
                ref
                for ref in (
                    (event.run_id, event.parent_run_id)
                    if match_parent
                    else (event.run_id,)
                )
                if ref is not None
            }
            if refs & hidden:
                return False
            return allowed is None or bool(refs & visible)

        chain = [
            e
            for e in self._audit.get(tenant_id, [])
            if (e.workspace_id is None or e.workspace_id == workspace_id)
            and _permits(e)
        ]
        if run_id is not None:
            chain = [
                e for e in chain if e.run_id == run_id or e.parent_run_id == run_id
            ]
        return chain[-clamp_observability_page(limit) :]


class ObservabilityReadsPG:
    async def audit_query_scoped(
        self,
        tenant_id,
        *,
        departments=None,
        workspace_id=None,
        match_parent=False,
        run_id=None,
        limit=200,
    ):
        args: list[Any] = [tenant_id]
        # A work item owns a run ref through its durable run identity only.
        ref = "COALESCE(w.hatchet_run_id, w.id)"
        cols = ["a.run_id"] + (["a.parent_run_id"] if match_parent else [])
        match = " OR ".join(f"{ref} = {col}" for col in cols)
        # V(w): the visible-item predicate - department scope plus the enforced
        # workspace visibility (org-wide + active).
        visible_clauses = []
        if departments is not None:
            args.append(list(departments))
            visible_clauses.append(f"w.owner_member = ANY(${len(args)}::text[])")
        append_work_workspace_clause(visible_clauses, args, workspace_id, True)
        visible_sql = " AND ".join(visible_clauses)
        clauses = ["a.tenant_id = $1"]
        # Event-row workspace visibility (the routes' _ws_visible): org-wide
        # rows plus the active workspace's rows, never another workspace's. In
        # a WHERE clause a NULL comparison behaves like false, matching Python.
        args.append(workspace_id)
        clauses.append(f"(a.workspace_id IS NULL OR a.workspace_id = ${len(args)})")
        # RunScope.permits: a ref owned by ANY non-visible item hides the event,
        # even when another (visible) item owns the same ref. COALESCE keeps
        # three-valued logic honest: a NULL owner_member makes V NULL, and
        # NOT NULL is still NULL - Python treats that item as NOT visible.
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM work_items w WHERE w.tenant_id = $1"
            f" AND ({match}) AND NOT COALESCE(({visible_sql}), false))"
        )
        if departments is not None:
            # A department-scoped caller additionally needs a visible owner;
            # audit-only runs (no work item) stay invisible to it, exactly like
            # RunScope with unrestricted_departments=False.
            clauses.append(
                "EXISTS (SELECT 1 FROM work_items w WHERE w.tenant_id = $1"
                f" AND ({match}) AND {visible_sql})"
            )
        if run_id is not None:
            args.append(run_id)
            clauses.append(f"(a.run_id = ${len(args)} OR a.parent_run_id = ${len(args)})")
        args.append(clamp_observability_page(limit))
        rows = await self._pool.fetch(
            f"SELECT a.* FROM audit_log a WHERE {' AND '.join(clauses)}"
            f" ORDER BY a.seq DESC LIMIT ${len(args)}",
            *args,
        )
        return [_audit(r) for r in reversed(rows)]  # ascending, like audit_query
