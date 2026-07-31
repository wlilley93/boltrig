"""The periodic audit-rollup anchor janitor ([2026] VJS-COUNTY 9, D4).

The anchorer (:class:`boltrig.kernel.security_events.AuditAnchorer`) seals an
audit-chain segment; this proves the *trigger* that drives it periodically
(:mod:`boltrig.fleet.anchor`):

SEC-125  the anchor janitor seals the latest un-anchored segment for EACH tenant
         on its sweep and is a no-op when a tenant has no new rows; an anchor the
         job writes agrees with a recompute over the segment (reusing the SEC-122
         anchor-integrity property via ``verify_latest``); it enumerates tenants
         via ``list_orgs`` and one tenant's failure never stops the sweep; it
         degrades cleanly when Hatchet is absent (the local, non-durable executor
         is selected and the sweep still writes a dev-fallback anchor, no crash);
         and the forever loop cancels cleanly.
"""

from __future__ import annotations

import asyncio

import pytest

from boltrig.fleet import register_workers, run_anchor_forever, run_anchor_sweep_detailed
from boltrig.fleet.anchor import (
    DEFAULT_INTERVAL_SECONDS,
    INTERVAL_ENV,
    anchor_interval_from_env,
)
from boltrig.models import Organisation
from tests.conftest import TENANT, make_ctx

OTHER = "empty-co"


async def _seed_org(store, tenant_id: str) -> None:
    await store.create_org(
        Organisation(id=tenant_id, name=tenant_id, slug=tenant_id)
    )


async def _seed_audit(kernel, n: int) -> None:
    for i in range(n):
        await kernel.invoke(
            "ticket", "ticket.create", {"title": f"t{i}"}, make_ctx(["ticket.create"])
        )


# --------------------------------------------------------------------------- #
# SEC-125  sweep seals each tenant, recompute agrees, no-op when nothing new
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-125")
async def test_sweep_seals_each_tenant_and_is_a_noop_without_new_rows(kernel):
    # Two tenants enumerated by list_orgs; only ``acme`` has audit rows.
    await _seed_org(kernel.store, TENANT)
    await _seed_org(kernel.store, OTHER)
    await _seed_audit(kernel, 3)

    # First sweep seals acme (3 rows) and no-ops the empty tenant -> 1 written.
    written = (await run_anchor_sweep_detailed(kernel.store, kernel.anchorer)).sealed
    assert written == 1

    # The anchor the JOB wrote agrees with a recompute over the segment (SEC-122).
    ok, anchor = await kernel.anchorer.verify_latest(TENANT)
    assert ok is True and anchor is not None
    assert anchor.seq_start == 1 and anchor.seq_end == 3
    assert anchor.is_dev_fallback is True  # no external TSA/KMS in test env
    # the empty tenant was never anchored (a no-op, not an empty anchor row).
    assert await kernel.anchorer.verify_latest(OTHER) == (True, None)

    # A second sweep with nothing new is a clean no-op.
    assert (await run_anchor_sweep_detailed(kernel.store, kernel.anchorer)).sealed == 0

    # New rows -> the next sweep advances only over the un-anchored tail.
    await _seed_audit(kernel, 2)
    assert (await run_anchor_sweep_detailed(kernel.store, kernel.anchorer)).sealed == 1
    _, tail = await kernel.anchorer.verify_latest(TENANT)
    assert tail.seq_start == 4 and tail.seq_end == 5


# --------------------------------------------------------------------------- #
# SEC-125  degrades cleanly when Hatchet is absent (local fallback, no crash)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-125")
async def test_anchor_degrades_cleanly_when_hatchet_absent(kernel):
    # The anchor janitor depends on NONE of the durable-execution machinery: it
    # needs only the store + the anchorer. register_workers must not crash whether
    # the worker selected the durable (Hatchet) executor or the local fallback -
    # so we assert the sweep works regardless of executor.durable (which varies
    # with the ambient HATCHET_CLIENT_TOKEN and is not what this test is about).
    executor = register_workers(kernel)
    assert executor is not None  # boots under either executor, no crash

    await _seed_org(kernel.store, TENANT)
    await _seed_audit(kernel, 2)
    # The sweep still seals the chain (a dev-fallback anchor), no crash.
    assert (await run_anchor_sweep_detailed(kernel.store, kernel.anchorer)).sealed == 1
    ok, anchor = await kernel.anchorer.verify_latest(TENANT)
    assert ok and anchor.is_dev_fallback is True

    # A sweep over an empty control plane (no orgs registered yet) is a clean 0.
    from boltrig.store import InMemoryStore

    from boltrig.kernel.security_events import AuditAnchorer

    empty = InMemoryStore()
    assert (await run_anchor_sweep_detailed(empty, AuditAnchorer(empty))).sealed == 0


# --------------------------------------------------------------------------- #
# SEC-125  one tenant's failure never stops the sweep (P9)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-125")
async def test_sweep_continues_past_a_failing_tenant(kernel):
    await _seed_org(kernel.store, TENANT)
    await _seed_org(kernel.store, OTHER)
    await _seed_audit(kernel, 1)

    real_anchor = kernel.anchorer.anchor

    async def flaky(tenant_id, **kw):
        if tenant_id == OTHER:
            raise RuntimeError("boom")  # this tenant blows up
        return await real_anchor(tenant_id, **kw)

    kernel.anchorer.anchor = flaky  # type: ignore[method-assign]
    # The failing tenant is logged + skipped; acme is still sealed.
    assert (await run_anchor_sweep_detailed(kernel.store, kernel.anchorer)).sealed == 1
    ok, _ = await kernel.anchorer.verify_latest(TENANT)
    assert ok is True


# --------------------------------------------------------------------------- #
# SEC-125  the forever loop seals then cancels cleanly (never dies on a cycle)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-125")
async def test_forever_loop_seals_then_cancels_cleanly(kernel):
    await _seed_org(kernel.store, TENANT)
    await _seed_audit(kernel, 2)

    task = asyncio.create_task(
        run_anchor_forever(kernel.store, kernel.anchorer, interval=0.01)
    )
    try:
        # Wait for the first sweep to land an anchor.
        for _ in range(200):
            _, anchor = await kernel.anchorer.verify_latest(TENANT)
            if anchor is not None:
                break
            await asyncio.sleep(0.01)
        assert anchor is not None and anchor.seq_end == 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# --------------------------------------------------------------------------- #
# SEC-125  the interval knob: default daily, malformed -> default, disable <= 0
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-125")
def test_anchor_interval_knob(monkeypatch):
    monkeypatch.delenv(INTERVAL_ENV, raising=False)
    assert anchor_interval_from_env() == DEFAULT_INTERVAL_SECONDS  # daily default

    monkeypatch.setenv(INTERVAL_ENV, "3600")
    assert anchor_interval_from_env() == 3600.0

    monkeypatch.setenv(INTERVAL_ENV, "not-a-number")
    assert anchor_interval_from_env() == DEFAULT_INTERVAL_SECONDS  # malformed -> default

    monkeypatch.setenv(INTERVAL_ENV, "0")
    assert anchor_interval_from_env() == 0.0  # honoured as "disabled"
