"""The review that turns a proposal into a routable capability (doctrine step 4).

THE CHAIN THIS PROVES, END TO END, is the whole of "Opbox is built on Boltrig":

    an Opbox door registers
        -> its operations become source operations (nothing declared)
        -> the shipped pack PROPOSES canonical bindings
        -> the capability is NOT routable, because a proposal is not authority
        -> an operator approves through a governed, HITL-gated verb
        -> the capability routes to Opbox

Before this existed the chain stopped at step three: proposals accumulated with
nothing able to move them, so the pack filled an inbox that had no door.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.base import Result, VerbSpec
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.routing import resolve_execution_plan
from boltrig.models import (
    AdapterFailure,
    BindingNotFound,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.models.capability_routing import ProviderConnection
from boltrig.store import InMemoryStore

T = "review"


class _OpboxDoor:
    runtime = "script"
    source = "generated"
    id = "opbox"
    version = "1.0.0"

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="opbox.create_matter",
                noun_id="matter",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                description="Create a matter",
            )
        ]

    async def execute(self, verb, params, credential, context) -> Result:
        return Result.success({"verb": verb})


def _context(verb: str) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="author",
        actor_tier="human",
        run_id=f"run-{verb.rsplit('.', 1)[-1]}",
        extra={"principal_role": "org-admin", "principal_scope": {"all": True}},
    )


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, _OpboxDoor())
    await kernel.register_adapter(
        T, build_control_plane_adapter(store, loader=kernel.loader, registry=kernel.registry)
    )
    # The connection the pack bound must be eligible for routing; a live door is
    # what a real deployment has, and an unhealthy one would mask the test.
    connection = await store.get_provider_connection(T, "pconn:opbox")
    await store.upsert_provider_connection(
        ProviderConnection(**{**connection.__dict__, "health": "ok"})
    )
    return kernel


async def _approve(kernel: Kernel, binding_id: str) -> dict:
    verb, params = "control.capability_binding.approve", {"binding_id": binding_id}
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context(verb))
    await kernel.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer")
    return await kernel.invoke(
        "control", verb, params, _context(verb), approval_id=held.value.hitl_request_id
    )


@pytest.mark.asyncio
async def test_a_proposed_binding_does_not_route():
    kernel = await _kernel()

    with pytest.raises(BindingNotFound):
        await resolve_execution_plan(kernel.store, T, "matter.open")


@pytest.mark.asyncio
async def test_approving_a_binding_makes_the_capability_route_to_opbox():
    kernel = await _kernel()
    binding = (await kernel.store.list_capability_bindings(T, "matter.open"))[0]

    await _approve(kernel, binding.binding_id)

    plan = await resolve_execution_plan(kernel.store, T, "matter.open")
    assert plan.target.source_operation_id == "opbox.create_matter"
    assert plan.selected_by == "only_eligible"


@pytest.mark.asyncio
async def test_approval_is_held_for_a_human_before_it_publishes_anything():
    """Approving is what makes a verb model-callable, so it is HITL-gated.

    The first invocation must NOT publish: it raises PendingHuman and the
    capability stays unroutable until a person answers.
    """
    kernel = await _kernel()
    binding = (await kernel.store.list_capability_bindings(T, "matter.open"))[0]
    verb = "control.capability_binding.approve"

    with pytest.raises(PendingHuman):
        await kernel.invoke("control", verb, {"binding_id": binding.binding_id}, _context(verb))

    with pytest.raises(BindingNotFound):
        await resolve_execution_plan(kernel.store, T, "matter.open")


@pytest.mark.asyncio
async def test_rejecting_keeps_the_claim_but_never_routes_it():
    kernel = await _kernel()
    binding = (await kernel.store.list_capability_bindings(T, "matter.open"))[0]
    verb, params = "control.capability_binding.reject", {"binding_id": binding.binding_id}

    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context(verb))
    await kernel.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer")
    await kernel.invoke(
        "control", verb, params, _context(verb), approval_id=held.value.hitl_request_id
    )

    # Disabled, not deleted: the record that a claim was made and refused is
    # what a review queue needs in order not to re-propose it forever.
    refused = (await kernel.store.list_capability_bindings(T, "matter.open"))[0]
    assert refused.status == "disabled"
    with pytest.raises(BindingNotFound):
        await resolve_execution_plan(kernel.store, T, "matter.open")


@pytest.mark.asyncio
async def test_approving_a_binding_that_does_not_exist_is_not_a_silent_success():
    kernel = await _kernel()
    verb, params = "control.capability_binding.approve", {"binding_id": "cb:nope"}

    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context(verb))
    await kernel.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer")
    # It FAILS rather than answering "ok". An approval naming a stale id is
    # usually a stale review queue, and a silent success would leave an operator
    # believing they had published something.
    with pytest.raises(AdapterFailure, match="capability binding not found"):
        await kernel.invoke(
            "control", verb, params, _context(verb), approval_id=held.value.hitl_request_id
        )
