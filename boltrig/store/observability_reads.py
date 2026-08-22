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

from itertools import islice
from typing import Any

from .audit_read_contract import (
    MAX_ACCOUNT_ACTIVITY_PAGE,
    MAX_AUDIT_SEARCH_PAGE,
    bounded_offset,
    bounded_page,
)
from .base import clamp_observability_page
from .rows import _audit, _security
from .workspace_scope import (
    append_workspace_scope_clause,
    workspace_scope_visible,
)


def _run_ref(item: Any) -> Any:
    # The durable run identity (models.work.work_item_run_id): hatchet id first,
    # so an item with a hatchet_run_id contributes ONLY that ref, never its id.
    return item.hatchet_run_id or item.id


def _page(rows, *, limit: int, offset: int):
    page = list(islice(rows, offset, offset + limit + 1))
    return page[:limit], offset + limit if len(page) > limit else None


def _audit_text_matches(event: Any, query: str | None) -> bool:
    if query is None:
        return True
    needle = query.casefold()
    return any(
        needle in (value or "").casefold()
        for value in (
            event.actor,
            event.verb,
            event.status,
            event.run_id,
            event.parent_run_id,
            event.resource,
            event.resource_id,
        )
    )


class ObservabilityReadsMem:
    def _audit_scope(self, tenant_id, departments, workspace_id, match_parent=False):
        items = [w for (tenant, _), w in self._work.items() if tenant == tenant_id]
        allowed = None if departments is None else set(departments)

        def _visible(w) -> bool:
            return (allowed is None or w.owner_member in allowed) and (
                workspace_scope_visible(w, workspace_id, True)
            )

        visible = {_run_ref(w) for w in items if _visible(w)}
        hidden = {_run_ref(w) for w in items if not _visible(w)}

        def _permits(event) -> bool:
            refs = {
                ref for ref in (
                    (event.run_id, event.parent_run_id)
                    if match_parent else (event.run_id,)
                ) if ref is not None
            }
            return not refs & hidden and (allowed is None or bool(refs & visible))

        return _permits

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
        permits = self._audit_scope(
            tenant_id, departments, workspace_id, match_parent
        )

        chain = [
            e
            for e in self._audit.get(tenant_id, [])
            if (e.workspace_id is None or e.workspace_id == workspace_id)
            and permits(e)
        ]
        if run_id is not None:
            chain = [
                e for e in chain if e.run_id == run_id or e.parent_run_id == run_id
            ]
        return chain[-clamp_observability_page(limit) :]

    async def account_activity_page(
        self, tenant_id, subject, *, limit, offset=0
    ):
        size = bounded_page(limit, MAX_ACCOUNT_ACTIVITY_PAGE)
        start = bounded_offset(offset)
        rows = (
            event for event in reversed(self._audit.get(tenant_id, ()))
            if event.actor == subject or event.on_behalf_of == subject
        )
        return _page(rows, limit=size, offset=start)

    async def audit_search_page(
        self, tenant_id, *, departments=None, workspace_id=None, run_id=None,
        query=None, actor=None, verb=None, status=None, resource=None, since=None,
        until=None, limit=100, offset=0,
    ):
        size = bounded_page(limit, MAX_AUDIT_SEARCH_PAGE)
        start = bounded_offset(offset)
        permits = self._audit_scope(tenant_id, departments, workspace_id)
        rows = (
            event for event in reversed(self._audit.get(tenant_id, ()))
            if (event.workspace_id is None or event.workspace_id == workspace_id)
            and permits(event)
            and (run_id is None or event.run_id == run_id or event.parent_run_id == run_id)
            and _audit_text_matches(event, query)
            and (actor is None or event.actor == actor)
            and (verb is None or event.verb == verb)
            and (status is None or event.status == status)
            and (resource is None or event.resource == resource)
            and (since is None or event.ts >= since)
            and (until is None or event.ts <= until)
        )
        return _page(rows, limit=size, offset=start)

    async def security_search_page(
        self, tenant_id, *, workspace_id=None, event_type=None, actor=None,
        resource=None, since=None, until=None, limit=100, offset=0,
    ):
        size = bounded_page(limit, MAX_AUDIT_SEARCH_PAGE)
        start = bounded_offset(offset)
        rows = (
            event for event in reversed(self._security.get(tenant_id, ()))
            if (event.workspace_id is None or event.workspace_id == workspace_id)
            and (event_type is None or event.event_type.value == event_type)
            and (actor is None or event.actor == actor)
            and (resource is None or event.resource == resource)
            and (since is None or event.ts >= since)
            and (until is None or event.ts <= until)
        )
        return _page(rows, limit=size, offset=start)


