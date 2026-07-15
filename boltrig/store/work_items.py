"""Workspace-aware WorkItem read parity for memory and PostgreSQL stores."""

from __future__ import annotations

from typing import Any

from boltrig.models import WorkItem, WorkStatus

from .base import clamp_work_page
from .workspace_scope import (
    append_work_workspace_clause,
    work_item_workspace_visible,
)


class WorkItemReadsMem:
    async def get_work_item(
        self, tenant_id, item_id, workspace_id=None, enforce_workspace=False
    ):
        item = self._work.get((tenant_id, item_id))
        if item is None:
            return None
        return item if work_item_workspace_visible(item, workspace_id, enforce_workspace) else None

    async def get_work_item_by_run_id(
        self, tenant_id, run_id, workspace_id=None, enforce_workspace=False
    ):
        direct = self._work.get((tenant_id, run_id))
        if direct is not None:
            return (
                direct
                if work_item_workspace_visible(direct, workspace_id, enforce_workspace)
                else None
            )
        return next(
            (
                item
                for (tenant, _), item in self._work.items()
                if tenant == tenant_id
                and item.hatchet_run_id == run_id
                and work_item_workspace_visible(item, workspace_id, enforce_workspace)
            ),
            None,
        )

    async def list_work_items(
        self,
        tenant_id,
        status=None,
        parent_id=None,
        departments=None,
        limit=None,
        cursor=None,
        workspace_id=None,
        enforce_workspace=False,
    ):
        out = [item for (tenant, _), item in self._work.items() if tenant == tenant_id]
        if status is not None:
            out = [item for item in out if item.status == status]
        if parent_id is not None:
            out = [item for item in out if item.parent_id == parent_id]
        if departments is not None:
            allowed = set(departments)
            out = [item for item in out if item.owner_member in allowed]
        if enforce_workspace:
            out = [
                item
                for item in out
                if work_item_workspace_visible(item, workspace_id, True)
            ]
        out.sort(key=lambda item: item.id)
        if cursor is not None:
            out = [item for item in out if item.id > cursor]
        return out[: clamp_work_page(limit)] if limit is not None else out


class WorkItemReadsPG:
    async def get_work_item(
        self, tenant_id, item_id, workspace_id=None, enforce_workspace=False
    ):
        clauses = ["tenant_id=$1", "id=$2"]
        args: list[Any] = [tenant_id, item_id]
        append_work_workspace_clause(clauses, args, workspace_id, enforce_workspace)
        row = await self._pool.fetchrow(
            f"SELECT * FROM work_items WHERE {' AND '.join(clauses)}", *args
        )
        return work_item_from_row(row)

    async def get_work_item_by_run_id(
        self, tenant_id, run_id, workspace_id=None, enforce_workspace=False
    ):
        clauses = [
            "tenant_id=$1",
            "(id=$2 OR (hatchet_run_id=$2 AND NOT EXISTS "
            "(SELECT 1 FROM work_items direct "
            "WHERE direct.tenant_id=$1 AND direct.id=$2)))",
        ]
        args: list[Any] = [tenant_id, run_id]
        append_work_workspace_clause(clauses, args, workspace_id, enforce_workspace)
        row = await self._pool.fetchrow(
            f"""SELECT * FROM work_items WHERE {' AND '.join(clauses)}
                ORDER BY CASE WHEN id=$2 THEN 0 ELSE 1 END LIMIT 1""",
            *args,
        )
        return work_item_from_row(row)

    async def list_work_items(
        self,
        tenant_id,
        status=None,
        parent_id=None,
        departments=None,
        limit=None,
        cursor=None,
        workspace_id=None,
        enforce_workspace=False,
    ):
        clauses = ["tenant_id=$1"]
        args: list[Any] = [tenant_id]
        if status is not None:
            args.append(status.value)
            clauses.append(f"status=${len(args)}")
        if parent_id is not None:
            args.append(parent_id)
            clauses.append(f"parent_id=${len(args)}")
        if departments is not None:
            args.append(list(departments))
            clauses.append(f"owner_member = ANY(${len(args)}::text[])")
        append_work_workspace_clause(clauses, args, workspace_id, enforce_workspace)
        if cursor is not None:
            args.append(cursor)
            clauses.append(f"id > ${len(args)}")
        sql = f"SELECT * FROM work_items WHERE {' AND '.join(clauses)} ORDER BY id"
        if limit is not None:
            args.append(clamp_work_page(limit))
            sql += f" LIMIT ${len(args)}"
        rows = await self._pool.fetch(sql, *args)
        return [work_item_from_row(row) for row in rows]


def work_item_from_row(row: Any) -> WorkItem | None:
    if row is None:
        return None
    return WorkItem(
        id=row["id"],
        tenant_id=row["tenant_id"],
        workspace_id=row["workspace_id"],
        source=row["source"],
        intent=row["intent"],
        confidence=row["confidence"],
        convergent=row["convergent"],
        status=WorkStatus(row["status"]),
        source_id=row["source_id"],
        owner_member=row["owner_member"],
        parent_id=row["parent_id"],
        hatchet_run_id=row["hatchet_run_id"],
        depth=row["depth"],
        on_behalf_of=row["on_behalf_of"],
        constraints=row["constraints"] or {},
        raw=row["raw"] or {},
        attempts=row["attempts"],
        degraded=row["degraded"],
        result=row["result"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
    )
