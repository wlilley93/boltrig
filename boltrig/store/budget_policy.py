"""Budget policy mutation contracts shared by memory and Postgres stores."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from boltrig.models import Budget, utcnow

from .budget_windows import window_ref


class BudgetPolicyContract(Protocol):
    async def upsert_budget_policy(self, budget: Budget) -> Budget: ...

    async def reset_budget_usage(
        self, tenant_id: str, scope_id: str, *, reset_tokens: bool = True,
        reset_cost: bool = True, at=None,
    ) -> Budget | None: ...


class BudgetPolicyMem:
    async def upsert_budget_policy(self, budget: Budget) -> Budget:
        key = (budget.tenant_id, budget.id)
        current = self._budgets.get(key)
        observed = utcnow()
        self._budgets[key] = replace(
            budget,
            spent_tokens=0,
            spent_micros=0,
        )
        if current is None and budget.window != "run" and (
            budget.spent_tokens or budget.spent_micros
        ):
            ref = window_ref(
                budget.id, budget.window, run_id=None, at=observed
            )
            self._budget_usage[
                (budget.tenant_id, budget.id, ref.window_key)
            ] = (ref, budget.spent_tokens, budget.spent_micros)
        return await self.get_budget(budget.tenant_id, budget.id, at=observed)

    async def reset_budget_usage(
        self, tenant_id, scope_id, *, reset_tokens=True, reset_cost=True, at=None,
    ):
        key = (tenant_id, scope_id)
        policy = self._budgets.get(key)
        if policy is None:
            return None
        if policy.window == "run":
            raise ValueError(
                "run-window usage resets require an exact run context"
            )
        candidate = window_ref(
            scope_id, policy.window, run_id=None, at=at or utcnow()
        )
        usage_key = (tenant_id, scope_id, candidate.window_key)
        current = self._budget_usage.get(usage_key)
        if current is None:
            ref, tokens, micros = candidate, 0, 0
        else:
            ref, tokens, micros = current
        ref = replace(ref, reset_generation=ref.reset_generation + 1)
        self._budget_usage[usage_key] = (
            ref,
            0 if reset_tokens else tokens,
            0 if reset_cost else micros,
        )
        return await self.get_budget(tenant_id, scope_id, at=at)


class BudgetPolicyPG:
    async def upsert_budget_policy(self, budget: Budget) -> Budget:
        from .postgres import _apply_guc
        from .tenant_scope import pool_assumes_app_role

        observed = utcnow()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))
                inserted = await conn.fetchval(
                    """INSERT INTO budgets (
                           id, tenant_id, scope_type, token_limit,
                           cost_limit_micros, hard_stop, "window",
                           spent_tokens, spent_micros
                       )
                       VALUES ($1,$2,$3,$4,$5,$6,$7,0,0)
                       ON CONFLICT (tenant_id, id) DO NOTHING
                       RETURNING id""",
                    budget.id,
                    budget.tenant_id,
                    budget.scope_type,
                    budget.token_limit,
                    budget.cost_limit_micros,
                    budget.hard_stop,
                    budget.window,
                )
                if inserted is None:
                    await conn.execute(
                        """UPDATE budgets
                           SET scope_type=$3, token_limit=$4,
                               cost_limit_micros=$5, hard_stop=$6,
                               "window"=$7, updated_at=now()
                           WHERE tenant_id=$1 AND id=$2""",
                        budget.tenant_id,
                        budget.id,
                        budget.scope_type,
                        budget.token_limit,
                        budget.cost_limit_micros,
                        budget.hard_stop,
                        budget.window,
                    )
                elif budget.window != "run" and (
                    budget.spent_tokens or budget.spent_micros
                ):
                    ref = window_ref(
                        budget.id,
                        budget.window,
                        run_id=None,
                        at=observed,
                    )
                    await conn.execute(
                        """INSERT INTO budget_usage (
                               tenant_id, scope_id, window_key,
                               window_started_at, window_ends_at,
                               spent_tokens, spent_micros
                           )
                           VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                        budget.tenant_id,
                        budget.id,
                        ref.window_key,
                        ref.started_at,
                        ref.ends_at,
                        budget.spent_tokens,
                        budget.spent_micros,
                    )
        return await self.get_budget(
            budget.tenant_id, budget.id, at=observed
        )

    async def reset_budget_usage(
        self, tenant_id, scope_id, *, reset_tokens=True, reset_cost=True, at=None,
    ):
        observed = at or utcnow()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                from .postgres import _apply_guc
                from .tenant_scope import pool_assumes_app_role

                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))
                policy = await conn.fetchrow(
                    """SELECT "window" FROM budgets
                       WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
                    tenant_id,
                    scope_id,
                )
                if policy is None:
                    return None
                if policy["window"] == "run":
                    raise ValueError(
                        "run-window usage resets require an exact run context"
                    )
                ref = window_ref(
                    scope_id,
                    policy["window"],
                    run_id=None,
                    at=observed,
                )
                await conn.execute(
                    """INSERT INTO budget_usage (
                           tenant_id, scope_id, window_key, window_started_at,
                           window_ends_at, reset_generation
                       )
                       VALUES ($1,$2,$3,$4,$5,0)
                       ON CONFLICT (tenant_id, scope_id, window_key) DO NOTHING""",
                    tenant_id,
                    scope_id,
                    ref.window_key,
                    ref.started_at,
                    ref.ends_at,
                )
                await conn.execute(
                    """UPDATE budget_usage
                       SET spent_tokens=CASE WHEN $4 THEN 0 ELSE spent_tokens END,
                           spent_micros=CASE WHEN $5 THEN 0 ELSE spent_micros END,
                           reset_generation=reset_generation + 1,
                           updated_at=now()
                       WHERE tenant_id=$1 AND scope_id=$2 AND window_key=$3""",
                    tenant_id,
                    scope_id,
                    ref.window_key,
                    reset_tokens,
                    reset_cost,
                )
        return await self.get_budget(tenant_id, scope_id, at=observed)