class ObservabilityReadsPG:
    def _audit_scope_sql(
        self, tenant_id, departments, workspace_id, match_parent=False
    ):
        args: list[Any] = [tenant_id]
        ref = "COALESCE(w.hatchet_run_id, w.id)"
        cols = ["a.run_id"] + (["a.parent_run_id"] if match_parent else [])
        match = " OR ".join(f"{ref} = {col}" for col in cols)
        visible_clauses = []
        if departments is not None:
            args.append(list(departments))
            visible_clauses.append(f"w.owner_member = ANY(${len(args)}::text[])")
        append_workspace_scope_clause(visible_clauses, args, workspace_id, True)
        visible_sql = " AND ".join(visible_clauses)
        clauses = ["a.tenant_id = $1"]
        args.append(workspace_id)
        clauses.append(f"(a.workspace_id IS NULL OR a.workspace_id = ${len(args)})")
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM work_items w WHERE w.tenant_id = $1"
            f" AND ({match}) AND NOT COALESCE(({visible_sql}), false))"
        )
        if departments is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM work_items w WHERE w.tenant_id = $1"
                f" AND ({match}) AND {visible_sql})"
            )
        return args, clauses

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
        args, clauses = self._audit_scope_sql(
            tenant_id, departments, workspace_id, match_parent
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

    async def account_activity_page(
        self, tenant_id, subject, *, limit, offset=0
    ):
        size = bounded_page(limit, MAX_ACCOUNT_ACTIVITY_PAGE)
        start = bounded_offset(offset)
        rows = await self._pool.fetch(
            """SELECT * FROM audit_log
               WHERE tenant_id=$1 AND (actor=$2 OR on_behalf_of=$2)
               ORDER BY seq DESC LIMIT $3 OFFSET $4""",
            tenant_id, subject, size + 1, start,
        )
        return ([_audit(r) for r in rows[:size]],
                start + size if len(rows) > size else None)

    async def audit_search_page(
        self, tenant_id, *, departments=None, workspace_id=None, run_id=None,
        query=None, actor=None, verb=None, status=None, resource=None, since=None,
        until=None, limit=100, offset=0,
    ):
        size = bounded_page(limit, MAX_AUDIT_SEARCH_PAGE)
        start = bounded_offset(offset)
        args, clauses = self._audit_scope_sql(tenant_id, departments, workspace_id)
        for value, sql in (
            (run_id, "(a.run_id = ${n} OR a.parent_run_id = ${n})"),
            (actor, "a.actor = ${n}"), (verb, "a.verb = ${n}"),
            (status, "a.status = ${n}"), (resource, "a.resource = ${n}"),
            (since, "a.ts >= ${n}"), (until, "a.ts <= ${n}"),
        ):
            if value is not None:
                args.append(value)
                clauses.append(sql.replace("{n}", str(len(args))))
        if query is not None:
            # The query is a literal substring, not a LIKE mini-language. Keep
            # it bound and escape all three metacharacters before paging.
            needle = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.append(f"%{needle}%")
            placeholder = f"${len(args)}"
            clauses.append(
                "("
                + " OR ".join(
                    f"COALESCE(a.{column}, '') ILIKE {placeholder} ESCAPE '\\'"
                    for column in (
                        "actor",
                        "verb",
                        "status",
                        "run_id",
                        "parent_run_id",
                        "resource",
                        "resource_id",
                    )
                )
                + ")"
            )
        args.extend((size + 1, start))
        rows = await self._pool.fetch(
            f"SELECT a.* FROM audit_log a WHERE {' AND '.join(clauses)}"
            f" ORDER BY a.seq DESC LIMIT ${len(args)-1} OFFSET ${len(args)}",
            *args,
        )
        return ([_audit(r) for r in rows[:size]],
                start + size if len(rows) > size else None)

    async def security_search_page(
        self, tenant_id, *, workspace_id=None, event_type=None, actor=None,
        resource=None, since=None, until=None, limit=100, offset=0,
    ):
        size = bounded_page(limit, MAX_AUDIT_SEARCH_PAGE)
        start = bounded_offset(offset)
        args: list[Any] = [tenant_id, workspace_id]
        clauses = [
            "tenant_id = $1",
            "(workspace_id IS NULL OR workspace_id = $2)",
        ]
        for value, column, operator in (
            (event_type, "event_type", "="), (actor, "actor", "="),
            (resource, "resource", "="), (since, "ts", ">="), (until, "ts", "<="),
        ):
            if value is not None:
                args.append(value)
                clauses.append(f"{column} {operator} ${len(args)}")
        args.extend((size + 1, start))
        rows = await self._pool.fetch(
            f"SELECT * FROM security_log WHERE {' AND '.join(clauses)}"
            f" ORDER BY seq DESC LIMIT ${len(args)-1} OFFSET ${len(args)}",
            *args,
        )
        return ([_security(r) for r in rows[:size]],
                start + size if len(rows) > size else None)
