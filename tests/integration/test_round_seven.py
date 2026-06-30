"""Round Seven control plane - functional invariants (FR-CTL-01/02).

FR-CTL-01  agent/department profile config takes effect LIVE (re-read per call),
           no router reconstruction.
FR-CTL-02  the generic interpreter executes a stored WorkflowDefinition's steps in
           dependency order, each as its own durable boundary, through the kernel.
"""

from __future__ import annotations

import types

import pytest

from nankle.adapters.builtin.memory_tickets import build as build_tickets
from nankle.fleet.chief_of_staff import ChiefOfStaff, Department
from nankle.fleet.workers import LocalDurableExecutor
from nankle.kernel import Kernel
from nankle.models import (
    GrantSet,
    InvocationContext,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
    WorkItem,
    WorkStatus,
)
from nankle.store import InMemoryStore
from nankle.workflows import WorkflowLibrary

T = "acme"


def _work(intent: str, source: str = "chat") -> WorkItem:
    return WorkItem(id=intent, tenant_id=T, source=source, intent=intent,
                    confidence=1.0, convergent=False, status=WorkStatus.PENDING)


@pytest.mark.invariant("FR-CTL-01")
async def test_chief_of_staff_reloads_departments_live():
    live = [Department("eng", intent_keywords=["bug"])]
    cos = ChiefOfStaff(types.SimpleNamespace(), live, departments_provider=lambda: live)

    assert await cos.route(_work("there is a bug")) == "eng"
    # amend the config in place (as an admin/manifest edit would) - NO reconstruction
    live.append(Department("sales", intent_keywords=["deal"]))
    assert await cos.route(_work("close the deal")) == "sales"

    # without a provider, the construction-time list is authoritative (control)
    frozen = ChiefOfStaff(types.SimpleNamespace(), [Department("eng", intent_keywords=["bug"])])
    frozen_list_ignored = [Department("sales", intent_keywords=["deal"])]  # noqa: F841
    assert await frozen.route(_work("close the deal")) == "eng"  # default, sales never added


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="u", run_id="run-7")


def _wf(steps: list[dict]) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf-seven", tenant_id=T, version="1.0.0", source=WorkflowSource.PRECREATED,
        definition={"name": "seven", "version": "1", "steps": steps}, intent_tags=[],
    )


@pytest.mark.invariant("FR-CTL-02")
async def test_interpreter_runs_steps_in_dependency_order_each_durable():
    k = await _kernel()
    executor = LocalDurableExecutor()
    lib = WorkflowLibrary(k.store, executor=executor, kernel=k)
    wf = _wf([
        {"id": "step-2", "parents": ["step-1"], "action": "ticket.create", "params": {"title": "b"}},
        {"id": "step-1", "parents": [], "action": "ticket.create", "params": {"title": "a"}},
    ])
    await lib.register(wf)

    record = await lib.execute(T, wf.id, {}, _ctx())

    assert record["status"] == "completed"
    # both steps actually dispatched through the chokepoint (two real tickets)
    ids = [s["output"]["id"] for s in record["steps"] if s["status"] == "ok"]
    assert len(ids) == 2 and len(set(ids)) == 2
    # each step ran as its OWN durable boundary, parent before child (dep order)
    boundaries = [r.name for r in executor.steps]
    assert boundaries == ["workflow:wf-seven:step-1", "workflow:wf-seven:step-2"]


@pytest.mark.invariant("FR-CTL-02")
async def test_interpreter_skips_descendants_of_a_failed_step():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "a", "parents": [], "action": "ticket.create", "params": {"title": "ok"}},
        {"id": "b", "parents": ["a"], "action": "does.notexist", "params": {}},
        {"id": "c", "parents": ["b"], "action": "ticket.create", "params": {"title": "never"}},
    ])
    await lib.register(wf)

    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert record["status"] == "failed"
    assert by_id["a"]["status"] == "ok"
    assert by_id["b"]["status"] in {"failed", "error"}  # unbound action, fail-closed
    assert by_id["c"]["status"] == "skipped"  # descendant of a failed step never runs
