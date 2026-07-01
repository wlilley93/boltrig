"""Honest executor selection: durability is recorded, optionally fail-closed
(US-EXE-05, Beat 2)."""

import sys

import pytest

from boltrig.fleet.workers import LocalDurableExecutor, register_workers
from boltrig.kernel import Kernel
from boltrig.store import InMemoryStore


def _kernel() -> Kernel:
    return Kernel(InMemoryStore())


@pytest.mark.invariant("US-EXE-05")
def test_require_durable_refuses_to_fall_back(monkeypatch):
    # hatchet unavailable (import fails) + durability required -> refuse to boot
    monkeypatch.setitem(sys.modules, "hatchet_sdk", None)
    monkeypatch.setenv("BOLTRIG_REQUIRE_DURABLE", "1")
    with pytest.raises(RuntimeError, match="BOLTRIG_REQUIRE_DURABLE"):
        register_workers(_kernel())


@pytest.mark.invariant("US-EXE-05")
def test_default_falls_back_to_local_with_durable_false(monkeypatch):
    # default (flag unset): graceful fallback, but non-durability is discoverable
    monkeypatch.setitem(sys.modules, "hatchet_sdk", None)
    monkeypatch.delenv("BOLTRIG_REQUIRE_DURABLE", raising=False)
    executor = register_workers(_kernel())
    assert isinstance(executor, LocalDurableExecutor)
    assert executor.durable is False


@pytest.mark.invariant("US-EXE-05")
async def test_local_enqueue_runs_inline_and_push_event_records():
    executor = LocalDurableExecutor()
    ran: list[dict] = []

    async def body(payload: dict) -> None:
        ran.append(payload)

    executor.register_task("pump", body)
    run_id = await executor.enqueue("pump", {"item": 1})
    # inline execution: the body ran before enqueue returned, as a recorded step
    assert ran == [{"item": 1}]
    assert run_id and any(
        s.name == "task:pump" and s.status == "ok" and s.run_id == run_id
        for s in executor.steps
    )
    # an unregistered task fails closed
    with pytest.raises(KeyError):
        await executor.enqueue("missing", {})
    # push_event records in memory (assertable offline seam)
    await executor.push_event("hitl:approve", {"ok": True}, scope="run-1")
    assert executor.events == [
        {"key": "hitl:approve", "payload": {"ok": True}, "scope": "run-1"}
    ]
