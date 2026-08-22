"""An approval does not survive a change to the contract it approved.

``source_schema_digest`` was written on every binding from the day the shard
landed and read by nothing. The bytes made a divergence "at least detectable"
(SPEC §11.9); nothing detected it, so an approved binding outlived any change
to the operation behind it and the capability kept being offered against a
contract nobody had approved.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from boltrig.adapters.base import Result, VerbSpec
from boltrig.kernel import Kernel
from boltrig.kernel.capability_offer import offer_candidates
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "drift"

_NARROW = {"type": "object", "properties": {"name": {"type": "string"}}}
_MOVED = {"type": "object", "properties": {"full_name": {"type": "string"}}}


class _Door:
    runtime = "script"
    source = "generated"
    id = "opbox"
    version = "1.0.0"

    def __init__(self, schema: dict) -> None:
        self._schema = schema

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="opbox.create_matter",
                noun_id="matter",
                input_schema=self._schema,
                output_schema={"type": "object"},
                description="Create a matter",
            )
        ]

    async def execute(self, verb, params, credential, context) -> Result:
        return Result.success({})


async def _kernel_with_approved_binding() -> tuple[Kernel, str]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store, blocking_verbs=set())
    await kernel.register_adapter(T, _Door(_NARROW))
    binding = (await store.list_capability_bindings(T, "matter.open"))[0]
    await store.set_capability_binding_status(T, binding.binding_id, "approved", "reviewer")
    return kernel, binding.binding_id


def _permits(name: str) -> bool:
    return True


@pytest.mark.asyncio
async def test_an_approved_binding_returns_to_review_when_its_schema_moves():
    kernel, binding_id = await _kernel_with_approved_binding()

    await kernel.register_adapter(T, _Door(_MOVED))

    binding = (await kernel.store.list_capability_bindings(T, "matter.open"))[0]
    assert binding.binding_id == binding_id
    assert binding.status == "proposed"
    # The reviewer is cleared with the approval: the record must not read as
    # though that person approved the contract that is there now.
    assert binding.reviewed_by is None


@pytest.mark.asyncio
async def test_the_capability_leaves_the_offer_until_it_is_approved_again():
    """The consequence that matters, stated as behaviour rather than as status."""
    kernel, _ = await _kernel_with_approved_binding()
    before = {v.id for v in await offer_candidates(kernel.store, T, permits=_permits)}
    assert "matter.open" in before

    await kernel.register_adapter(T, _Door(_MOVED))

    after = {v.id for v in await offer_candidates(kernel.store, T, permits=_permits)}
    assert "matter.open" not in after
    # And the provider's own verb comes back, so nobody loses reach.
    assert "opbox.create_matter" in after


@pytest.mark.asyncio
async def test_re_registering_an_unchanged_operation_disturbs_nothing():
    """THE COUNTERWEIGHT. Registration runs at every startup.

    A reconciliation that demoted on every boot would make approval useless.
    """
    kernel, _ = await _kernel_with_approved_binding()

    await kernel.register_adapter(T, _Door(_NARROW))

    binding = (await kernel.store.list_capability_bindings(T, "matter.open"))[0]
    assert binding.status == "approved"
    assert binding.reviewed_by == "reviewer"


@pytest.mark.asyncio
async def test_an_operation_this_pass_never_saw_is_left_alone():
    """Silence is not evidence of a change.

    A second adapter registering must not demote the first adapter's approvals
    merely by not mentioning its operations.
    """
    kernel, _ = await _kernel_with_approved_binding()

    class _Other(_Door):
        id = "hubspot"

        def describe(self):
            return [replace(super().describe()[0], verb_id="hubspot.create_deal")]

    await kernel.register_adapter(T, _Other(_NARROW))

    binding = (await kernel.store.list_capability_bindings(T, "matter.open"))[0]
    assert binding.status == "approved"


@pytest.mark.asyncio
async def test_a_proposed_binding_is_not_touched_by_a_schema_change():
    """There is no approval to withdraw, and no reviewer to clear."""
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store, blocking_verbs=set())
    await kernel.register_adapter(T, _Door(_NARROW))

    await kernel.register_adapter(T, _Door(_MOVED))

    binding = (await store.list_capability_bindings(T, "matter.open"))[0]
    assert binding.status == "proposed"
