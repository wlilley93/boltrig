"""Shared helpers for the platform route modules.

These were the module-level helpers of the former monolithic platform_routes.py;
each per-resource module imports them from here. rbac is imported lazily inside
the guards to avoid a circular import at module load (the original pattern).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from boltrig.models import ActionType, AuditEvent, GrantMissing, utcnow


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


def can_author_route(p) -> bool:
    from boltrig.identity.rbac import can_author

    return can_author(p.role)


def scope_depts(p) -> list[str] | None:
    from boltrig.identity.rbac import departments_for

    return departments_for(p.role, p.scope)


def platform_state(request: Request) -> dict[str, Any]:
    return getattr(request.app.state, "platform", {}) or {}
