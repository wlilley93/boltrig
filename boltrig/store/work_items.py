"""Workspace-aware WorkItem read parity for memory and PostgreSQL stores."""

from __future__ import annotations

from typing import Any

from boltrig.models import WorkItem, WorkStatus
from boltrig.models.work import work_item_run_id

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

    async def list_work_items_by_refs(self, tenant_id, refs):
        wanted = set(refs)
        out = [
            item
            for (tenant, _), item in self._work.items()
            if tenant == tenant_id
            and (item.id in wanted or item.hatchet_run_id in wanted)
        ]
        out.sort(key=lambda item: item.id)
        return out

    async def list_run_items_scoped(
        self,
        tenant_id,
        *,
        departments=None,
        workspace_id=None,
        owner=None,
        on_behalf_of=None,
        label=None,
        source=None,
        external_ref=None,
        limit=None,
        cursor=None,
    ):
        items = [w for (tenant, _), w in self._work.items() if tenant == tenant_id]
        allowed = None if departments is None else set(departments)

        def _visible(w) -> bool:
            dept_ok = allowed is None or w.owner_member in allowed
            return dept_ok and work_item_workspace_visible(w, workspace_id, True)

        # The RunScope hidden-wins rule: a run ref owned by ANY non-visible item
        # hides every item carrying that ref, visible aliases included.
        hidden = {work_item_run_id(w) for w in items if not _visible(w)}
        out = [w for w in items if _visible(w) and work_item_run_id(w) not in hidden]

        # G7 owner/label/external-ref filters. Applied AFTER hidden-wins so they
        # can only REMOVE rows from the already-scoped set - never resurrect a
        # hidden alias. `label` is a literal case-insensitive substring of the
        # intent (parity with the PG ILIKE ... ESCAPE below); `external_ref`
        # matches the opaque source_id.
        label_needle = label.lower() if label else None
        out = [
            w
            for w in out
            if (owner is None or w.owner_member == owner)
            and (on_behalf_of is None or w.on_behalf_of == on_behalf_of)
            and (source is None or w.source == source)
            and (external_ref is None or w.source_id == external_ref)
            and (label_needle is None or label_needle in (w.intent or "").lower())
        ]
        out.sort(key=lambda w: w.id)
        if cursor is not None:
            out = [w for w in out if w.id > cursor]
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

    async def list_work_items_by_refs(self, tenant_id, refs):
        rows = await self._pool.fetch(
            """SELECT * FROM work_items WHERE tenant_id=$1
               AND (id = ANY($2::text[]) OR hatchet_run_id = ANY($2::text[]))
               ORDER BY id""",
            tenant_id,
            list(refs),
        )
        return [work_item_from_row(row) for row in rows]

    async def list_run_items_scoped(
        self,
        tenant_id,
        *,
        departments=None,
        workspace_id=None,
        owner=None,
        on_behalf_of=None,
        label=None,
        source=None,
        external_ref=None,
        limit=None,
        cursor=None,
    ):
        args: list[Any] = [tenant_id]
        # V(item): the visible-item predicate - department scope plus the
        # enforced workspace visibility (org-wide + active). Unqualified columns
        # resolve to the outer item in the WHERE clause and to the hidden-alias
        # candidate h inside the NOT EXISTS subquery.
        visible_clauses = []
        if departments is not None:
            args.append(list(departments))
            visible_clauses.append(f"owner_member = ANY(${len(args)}::text[])")
        append_work_workspace_clause(visible_clauses, args, workspace_id, True)
        visible_sql = " AND ".join(visible_clauses)
        clauses = ["w.tenant_id=$1", visible_sql]
        # RunScope hidden-wins: a ref owned by ANY non-visible item hides the
        # row. COALESCE keeps three-valued logic honest (a NULL owner_member
        # makes V NULL, and that item counts as NOT visible), exactly like
        # audit_query_scoped.
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM work_items h WHERE h.tenant_id=$1"
            " AND COALESCE(h.hatchet_run_id, h.id) = COALESCE(w.hatchet_run_id, w.id)"
            f" AND NOT COALESCE(({visible_sql}), false))"
        )
        # G7 owner/label/external-ref filters. These qualify the OUTER row (w.)
        # ONLY - never the hidden-alias subquery - so a filter can only NARROW
        # the already-scoped, hidden-wins-deduped set, never widen it.
        if owner is not None:
            args.append(owner)
            clauses.append(f"w.owner_member = ${len(args)}")
        if on_behalf_of is not None:
            args.append(on_behalf_of)
            clauses.append(f"w.on_behalf_of = ${len(args)}")
        if source is not None:
            args.append(source)
            clauses.append(f"w.source = ${len(args)}")
        if external_ref is not None:
            args.append(external_ref)
            clauses.append(f"w.source_id = ${len(args)}")
        if label is not None:
            # Literal substring (parity with the in-memory store): escape the
            # LIKE metacharacters so a user-supplied % / _ / \ is matched
            # literally, not as a wildcard.
            needle = label.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.append(f"%{needle}%")
            clauses.append(f"w.intent ILIKE ${len(args)} ESCAPE '\\'")
        if cursor is not None:
            args.append(cursor)
            clauses.append(f"w.id > ${len(args)}")
        sql = f"SELECT w.* FROM work_items w WHERE {' AND '.join(clauses)} ORDER BY w.id"
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
        target=row["target"],
        reply_route=row["reply_route"],
    )
