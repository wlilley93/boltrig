"""Round Seven control plane - security invariants (SEC-50/51).

SEC-50  every workflow step is dispatched through the kernel chokepoint under the
        caller's own grants - a step can neither escalate nor bypass governance.
SEC-51  control-plane config writes are dispatched as kernel verbs (grant-checked,
        audited, HITL-gateable), not an ungoverned store write.
"""

from __future__ import annotations

import pytest

from nankle.adapters.builtin.memory_tickets import build as build_tickets
from nankle.config.control_plane import build_control_plane_adapter
from nankle.kernel import Kernel
from nankle.models import (
    GrantMissing,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from nankle.store import InMemoryStore
from nankle.workflows import WorkflowLibrary

T = "acme"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    await k.register_adapter(T, build_control_plane_adapter(store))
    return k


def _ctx(grants: list[str]) -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(grants), actor="u", run_id="run-7")


def _wf() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf-sec", tenant_id=T, version="1.0.0", source=WorkflowSource.PRECREATED,
        definition={"steps": [
            {"id": "s1", "parents": [], "action": "ticket.create", "params": {"title": "x"}},
        ]}, intent_tags=[],
    )


# --------------------------------------------------------------------------- #
# SEC-50  a workflow step runs through the chokepoint under the caller's grants
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-50")
async def test_workflow_step_cannot_escalate_past_caller_grants():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, kernel=k)
    await lib.register(_wf())

    # caller may NOT create tickets -> the step is denied at the chokepoint, and
    # nothing is created. The stored definition does not grant the step authority.
    record = await lib.execute(T, "wf-sec", {}, _ctx(["ticket.read"]))
    assert record["steps"][0]["status"] == "failed"
    assert await k.store.list_work_items(T) == []  # (sanity) no side effect
    # the very same step succeeds when the caller actually holds the grant
    ok = await lib.execute(T, "wf-sec", {}, _ctx(["ticket.create"]))
    assert ok["steps"][0]["status"] == "ok"


# --------------------------------------------------------------------------- #
# SEC-51  control-plane writes are governed kernel verbs (grant + HITL + audit)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-51")
async def test_control_plane_write_is_grant_checked():
    k = await _kernel()
    # a caller without the control grant cannot amend config
    with pytest.raises(GrantMissing):
        await k.invoke("control", "control.workflow.upsert",
                       {"id": "x", "definition": {"steps": []}}, _ctx(["ticket.read"]))


@pytest.mark.security
@pytest.mark.invariant("SEC-51")
async def test_control_plane_write_is_hitl_gated_and_audited():
    k = await _kernel()
    params = {"id": "authored-wf", "definition": {"steps": []}, "intent_tags": ["x"]}

    # config amendment is high-consequence -> the HITL gate holds it (cannot bypass)
    with pytest.raises(PendingHuman) as exc:
        await k.invoke("control", "control.workflow.upsert", params, _ctx(["*"]))
    req_id = exc.value.hitl_request_id
    assert not await _has_workflow(k, "authored-wf")  # not written while pending

    # approve, then the same verb executes through the chokepoint and writes
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    out = await k.invoke("control", "control.workflow.upsert", params, _ctx(["*"]),
                         approval_id=req_id)
    assert out["upserted"] == "workflow"
    assert await _has_workflow(k, "authored-wf")

    # the amendment was audited as a kernel verb (governed, not a silent store write)
    events = await k.store.audit_query(T, limit=100)
    assert any(e.verb == "control.workflow.upsert" for e in events)


async def _has_workflow(k: Kernel, wf_id: str) -> bool:
    return any(w.id == wf_id for w in await k.store.list_workflows(T))
