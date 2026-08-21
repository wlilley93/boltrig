"""Reverting a run through the dispatch chokepoint (FR-REV-02).

The fake messenger below is the whole point of the harness: its ``send``
answers with the posted message's ``ts`` (the identifier only the SUCCESS
OUTPUT carries), its registered inverse builds ``delete`` params from that
output at record time, and the revert executes the delete THROUGH
``kernel.invoke`` - so the compensation shows up in the audit ledger and the
adapter's own call log exactly like any forward call.
"""

from __future__ import annotations

import pytest

from fastapi import HTTPException

from boltrig.adapters.base import Result, VerbSpec
from boltrig.kernel import Kernel
from boltrig.kernel.effect_inverses import register_inverse
from boltrig.kernel.platform_routes.run_effects import revert_run_effects
from boltrig.models import (
    GrantSet,
    InvocationContext,
    TenantPermissions,
    WorkItem,
)
from boltrig.models.errors import PendingHuman
from boltrig.store import InMemoryStore

T = "acme"


class _Messenger:
    id = "msgr"
    version = "1"
    runtime = "script"
    activated = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._ts = 0

    def describe(self) -> list[VerbSpec]:
        empty = {"type": "object"}
        return [
            # post/delete are low consequence: they record via their registered
            # inverse without pending the HITL gate. wipe is high consequence
            # and has NO inverse - the honest not_undoable case, driven through
            # the same approval dance a real destructive verb would take.
            VerbSpec("msgr.post", "msgr", empty, empty, consequence="low"),
            VerbSpec("msgr.delete", "msgr", empty, empty, consequence="low"),
            VerbSpec("msgr.wipe", "msgr", empty, empty, consequence="high"),
        ]

    async def execute(self, verb, params, credential, context) -> Result:
        self.calls.append((verb, dict(params)))
        if verb == "msgr.post":
            self._ts += 1
            return Result(ok=True, output={"ts": str(self._ts)})
        return Result(ok=True, output={})

    async def health(self) -> str:
        return "ok"


@pytest.fixture()
def scratch_registry(monkeypatch):
    import boltrig.kernel.effect_inverses as module

    monkeypatch.setattr(module, "_BUILDERS", {})
    register_inverse(
        "msgr.post",
        lambda params, output: ("msgr.delete", {"ts": output["ts"]}),
    )


def _ctx(run_id: str) -> InvocationContext:
    return InvocationContext(tenant_id=T, run_id=run_id, grants=GrantSet.of(["*"]))


class _Principal:
    tenant_id = T
    subject = "alice"
    active_workspace_id = None
    grants = GrantSet.of(["*"])


async def _kernel_with_messenger() -> tuple[Kernel, _Messenger]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    messenger = _Messenger()
    await k.register_adapter(T, messenger)
    return k, messenger


async def _seen_run(k: Kernel, run_id: str) -> None:
    """Give the run a work item, so the caller can see what they unwind."""
    await k.store.create_work_item(
        WorkItem(
            id=f"wi-{run_id}",
            tenant_id=T,
            source="internal",
            intent="revert fixture",
            confidence=1.0,
            convergent=True,
            hatchet_run_id=run_id,
        )
    )


async def _revert(k: Kernel, run_id: str) -> list[dict]:
    """The SHIPPED loop (visibility fence included), no HTTP server needed."""
    return await revert_run_effects(k, _Principal(), run_id)


@pytest.mark.invariant("FR-REV-02")
async def test_revert_executes_inverses_lifo_through_dispatch(scratch_registry):
    k, messenger = await _kernel_with_messenger()
    await k.invoke("msgr", "msgr.post", {"text": "one"}, _ctx("run-1"))
    await k.invoke("msgr", "msgr.post", {"text": "two"}, _ctx("run-1"))

    await _seen_run(k, "run-1")
    results = await _revert(k, "run-1")

    assert [r["outcome"] for r in results] == ["reverted", "reverted"]
    # LIFO: message two (ts=2) deleted before message one (ts=1), and the
    # deletes went through the adapter - i.e. through kernel.invoke.
    deletes = [p for v, p in messenger.calls if v == "msgr.delete"]
    assert deletes == [{"ts": "2"}, {"ts": "1"}]
    settled = await k.store.list_run_effects(T, "run-1")
    assert {e.status for e in settled} == {"reverted"}
    # The revert run recorded nothing of its own: the deletes are absent
    # from every run's ledger, so an undo cannot be undone into a loop.
    for effect in settled:
        assert effect.verb_id == "msgr.post"


@pytest.mark.invariant("FR-REV-02")
async def test_not_undoable_rows_are_reported_never_attempted(scratch_registry):
    k, messenger = await _kernel_with_messenger()
    await k.invoke("msgr", "msgr.post", {"text": "keep"}, _ctx("run-2"))
    # wipe is gated (high consequence) and has no registered inverse: the
    # approval dance releases the call, and the ledger owes it an honest row.
    with pytest.raises(PendingHuman) as held:
        await k.invoke("msgr", "msgr.wipe", {}, _ctx("run-2"))
    req_id = held.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    await k.invoke("msgr", "msgr.wipe", {}, _ctx("run-2"), approval_id=req_id)

    await _seen_run(k, "run-2")
    results = await _revert(k, "run-2")

    assert [r["outcome"] for r in results] == ["not_undoable", "reverted"]
    rows = {r["verb"]: r for r in results}
    assert rows["msgr.wipe"]["undoable"] is False
    deletes = [p for v, p in messenger.calls if v == "msgr.delete"]
    assert deletes == [{"ts": "1"}]  # only the invertible effect was attempted
    # post + approved wipe + one delete, and NOTHING else: the not_undoable
    # row produced no adapter call of any kind.
    assert len(messenger.calls) == 3


async def test_a_second_revert_finds_everything_settled(scratch_registry):
    k, messenger = await _kernel_with_messenger()
    await k.invoke("msgr", "msgr.post", {"text": "once"}, _ctx("run-3"))

    await _seen_run(k, "run-3")
    first = await _revert(k, "run-3")
    second = await _revert(k, "run-3")

    assert [r["outcome"] for r in first] == ["reverted"]
    assert [r["outcome"] for r in second] == ["reverted"]  # reported, not re-run
    assert len([1 for v, _ in messenger.calls if v == "msgr.delete"]) == 1


async def test_an_unseen_run_is_404_even_when_rows_exist(scratch_registry):
    # Same fence as every run-scoped read: recording is not permission to read
    # (or unwind). No work item, no revert - even though the ledger has a row.
    k, messenger = await _kernel_with_messenger()
    await k.invoke("msgr", "msgr.post", {"text": "hidden"}, _ctx("run-4"))

    with pytest.raises(HTTPException) as denied:
        await _revert(k, "run-4")

    assert denied.value.status_code == 404
    assert not any(v == "msgr.delete" for v, _ in messenger.calls)
