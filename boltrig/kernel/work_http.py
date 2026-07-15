"""Workspace-scoped WorkItem read helpers shared by HTTP routes."""

from __future__ import annotations

from typing import Any

from boltrig.models.work import work_item_run_id


async def list_visible_work_items(store: Any, principal: Any, status=None, **filters):
    return await store.list_work_items(
        principal.tenant_id,
        status,
        workspace_id=principal.active_workspace_id,
        enforce_workspace=True,
        **filters,
    )


async def get_visible_work_item(store: Any, principal: Any, item_id: str):
    return await store.get_work_item(
        principal.tenant_id,
        item_id,
        workspace_id=principal.active_workspace_id,
        enforce_workspace=True,
    )


async def work_item_audit_trail(store: Any, principal: Any, item: Any) -> list[dict]:
    run_id = work_item_run_id(item)
    events = await store.audit_query(principal.tenant_id, run_id=run_id, limit=200)
    active = principal.active_workspace_id
    return [
        {
            "ts": event.ts.isoformat()
            if hasattr(event.ts, "isoformat")
            else str(event.ts),
            "actor": event.actor,
            "actor_tier": event.actor_tier,
            "verb": event.verb,
            "noun": event.noun,
            "status": event.status,
            "detail": event.detail,
        }
        for event in events
        if event.run_id == run_id
        and (event.workspace_id is None or event.workspace_id == active)
    ]
