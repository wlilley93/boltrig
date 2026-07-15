"""Shared helpers for the platform route modules.

These were the module-level helpers of the former monolithic platform_routes.py;
each per-resource module imports them from here. rbac is imported lazily inside
the guards to avoid a circular import at module load (the original pattern).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from boltrig.models import ActionType, AuditEvent, GrantMissing, utcnow
from boltrig.models.work import work_item_run_id


def require_author(p) -> None:
    from boltrig.identity.rbac import can_author

    if not can_author(p.role):
        raise GrantMissing("authoring/admin not permitted for this role")


async def audit_authoring(kernel, p, action: str, detail: dict, status: str = "ok") -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=p.tenant_id, ts=utcnow(), actor=p.subject, actor_tier=p.actor_tier,
            action_type=ActionType.TOOL_CALL, verb=f"authoring.{action}", status=status,
            on_behalf_of=p.on_behalf_of, detail=detail,
        )
    )


@dataclass(frozen=True)
class RunScope:
    """WorkItem-derived run authorization with an audit-only safe fallback."""

    visible: frozenset[str]
    hidden: frozenset[str]
    unrestricted_departments: bool

    def permits(self, run_id: str | None, parent_run_id: str | None = None) -> bool:
        refs = {ref for ref in (run_id, parent_run_id) if ref is not None}
        if refs & self.hidden:
            return False
        return self.unrestricted_departments or bool(refs & self.visible)


async def dept_run_ids(
    kernel, principal, departments: list[str] | None
) -> RunScope:
    """Build visible and hidden WorkItem run sets before audit fallback."""
    all_items = await kernel.list_work(principal.tenant_id)
    visible_items = await scoped_work_items(kernel, principal, departments)
    visible_item_ids = {item.id for item in visible_items}
    visible_ids = {work_item_run_id(item) for item in visible_items}
    hidden_ids = {
        work_item_run_id(item)
        for item in all_items
        if item.id not in visible_item_ids
    }
    return RunScope(
        visible=frozenset(visible_ids),
        hidden=frozenset(hidden_ids),
        unrestricted_departments=departments is None,
    )


async def scoped_work_items(kernel, principal, departments=None):
    return await kernel.list_work(
        principal.tenant_id,
        departments=departments,
        workspace_id=principal.active_workspace_id,
        enforce_workspace=True,
    )


def can_author_route(p) -> bool:
    from boltrig.identity.rbac import can_author

    return can_author(p.role)


def scope_depts(p) -> list[str] | None:
    from boltrig.identity.rbac import departments_for

    return departments_for(p.role, p.scope)


def platform_state(request: Request) -> dict[str, Any]:
    return getattr(request.app.state, "platform", {}) or {}
