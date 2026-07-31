"""Exact budget usage reads, reservations, and true-up for both stores."""

from __future__ import annotations

from dataclasses import replace

from boltrig.models import Budget, BudgetWindowRef, utcnow

from .budget_windows import usage_view, window_ref


def _aggregate(reservations) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for scope_id, tokens, micros in reservations:
        current_tokens, current_micros = result.get(scope_id, (0, 0))
        result[scope_id] = (
            current_tokens + max(0, tokens),
            current_micros + max(0, micros),
        )
    return result


def _over_limit(policy, tokens: int, micros: int) -> bool:
    return (
        policy["token_limit"] is not None
        and tokens > policy["token_limit"]
    ) or (
        policy["cost_limit_micros"] is not None
        and micros > policy["cost_limit_micros"]
    )


class BudgetUsageMem:
    async def get_budget(self, tenant_id, scope_id, *, run_id=None, at=None):
        policy = self._budgets.get((tenant_id, scope_id))
        if policy is None:
            return None
        observed = at or utcnow()
        if policy.window == "run" and not str(run_id or "").strip():
            return usage_view(policy, None)
        candidate = window_ref(
            scope_id, policy.window, run_id=run_id, at=observed
        )
        existing = self._budget_usage.get(
            (tenant_id, scope_id, candidate.window_key)
        )
        if existing is None:
            return usage_view(policy, candidate)
        ref, tokens, micros = existing
        return usage_view(
            policy, ref, spent_tokens=tokens, spent_micros=micros
        )

    def set_budget(self, budget: Budget) -> None:
        """Legacy fixture/bootstrap setter; governed callers use the async API."""
        observed = utcnow()
        self._budgets[(budget.tenant_id, budget.id)] = replace(
            budget, spent_tokens=0, spent_micros=0
        )
        if (
            budget.window != "run"
            and (budget.spent_tokens or budget.spent_micros)
        ):
            ref = window_ref(
                budget.id, budget.window, run_id=None, at=observed
            )
            self._budget_usage[
                (budget.tenant_id, budget.id, ref.window_key)
            ] = (ref, budget.spent_tokens, budget.spent_micros)

    async def list_budgets(self, tenant_id, *, run_id=None, at=None):
        return [
            budget
            for (current_tenant, scope_id) in self._budgets
            if current_tenant == tenant_id
            and (
                budget := await self.get_budget(
                    tenant_id, scope_id, run_id=run_id, at=at
                )
            )
            is not None
        ]

    async def reconcile_budget(
        self, tenant_id, window, delta_tokens, delta_micros
    ):
        key = (tenant_id, window.scope_id, window.window_key)
        current = self._budget_usage.get(key)
        if (
            current is None
            or current[0].reset_generation != window.reset_generation
        ):
            return
        ref, spent_tokens, spent_micros = current
        self._budget_usage[key] = (
            ref,
            max(0, spent_tokens + delta_tokens),
            max(0, spent_micros + delta_micros),
        )

    async def reserve_budgets_atomic(
        self, tenant_id, reservations, *, run_id=None, at=None
    ):
        """Reserve every metered scope without an await between plan and apply."""
        observed = at or utcnow()
        planned: list[tuple[BudgetWindowRef, int, int]] = []
        for scope_id, (tokens, micros) in _aggregate(reservations).items():
            policy = self._budgets.get((tenant_id, scope_id))
            if policy is None:
                continue
            candidate = window_ref(
                scope_id, policy.window, run_id=run_id, at=observed
            )
            current = self._budget_usage.get(
                (tenant_id, scope_id, candidate.window_key)
            )
            ref, spent_tokens, spent_micros = (
                current if current is not None else (candidate, 0, 0)
            )
            new_tokens = spent_tokens + tokens
            new_micros = spent_micros + micros
            limits = {
                "token_limit": policy.token_limit,
                "cost_limit_micros": policy.cost_limit_micros,
            }
            if policy.hard_stop and _over_limit(
                limits, new_tokens, new_micros
            ):
                return None
            planned.append((ref, new_tokens, new_micros))
        for ref, tokens, micros in planned:
            self._budget_usage[
                (tenant_id, ref.scope_id, ref.window_key)
            ] = (ref, tokens, micros)
        return tuple(ref for ref, _, _ in planned)


