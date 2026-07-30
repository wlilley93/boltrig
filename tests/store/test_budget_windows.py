"""Automatic budget-window and exact true-up parity across both stores."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from boltrig.kernel.cost import CostAccountant
from boltrig.models import Budget, BudgetExceeded, BudgetWindowUnavailable

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "window-tenant"
DAY_ONE = datetime(2026, 7, 30, 23, 59, tzinfo=timezone.utc)
DAY_TWO = datetime(2026, 7, 31, 0, 1, tzinfo=timezone.utc)
MONTH_TWO = datetime(2026, 8, 1, 0, 1, tzinfo=timezone.utc)


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(
        "TRUNCATE budget_usage, budgets RESTART IDENTITY CASCADE"
    )
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN,
                reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity",
            ),
        ),
    ]
)
async def store(request):
    instance = await _make_store(request.param)
    yield instance
    close = getattr(instance, "close", None)
    if close is not None:
        await close()


async def _policy(store, *, window: str, limit: int = 100):
    return await store.upsert_budget_policy(
        Budget(
            id=T,
            tenant_id=T,
            scope_type="tenant",
            cost_limit_micros=limit,
            hard_stop=True,
            window=window,
        )
    )


@pytest.mark.store
@pytest.mark.invariant("FR-COST-02")
async def test_daily_window_rolls_at_the_utc_boundary(store):
    await _policy(store, window="daily")
    accountant = CostAccountant(store)

    await accountant.reserve(
        T, [T], tokens=0, micros=100, run_id="run-a", at=DAY_ONE
    )
    with pytest.raises(BudgetExceeded):
        await accountant.reserve(
            T, [T], tokens=0, micros=1, run_id="run-b", at=DAY_ONE
        )
    await accountant.reserve(
        T, [T], tokens=0, micros=100, run_id="run-c", at=DAY_TWO
    )

    first = await store.get_budget(T, T, at=DAY_ONE)
    second = await store.get_budget(T, T, at=DAY_TWO)
    assert first.window_key == "day:2026-07-30"
    assert second.window_key == "day:2026-07-31"
    assert first.spent_micros == second.spent_micros == 100


@pytest.mark.store
@pytest.mark.invariant("FR-COST-02")
async def test_monthly_window_rolls_at_the_utc_boundary(store):
    await _policy(store, window="monthly")
    accountant = CostAccountant(store)

    await accountant.reserve(
        T, [T], tokens=0, micros=100, run_id="run-a", at=DAY_ONE
    )
    with pytest.raises(BudgetExceeded):
        await accountant.reserve(
            T, [T], tokens=0, micros=1, run_id="run-b", at=DAY_TWO
        )
    await accountant.reserve(
        T, [T], tokens=0, micros=100, run_id="run-c", at=MONTH_TWO
    )

    july = await store.get_budget(T, T, at=DAY_ONE)
    august = await store.get_budget(T, T, at=MONTH_TWO)
    assert july.window_key == "month:2026-07"
    assert august.window_key == "month:2026-08"
    assert july.spent_micros == august.spent_micros == 100


@pytest.mark.store
@pytest.mark.invariant("FR-COST-02")
async def test_run_window_is_exact_isolated_and_requires_a_run_id(store):
    await _policy(store, window="run")
    accountant = CostAccountant(store)

    first_receipt = await accountant.reserve(
        T, [T], tokens=0, micros=100, run_id="run-a", at=DAY_ONE
    )
    with pytest.raises(BudgetExceeded):
        await accountant.reserve(
            T, [T], tokens=0, micros=1, run_id="run-a", at=DAY_TWO
        )
    second_receipt = await accountant.reserve(
        T, [T], tokens=0, micros=100, run_id="run-b", at=DAY_TWO
    )
    with pytest.raises(BudgetWindowUnavailable):
        await accountant.reserve(T, [T], tokens=0, micros=1)

    unbound = await store.get_budget(T, T)
    run_a = await store.get_budget(T, T, run_id="run-a", at=DAY_TWO)
    run_b = await store.get_budget(T, T, run_id="run-b", at=DAY_TWO)
    assert unbound.usage_state == "run_context_required"
    assert unbound.window_key is None and unbound.spent_micros == 0
    assert run_a.spent_micros == run_b.spent_micros == 100
    assert first_receipt.windows[0].window_key != second_receipt.windows[0].window_key
    assert "run-a" not in first_receipt.windows[0].window_key


@pytest.mark.store
@pytest.mark.invariant("FR-COST-03")
async def test_true_up_stays_in_the_exact_reserved_window_across_midnight(store):
    await _policy(store, window="daily", limit=1_000)
    accountant = CostAccountant(store)
    receipt = await accountant.reserve(
        T, [T], tokens=80, micros=80, run_id="cross-midnight", at=DAY_ONE
    )

    await accountant.reconcile(receipt, delta_tokens=20, delta_micros=20)

    first = await store.get_budget(T, T, at=DAY_ONE)
    second = await store.get_budget(T, T, at=DAY_TWO)
    assert first.spent_tokens == first.spent_micros == 100
    assert second.spent_tokens == second.spent_micros == 0


@pytest.mark.store
@pytest.mark.invariant("FR-COST-03")
async def test_manual_reset_invalidates_an_older_true_up_receipt(store):
    await _policy(store, window="daily", limit=1_000)
    accountant = CostAccountant(store)
    receipt = await accountant.reserve(
        T, [T], tokens=80, micros=80, run_id="reset-race", at=DAY_ONE
    )

    reset = await store.reset_budget_usage(T, T, at=DAY_ONE)
    await accountant.reconcile(receipt, delta_tokens=20, delta_micros=20)

    current = await store.get_budget(T, T, at=DAY_ONE)
    assert reset.reset_generation == 1
    assert current.reset_generation == 1
    assert current.spent_tokens == current.spent_micros == 0
