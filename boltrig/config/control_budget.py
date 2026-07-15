"""Governed budget policy and usage-reset operations."""

from __future__ import annotations

from typing import Any

from boltrig.models import Budget

_ADMIN_ROLES = frozenset({"org-admin", "superadmin", "admin"})
_SCOPE_TYPES = frozenset({"tenant", "department", "workflow"})
_WINDOWS = frozenset({"run", "daily", "monthly"})


def _require_admin(context: Any) -> None:
    role = str((context.extra or {}).get("principal_role") or "")
    if role not in _ADMIN_ROLES:
        raise PermissionError("budget administration requires an authenticated admin")


def _budget_view(budget: Budget) -> dict[str, Any]:
    return {
        "id": budget.id,
        "scope_type": budget.scope_type,
        "window": budget.window,
        "hard_stop": budget.hard_stop,
        "token_limit": budget.token_limit,
        "spent_tokens": budget.spent_tokens,
        "cost_limit_micros": budget.cost_limit_micros,
        "spent_micros": budget.spent_micros,
    }


def _scope(tenant_id: str, params: dict[str, Any]) -> tuple[str, str]:
    scope_type = str(params.get("scope_type") or "").strip()
    scope_id = str(params.get("scope_id") or "").strip()
    if scope_type not in _SCOPE_TYPES or not scope_id:
        raise ValueError("scope_type and scope_id are required")
    if scope_type == "tenant" and scope_id != tenant_id:
        raise PermissionError("tenant budget must target the active organisation")
    return scope_type, scope_id


def _limit(params: dict[str, Any], name: str) -> int | None:
    value = params.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or null")
    return value


async def execute_budget_operation(
    store: Any, verb: str, params: dict[str, Any], context: Any
) -> dict[str, Any] | None:
    if verb not in {"control.budget.upsert", "control.budget.reset"}:
        return None
    _require_admin(context)
    tenant_id = context.tenant_id
    scope_type, scope_id = _scope(tenant_id, params)
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(
        store, None, verb, params, context
    )

    if verb == "control.budget.upsert":
        token_limit = _limit(params, "token_limit")
        cost_limit = _limit(params, "cost_limit_micros")
        if token_limit is None and cost_limit is None:
            raise ValueError("at least one budget limit is required")
        window = str(params.get("window") or "run")
        if window not in _WINDOWS:
            raise ValueError("window must be run, daily, or monthly")
        budget = await store.upsert_budget_policy(
            Budget(
                id=scope_id,
                tenant_id=tenant_id,
                scope_type=scope_type,
                token_limit=token_limit,
                cost_limit_micros=cost_limit,
                hard_stop=bool(params.get("hard_stop", True)),
                window=window,
            )
        )
        return {"budget": _budget_view(budget)}

    reason = str(params.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason is required")
    reset_tokens = bool(params.get("reset_tokens", True))
    reset_cost = bool(params.get("reset_cost", True))
    if not reset_tokens and not reset_cost:
        raise ValueError("at least one counter must be selected")
    budget = await store.reset_budget_usage(
        tenant_id,
        scope_id,
        reset_tokens=reset_tokens,
        reset_cost=reset_cost,
    )
    if budget is None or budget.scope_type != scope_type:
        raise LookupError("budget not found")
    return {"budget": _budget_view(budget), "reason": reason}
