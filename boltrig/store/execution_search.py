"""Scoped, bounded execution search for memory and PostgreSQL stores."""

from __future__ import annotations

from typing import Any

from boltrig.models import WorkItem
from boltrig.models.work import work_item_run_id

from .base import clamp_work_page
from .work_item_rows import detached_work_item, work_item_from_row
from .workspace_scope import (
    append_workspace_scope_clause,
    workspace_scope_visible,
)


def _text_matches(item: WorkItem, query: str) -> bool:
    needle = query.casefold()
    status = getattr(item.status, "value", item.status)
    return any(
        needle in str(value or "").casefold()
        for value in (
            item.intent,
            item.id,
            work_item_run_id(item),
            item.owner_member,
            item.on_behalf_of,
            item.source,
            item.source_id,
            status,
        )
    )


class ExecutionSearchMem:
    async def search_execution_items_scoped(
        self,
        tenant_id,
        query,
        *,
        departments=None,
        workspace_id=None,
        limit,
    ):
        items = [w for (tenant, _), w in self._work.items() if tenant == tenant_id]
        allowed = None if departments is None else set(departments)

        def _visible(w) -> bool:
            return (allowed is None or w.owner_member in allowed) and (
                workspace_scope_visible(w, workspace_id, True)
            )

        hidden = {work_item_run_id(w) for w in items if not _visible(w)}
        out = [
            w
            for w in items
            if _visible(w)
            and work_item_run_id(w) not in hidden
            and _text_matches(w, query)
        ]
        out.sort(key=lambda w: w.id)
        return [detached_work_item(w) for w in out[:clamp_work_page(limit)]]


class ExecutionSearchPG:
    async def search_execution_items_scoped(
        self,
        tenant_id,
        query,
        *,
        departments=None,
        workspace_id=None,
        limit,
    ):
        args: list[Any] = [tenant_id]
        visible_clauses = []
        if departments is not None:
            args.append(list(departments))
            visible_clauses.append(f"owner_member = ANY(${len(args)}::text[])")
        append_workspace_scope_clause(visible_clauses, args, workspace_id, True)
        visible_sql = " AND ".join(visible_clauses)
        clauses = ["w.tenant_id=$1", visible_sql]
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM work_items h WHERE h.tenant_id=$1"
            " AND COALESCE(h.hatchet_run_id, h.id) = COALESCE(w.hatchet_run_id, w.id)"
            f" AND NOT COALESCE(({visible_sql}), false))"
        )
        needle = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args.append(f"%{needle}%")
        placeholder = f"${len(args)}"
        clauses.append(
            "("
            + " OR ".join(
                f"COALESCE({column}, '') ILIKE {placeholder} ESCAPE '\\'"
                for column in (
                    "w.intent",
                    "w.id",
                    "COALESCE(w.hatchet_run_id, w.id)",
                    "w.owner_member",
                    "w.on_behalf_of",
                    "w.source",
                    "w.source_id",
                    "w.status",
                )
            )
            + ")"
        )
        args.append(clamp_work_page(limit))
        rows = await self._pool.fetch(
            f"SELECT w.* FROM work_items w WHERE {' AND '.join(clauses)}"
            f" ORDER BY w.id LIMIT ${len(args)}",
            *args,
        )
        return [work_item_from_row(row) for row in rows]