async def _pg_usage_view(pool, tenant_id, policy, *, run_id=None, at=None):
    if policy is None:
        return None
    if policy.window == "run" and not str(run_id or "").strip():
        return usage_view(policy, None)
    candidate = window_ref(
        policy.id, policy.window, run_id=run_id, at=at or utcnow()
    )
    row = await pool.fetchrow(
        """SELECT window_started_at, window_ends_at, reset_generation,
                  spent_tokens, spent_micros
           FROM budget_usage
           WHERE tenant_id=$1 AND scope_id=$2 AND window_key=$3""",
        tenant_id,
        policy.id,
        candidate.window_key,
    )
    if row is None:
        return usage_view(policy, candidate)
    ref = replace(
        candidate,
        started_at=row["window_started_at"],
        ends_at=row["window_ends_at"],
        reset_generation=row["reset_generation"],
    )
    return usage_view(
        policy,
        ref,
        spent_tokens=row["spent_tokens"],
        spent_micros=row["spent_micros"],
    )


async def _pg_plan_scope(
    conn, tenant_id, scope_id, tokens, micros, *, run_id, observed
):
    policy = await conn.fetchrow(
        """SELECT token_limit, cost_limit_micros, hard_stop, "window"
           FROM budgets WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
        tenant_id,
        scope_id,
    )
    if policy is None:
        return None, False
    candidate = window_ref(
        scope_id, policy["window"], run_id=run_id, at=observed
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
        candidate.window_key,
        candidate.started_at,
        candidate.ends_at,
    )
    usage = await conn.fetchrow(
        """SELECT window_started_at, window_ends_at, reset_generation,
                  spent_tokens, spent_micros
           FROM budget_usage
           WHERE tenant_id=$1 AND scope_id=$2 AND window_key=$3 FOR UPDATE""",
        tenant_id,
        scope_id,
        candidate.window_key,
    )
    ref = replace(
        candidate,
        started_at=usage["window_started_at"],
        ends_at=usage["window_ends_at"],
        reset_generation=usage["reset_generation"],
    )
    new_tokens = usage["spent_tokens"] + tokens
    new_micros = usage["spent_micros"] + micros
    refused = bool(
        policy["hard_stop"]
        and _over_limit(policy, new_tokens, new_micros)
    )
    return (ref, new_tokens, new_micros), refused


async def _pg_apply_plans(conn, tenant_id, planned) -> None:
    for ref, tokens, micros in planned:
        await conn.execute(
            """UPDATE budget_usage
               SET spent_tokens=$4, spent_micros=$5, updated_at=now()
               WHERE tenant_id=$1 AND scope_id=$2 AND window_key=$3""",
            tenant_id,
            ref.scope_id,
            ref.window_key,
            tokens,
            micros,
        )


class BudgetUsagePG:
    async def get_budget(self, tenant_id, scope_id, *, run_id=None, at=None):
        from .rows import _budget

        row = await self._pool.fetchrow(
            "SELECT * FROM budgets WHERE tenant_id=$1 AND id=$2",
            tenant_id,
            scope_id,
        )
        return await _pg_usage_view(
            self._pool, tenant_id, _budget(row), run_id=run_id, at=at
        )

    async def list_budgets(self, tenant_id, *, run_id=None, at=None):
        from .rows import _budget

        rows = await self._pool.fetch(
            "SELECT * FROM budgets WHERE tenant_id=$1", tenant_id
        )
        return [
            budget
            for row in rows
            if (
                budget := await _pg_usage_view(
                    self._pool,
                    tenant_id,
                    _budget(row),
                    run_id=run_id,
                    at=at,
                )
            )
            is not None
        ]

    async def set_budget(self, budget: Budget) -> None:
        """Compatibility alias; governed callers use upsert_budget_policy."""
        await self.upsert_budget_policy(budget)

    async def reconcile_budget(
        self, tenant_id, window, delta_tokens, delta_micros
    ):
        await self._pool.execute(
            """UPDATE budget_usage
               SET spent_tokens=GREATEST(0, spent_tokens + $4),
                   spent_micros=GREATEST(0, spent_micros + $5),
                   updated_at=now()
               WHERE tenant_id=$1 AND scope_id=$2 AND window_key=$3
                 AND reset_generation=$6""",
            tenant_id,
            window.scope_id,
            window.window_key,
            delta_tokens,
            delta_micros,
            window.reset_generation,
        )

    async def reserve_budgets_atomic(
        self, tenant_id, reservations, *, run_id=None, at=None
    ):
        """Lock policies in stable order and debit all metered scopes or none."""
        from .postgres import _apply_guc
        from .tenant_scope import pool_assumes_app_role

        observed = at or utcnow()
        aggregate = _aggregate(reservations)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))
                planned = []
                for scope_id in sorted(aggregate):
                    tokens, micros = aggregate[scope_id]
                    plan, refused = await _pg_plan_scope(
                        conn,
                        tenant_id,
                        scope_id,
                        tokens,
                        micros,
                        run_id=run_id,
                        observed=observed,
                    )
                    if refused:
                        return None
                    if plan is not None:
                        planned.append(plan)
                await _pg_apply_plans(conn, tenant_id, planned)
                return tuple(ref for ref, _, _ in planned)
