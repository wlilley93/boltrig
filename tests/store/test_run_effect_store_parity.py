"""Memory/Postgres parity for the durable run-effect ledger (0085).

The two properties worth a database round trip: seq assignment is atomic and
per-run (the INSERT computes it, so a recorder cannot be handed a stale MAX),
and settle is a real CAS (only one caller wins recorded -> terminal, which is
what makes a concurrent double-revert impossible at the storage layer).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from boltrig.models import RunEffect

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "effect-store-tenant"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute("TRUNCATE run_effects RESTART IDENTITY CASCADE")
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
async def effect_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


def _effect(run_id: str, verb: str = "msgr.post", **kw) -> RunEffect:
    return RunEffect(
        tenant_id=T,
        run_id=run_id,
        seq=0,  # the store assigns the real seq
        verb_id=verb,
        inverse_verb=kw.pop("inverse_verb", "msgr.delete"),
        inverse_params=kw.pop("inverse_params", {"ts": "1"}),
        **kw,
    )


async def test_seq_is_assigned_per_run_and_listed_ascending(effect_store):
    a1 = await effect_store.record_run_effect(_effect("run-a"))
    a2 = await effect_store.record_run_effect(_effect("run-a"))
    b1 = await effect_store.record_run_effect(_effect("run-b"))

    assert (a1.seq, a2.seq, b1.seq) == (1, 2, 1)  # per-run, not global
    listed = await effect_store.list_run_effects(T, "run-a")
    assert [e.seq for e in listed] == [1, 2]
    assert await effect_store.list_run_effects(T, "run-none") == []


async def test_settle_cas_lets_exactly_one_caller_win(effect_store):
    await effect_store.record_run_effect(_effect("run-c"))

    outcomes = await asyncio.gather(*[
        effect_store.settle_run_effect(
            T, "run-c", 1, expected="recorded", status="revert_failed"
        )
        for _ in range(4)
    ])

    assert sorted(outcomes) == [False, False, False, True]
    [row] = await effect_store.list_run_effects(T, "run-c")
    assert row.status == "revert_failed"


async def test_settle_promotes_only_from_the_expected_status(effect_store):
    await effect_store.record_run_effect(_effect("run-d"))
    assert await effect_store.settle_run_effect(
        T, "run-d", 1, expected="recorded", status="revert_failed"
    )
    # The promote leg of the revert loop: claimed -> reverted succeeds once,
    # and a repeat (or a wrong expectation) changes nothing.
    assert await effect_store.settle_run_effect(
        T, "run-d", 1, expected="revert_failed", status="reverted"
    )
    assert not await effect_store.settle_run_effect(
        T, "run-d", 1, expected="recorded", status="reverted"
    )
    [row] = await effect_store.list_run_effects(T, "run-d")
    assert row.status == "reverted"


async def test_rows_read_back_are_copies_not_live_state(effect_store):
    await effect_store.record_run_effect(
        _effect("run-e", inverse_params={"ts": "9", "channel": "C1"})
    )

    [first] = await effect_store.list_run_effects(T, "run-e")
    first.inverse_params["ts"] = "tampered"
    [second] = await effect_store.list_run_effects(T, "run-e")

    assert second.inverse_params == {"ts": "9", "channel": "C1"}


async def test_runs_are_tenant_scoped(effect_store):
    await effect_store.record_run_effect(_effect("run-f"))

    assert await effect_store.list_run_effects("other-tenant", "run-f") == []
    assert not await effect_store.settle_run_effect(
        "other-tenant", "run-f", 1, expected="recorded", status="reverted"
    )
    [row] = await effect_store.list_run_effects(T, "run-f")
    assert row.status == "recorded"
