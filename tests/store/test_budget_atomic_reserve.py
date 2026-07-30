"""Transactional multi-scope budget reserve (audit H4, engine-plan Phase 6,
FR-COST-05).

The day-1 H4 fix made ``CostAccountant.reserve`` HONOUR a store refusal; the true
fix pinned here is a single-transaction, all-or-nothing multi-scope reserve. The
old ``reserve`` looped ``consume_budget`` per scope, so a concurrent reserve could
debit scope A, then have scope B refuse, leaving A charged for a call that never
ran (a partial reserve). ``store.reserve_budgets_atomic`` debits EVERY scope or
NONE: postgres locks every row FOR UPDATE in a deterministic order and re-checks
each hard stop under the lock; memory applies the same all-or-nothing under its
no-await lock.

Same parity pattern as test_durable_delegation: ONE set of contract assertions
runs against BOTH backends; the memory backend runs everywhere, the postgres
backend runs when BOLTRIG_TEST_DATABASE_URL is set (CI) and skips cleanly offline.
On postgres the concurrency test genuinely fails against the old per-scope loop
(a real row-level race produces the partial debit); memory serialises the two
reserves (its store methods never yield), so it holds the same contract by
construction.
"""

from __future__ import annotations

import asyncio
import inspect
import os

import pytest

from boltrig.kernel.cost import CostAccountant
from boltrig.models import Budget, BudgetExceeded

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = "budgets"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity"
            ),
        ),
    ]
)
async def store(request):
    s = await _make_store(request.param)
    yield s
    close = getattr(s, "close", None)
    if close is not None:
        await close()


async def _set_budget(store, budget: Budget) -> None:
    # set_budget is sync on the memory store, async on postgres - bridge both.
    res = store.set_budget(budget)
    if inspect.isawaitable(res):
        await res


def _budget(scope_id: str, *, limit: int, spent: int = 0, hard: bool = True) -> Budget:
    return Budget(
        id=scope_id, tenant_id=T, scope_type="department",
        cost_limit_micros=limit, spent_micros=spent, hard_stop=hard,
        window="daily",
    )


# --- all-or-nothing under a refusing scope (audit H4, FR-COST-05) ------------
@pytest.mark.store
@pytest.mark.invariant("FR-COST-05")
async def test_multi_scope_reserve_is_all_or_nothing(store):
    # scope A ("tenant") has headroom; scope B ("dept:eng") is a hard stop already
    # at its limit. A reserve over both must debit NEITHER (return False, no partial).
    await _set_budget(store, _budget("tenant", limit=10_000))
    await _set_budget(store, _budget("dept:eng", limit=100, spent=100))

    ok = await store.reserve_budgets_atomic(T, [("tenant", 0, 50), ("dept:eng", 0, 50)])
    assert ok is None  # the second scope refuses -> the whole reserve refuses
    # the FIRST scope must NOT have been debited (the partial-reserve bug is gone).
    assert (await store.get_budget(T, "tenant")).spent_micros == 0
    assert (await store.get_budget(T, "dept:eng")).spent_micros == 100

    # and through CostAccountant.reserve: it raises AND leaves the first scope clean.
    acct = CostAccountant(store)
    with pytest.raises(BudgetExceeded):
        await acct.reserve(T, ["tenant", "dept:eng"], tokens=0, micros=50)
    assert (await store.get_budget(T, "tenant")).spent_micros == 0


@pytest.mark.store
@pytest.mark.invariant("FR-COST-05")
async def test_reserve_debits_every_scope_when_all_fit(store):
    # the inverse: when every scope has headroom, EVERY scope is debited.
    await _set_budget(store, _budget("tenant", limit=10_000))
    await _set_budget(store, _budget("dept:eng", limit=1_000))

    ok = await store.reserve_budgets_atomic(T, [("tenant", 0, 200), ("dept:eng", 0, 200)])
    assert ok is not None
    assert (await store.get_budget(T, "tenant")).spent_micros == 200
    assert (await store.get_budget(T, "dept:eng")).spent_micros == 200

    # a scope with no budget row is a no-op (unmetered), mirroring consume_budget.
    ok2 = await store.reserve_budgets_atomic(T, [("tenant", 0, 100), ("no-budget", 0, 999)])
    assert ok2 is not None
    assert (await store.get_budget(T, "tenant")).spent_micros == 300
    assert await store.get_budget(T, "no-budget") is None


# --- concurrency: two reserves contending on a shared scope ------------------
@pytest.mark.store
@pytest.mark.invariant("FR-COST-05")
async def test_concurrent_multi_scope_reserves_cannot_partially_debit(store):
    # A shared hard-stop scope with room for EXACTLY ONE 100-micro reserve, plus a
    # private scope per reserver. The shared scope is passed SECOND, so the old
    # per-scope loop would debit the private scope first, then have the shared scope
    # refuse - a partial debit. The transactional reserve debits the private scope
    # only if the shared one also fits, so the loser's private scope stays at 0.
    await _set_budget(store, _budget("shared", limit=100))
    await _set_budget(store, _budget("dept:a", limit=10_000))
    await _set_budget(store, _budget("dept:b", limit=10_000))
    acct = CostAccountant(store)

    results = await asyncio.gather(
        acct.reserve(T, ["dept:a", "shared"], tokens=0, micros=100),
        acct.reserve(T, ["dept:b", "shared"], tokens=0, micros=100),
        return_exceptions=True,
    )
    refused = [r for r in results if isinstance(r, BudgetExceeded)]
    won = [r for r in results if not isinstance(r, BaseException)]
    assert len(refused) == 1 and len(won) == 1  # exactly one full reserve, one refused

    # the shared scope reflects EXACTLY ONE reserve - never two, never a partial.
    assert (await store.get_budget(T, "shared")).spent_micros == 100
    # exactly one private scope was debited (the winner's); the loser's stays clean.
    a = (await store.get_budget(T, "dept:a")).spent_micros
    b = (await store.get_budget(T, "dept:b")).spent_micros
    assert {a, b} == {0, 100}  # one winner debited its private scope, the loser none
