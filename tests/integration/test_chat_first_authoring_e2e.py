"""End-to-end validation of the chat-first authoring loop, inside boltrig.

This is the executable form of the Studio's contract: an agent (here, the
test) authors a workflow THROUGH the governed control plane - never a direct
store write - the high-consequence hold is approved by an independent human,
the approved upsert applies, and the stored definition then RUNS through the
interpreter with the full graphon-parity feature set exercised in one graph:

* ``$inputs`` references feeding a multi-case ``flow.branch``;
* OR-join: the merge node runs once off the taken arm;
* ``on_error: branch`` routing a failed step's "fail" arm;
* ``flow.loop`` with ``parallel: 2`` windowed concurrent iterations;
* honest partial success (``exceptions_count``).

Every mutation and the execution itself go through ``kernel.invoke`` - the
one chokepoint - exactly as the Studio side panel drives it.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.models import (
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary

TENANT = "studio-e2e"

DEFINITION = {
    "name": "studio-authored",
    "version": "1",
    "steps": [
        {"id": "start", "parents": [], "action": "trigger.start", "params": {}},
        {
            "id": "route",
            "parents": ["start"],
            "action": "flow.branch",
            "params": {
                "cases": [
                    {
                        "label": "vip",
                        "conditions": [
                            {"left": "$inputs.tier", "op": "eq", "right": "gold"}
                        ],
                    }
                ],
                "default_label": "standard",
            },
        },
        {
            "id": "vip_ticket",
            "parents": ["route"],
            "branch": "vip",
            "action": "ticket.create",
            "params": {"title": "vip lane"},
        },
        {
            "id": "std_ticket",
            "parents": ["route"],
            "branch": "standard",
            "action": "ticket.create",
            "params": {"title": "standard lane"},
        },
        # OR-join: runs exactly once, off whichever arm was taken.
        {
            "id": "merge",
            "parents": ["vip_ticket", "std_ticket"],
            "action": "ticket.create",
            "params": {"title": "merged"},
        },
        # A step that fails (unbound verb) but is absorbed into a routable arm.
        {
            "id": "flaky",
            "parents": ["merge"],
            "action": "nope.does_not_exist",
            "params": {},
            "on_error": "branch",
        },
        {
            "id": "recover",
            "parents": ["flaky"],
            "branch": "fail",
            "action": "ticket.create",
            "params": {"title": "recovered"},
        },
        # Windowed parallel iteration over a capability-only body.
        {
            "id": "fanout",
            "parents": ["merge"],
            "action": "flow.loop",
            "params": {"items": ["a", "b", "c"], "parallel": 2},
        },
        {
            "id": "item_ticket",
            "parents": ["fanout"],
            "action": "ticket.create",
            "params": {"title": None},
            "loop_bindings": {"title": "item"},
        },
        {"id": "end", "parents": ["recover", "item_ticket"], "action": "flow.end", "params": {}},
    ],
}


def _context() -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(["*"]),
        actor="studio-agent",
        actor_tier="human",
        run_id="run-studio-e2e",
        extra={"principal_role": "superadmin", "principal_scope": {"all": True}},
    )


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["*"])))
    kernel = Kernel(store)
    control = build_control_plane_adapter(store, loader=kernel.loader, registry=kernel.registry)
    control.set_workflows(WorkflowLibrary(store, kernel=kernel))
    await kernel.register_adapter(TENANT, control)
    await kernel.register_adapter(TENANT, build_tickets())
    return kernel


async def _approved(kernel: Kernel, noun: str, verb: str, params: dict) -> dict:
    """Invoke a high-consequence verb through hold -> independent approve -> resume.

    Exactly the Studio loop: first dispatch pauses with a HITL request; a
    different human approves; the SAME params re-dispatch with the approval id
    and the consume-if-approved CAS admits exactly one execution.
    """
    ctx = _context()
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(noun, verb, params, ctx)
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(TENANT, request_id, "approve", "independent-reviewer")
    return await kernel.invoke(noun, verb, params, ctx, approval_id=request_id)


@pytest.mark.invariant("SEC-50")
async def test_chat_first_loop_authors_approves_and_runs_the_full_dag() -> None:
    kernel = await _kernel()

    # Author through the governed verb - the only write path the Studio has.
    await _approved(
        kernel, "control", "control.workflow.upsert",
        {"id": "studio-authored", "definition": DEFINITION},
    )

    # Execute the stored definition, also through the chokepoint.
    output = await _approved(
        kernel, "control", "control.workflow.execute",
        {"workflow_id": "studio-authored", "inputs": {"tier": "gold"}},
    )

    record = output.get("record", output)
    by_id = {s["id"]: s for s in record["steps"]}

    assert record["status"] == "completed"
    # Branch: the $inputs-driven case took the vip arm; the other arm skipped.
    assert by_id["vip_ticket"]["status"] == "ok"
    assert by_id["std_ticket"]["status"] == "skipped"
    # OR-join: the merge ran despite one skipped parent.
    assert by_id["merge"]["status"] == "ok"
    # Error strategy: the unbound verb was absorbed and routed the fail arm.
    assert by_id["flaky"]["status"] == "exception"
    assert by_id["recover"]["status"] == "ok"
    # Parallel loop: three iterations aggregated in item order.
    assert by_id["item_ticket"]["status"] == "ok"
    assert by_id["item_ticket"]["output"]["count"] == 3
    assert len(by_id["item_ticket"]["output"]["iterations"]) == 3
    # Honest partial success: exactly the absorbed failure is counted.
    assert record["exceptions_count"] == 1
