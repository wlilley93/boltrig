"""Budget reservation boundary for one governed fleet spawn."""

from __future__ import annotations

from typing import Any

from boltrig.config.spawn_rules import SpawnRuleSelection
from boltrig.models import AgentCapability, BudgetExceeded, InvocationContext

from .spawn_budget import budget_scope_ids


async def reserve_spawn(
    spawner: Any,
    *,
    tenant_id: str,
    context: InvocationContext,
    capability: AgentCapability,
    skills: list[str],
    prefer: dict[str, Any],
    run_id: str,
    tokens_est: int,
    micros_est: int,
    partial_on_budget: bool,
    spawn_rule: SpawnRuleSelection | None,
) -> Any:
    """Reserve all applicable windows, or return the standard partial envelope."""
    try:
        return await spawner._kernel.cost.reserve(
            tenant_id,
            scope_ids=budget_scope_ids(tenant_id, prefer.get("department")),
            tokens=tokens_est,
            micros=micros_est,
            run_id=run_id,
        )
    except BudgetExceeded:
        await spawner._audit_spawn(
            tenant_id,
            context,
            capability,
            skills,
            run_id,
            status="budget_exceeded",
            tokens=0,
            cost=0,
            spawn_rule=spawn_rule,
        )
        if not partial_on_budget:
            raise
        return spawner._budget_partial(run_id, capability, spawn_rule)
