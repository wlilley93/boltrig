"""Budget policy mutation contracts shared by memory and Postgres stores."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from boltrig.models import Budget


class BudgetPolicyContract(Protocol):
    async def upsert_budget_policy(self, budget: Budget) -> Budget: ...

    async def reset_budget_usage(
        self, tenant_id: str, scope_id: str, *, reset_tokens: bool = True,
        reset_cost: bool = True,
    ) -> Budget | None: ...


class BudgetPolicyMem:
    async def upsert_budget_policy(self, budget: Budget) -> Budget:
        key = (budget.tenant_id, budget.id)
        current = self._budgets.get(key)
        if current is not None:
            budget = replace(
                budget,
                spent_tokens=current.spent_tokens,
                spent_micros=current.spent_micros,
            )
        self._budgets[key] = budget
        return budget

    async def reset_budget_usage(
        self, tenant_id, scope_id, *, reset_tokens=True, reset_cost=True,
    ):
        key = (tenant_id, scope_id)
        current = self._budgets.get(key)
        if current is None:
            return None
        current = replace(
            current,
            spent_tokens=0 if reset_tokens else current.spent_tokens,
            spent_micros=0 if reset_cost else current.spent_micros,
        )
        self._budgets[key] = current
        return current


class BudgetPolicyPG:
    async def upsert_budget_policy(self, budget: Budget) -> Budget:
        from .postgres import _budget

        row = await self._pool.fetchrow(
            """INSERT INTO budgets (id, tenant_id, scope_type, token_limit, cost_limit_micros,
                                    hard_stop, "window", spent_tokens, spent_micros)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 scope_type=EXCLUDED.scope_type, token_limit=EXCLUDED.token_limit,
                 cost_limit_micros=EXCLUDED.cost_limit_micros, hard_stop=EXCLUDED.hard_stop,
                 "window"=EXCLUDED."window", updated_at=now()
               RETURNING *""",
            budget.id, budget.tenant_id, budget.scope_type, budget.token_limit,
            budget.cost_limit_micros, budget.hard_stop, budget.window,
            budget.spent_tokens, budget.spent_micros,
        )
        return _budget(row)

    async def reset_budget_usage(
        self, tenant_id, scope_id, *, reset_tokens=True, reset_cost=True,
    ):
        from .postgres import _budget

        row = await self._pool.fetchrow(
            """UPDATE budgets
               SET spent_tokens=CASE WHEN $3 THEN 0 ELSE spent_tokens END,
                   spent_micros=CASE WHEN $4 THEN 0 ELSE spent_micros END,
                   updated_at=now()
               WHERE tenant_id=$1 AND id=$2
               RETURNING *""",
            tenant_id, scope_id, reset_tokens, reset_cost,
        )
        return _budget(row)
