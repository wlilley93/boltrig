"""The fleet worker starts the janitors the record says it starts.

Right-to-erasure (M11 / SEC-74 / DATA-07 / PRIV-04) was recorded as BUILT in
docs/security-conformance.md while `purge_closed_conversations` had never been
called in any deployment. The purge itself was tested - three tests drove
`run_retention_once` by hand and passed - so the store method was proven and the
thing that would have called it did not exist. `run_retention_forever` had zero
callers: no compose service, no Makefile target, no deploy unit, no `__main__`,
only a docstring telling the reader to schedule it themselves.

A test for the purge is not a test for erasure. This one asserts the wiring: that
the process operators actually run starts the loop, and that turning it off is a
choice someone made rather than the default.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from boltrig.api import worker as worker_mod


class _Pump:
    """Stands in for the delegation pump: blocks so the janitors stay alive."""

    heads: dict = {}

    def __init__(self) -> None:
        self.running = asyncio.Event()

    async def run_forever(self, tenant: str, interval: float = 0.0) -> None:
        self.running.set()
        await asyncio.Event().wait()  # never returns; the test cancels it


class _Executor:
    durable = False


class _Kernel:
    store = object()
    anchorer = object()


async def _janitor_names(monkeypatch, **env) -> set[str]:
    """Run the worker far enough to see which janitors it started."""
    for key in (
        "BOLTRIG_RETENTION_INTERVAL",
        "BOLTRIG_AUDIT_ANCHOR_INTERVAL",
        "BOLTRIG_HITL_EXPIRY_INTERVAL",
        "REDIS_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    pump = _Pump()
    monkeypatch.setattr(worker_mod, "build_kernel_async", _async(_Kernel()))
    monkeypatch.setattr(worker_mod, "register_workers", lambda k: _Executor())
    monkeypatch.setattr(worker_mod, "_find_manifest", lambda: None)
    monkeypatch.setattr(worker_mod, "load_settings", lambda: object())
    monkeypatch.setattr(worker_mod, "build_spawner", lambda k: object())
    monkeypatch.setattr(worker_mod, "build_codex_execution_stack", lambda s, st: None)
    monkeypatch.setattr(worker_mod, "build_org", lambda *a, **kw: pump)
    # The janitor bodies never need to do work; only being STARTED is the claim.
    monkeypatch.setattr(worker_mod, "run_retention_forever", _forever)
    monkeypatch.setattr(worker_mod, "run_anchor_forever", _forever)

    task = asyncio.create_task(worker_mod._run())
    try:
        await asyncio.wait_for(pump.running.wait(), timeout=5)
        return {t.get_name() for t in asyncio.all_tasks()}
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _async(value):
    async def _call(*a, **kw):
        return value
    return _call


async def _forever(*a, **kw) -> None:
    await asyncio.Event().wait()


@pytest.mark.invariant("SEC-74")
async def test_the_fleet_worker_starts_the_retention_janitor(monkeypatch) -> None:
    """The wiring erasure depends on. Absent it, a DELETE only soft-closes."""
    names = await _janitor_names(monkeypatch)
    assert "retention-janitor" in names, (
        "the fleet worker did not start the retention janitor, so no deployment "
        "hard-erases a closed conversation"
    )


@pytest.mark.invariant("SEC-74")
async def test_the_retention_janitor_is_off_only_when_someone_turns_it_off(
    monkeypatch,
) -> None:
    """Disabled must be a decision on the record, not the default it used to be."""
    names = await _janitor_names(monkeypatch, BOLTRIG_RETENTION_INTERVAL="0")
    assert "retention-janitor" not in names
