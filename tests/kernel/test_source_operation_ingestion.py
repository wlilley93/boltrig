"""An external provider's operations reach the capability layer unmapped.

Doctrine step 4 (SPEC §10): "store raw tools as source operations, run the
capability compiler, publish only approved canonical verbs". The compiler
cannot run on operations it cannot see, and until this landed it could not see
any of them: ``register_adapter_verbs`` recorded a source operation only for
specs that ALREADY declared ``implements``, so an operation was invisible to
the capability layer until somebody had mapped it by hand.

The measurement that makes this concrete: the Opbox MCP door publishes 633
verbs and declares ``implements`` on none, so it contributed exactly zero
source operations. That is the whole of "Opbox is not yet built on Boltrig" in
one number.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.base import Result, VerbSpec
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

TENANT = "acme"


class _ConsumedDoor:
    """An external MCP door, like Opbox's: many verbs, no capability claims."""

    runtime = "script"
    source = "generated"  # what a consumed/generated adapter carries

    def __init__(self, adapter_id: str = "opbox", *, implements: str | None = None) -> None:
        self.id = adapter_id
        self.version = "1.0.0"
        self._implements = implements

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id=f"{self.id}.matter.list",
                noun_id="matter",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                description="List matters",
                implements=self._implements,
            ),
            VerbSpec(
                verb_id=f"{self.id}.invoice.issue",
                noun_id="invoice",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                consequence="high",
                description="Issue an invoice",
            ),
        ]

    async def execute(self, verb, params, credential, context) -> Result:
        return Result.success({"verb": verb})


class _Builtin(_ConsumedDoor):
    """Boltrig's own adapter. Same verbs, but ours rather than a provider's."""

    source = "builtin"


async def _register(adapter) -> InMemoryStore:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["*"])))
    await Kernel(store, blocking_verbs=set()).register_adapter(TENANT, adapter)
    return store


@pytest.mark.asyncio
async def test_an_unmapped_external_operation_still_becomes_a_source_operation():
    store = await _register(_ConsumedDoor())

    operations = await store.list_source_operations(TENANT)

    # THE COUNTEREXAMPLE. Before the split this list was EMPTY, because nothing
    # here declares `implements`.
    assert {op.id for op in operations} == {"opbox.matter.list", "opbox.invoice.issue"}


@pytest.mark.asyncio
async def test_an_unmapped_operation_claims_no_capability():
    """Ingestion is not publication.

    A source operation is a record of what exists. It must NOT arrive bound to
    a canonical capability, or step 4 would publish every provider verb under a
    name the model can call without anyone approving the mapping.
    """
    store = await _register(_ConsumedDoor())

    assert await store.list_capability_bindings(TENANT, "crm.contact.search") == []


@pytest.mark.asyncio
async def test_a_declared_operation_still_gets_both_records():
    store = await _register(_ConsumedDoor(implements="matter.list"))

    operations = {op.id for op in await store.list_source_operations(TENANT)}
    bindings = await store.list_capability_bindings(TENANT, "matter.list")

    assert "opbox.matter.list" in operations
    assert [b.source_operation_id for b in bindings] == ["opbox.matter.list"]
    # Consumed, so the claim is evidence and not authority: it lands proposed.
    assert bindings[0].status == "proposed"


@pytest.mark.asyncio
async def test_the_source_operation_carries_what_a_compiler_needs():
    store = await _register(_ConsumedDoor())

    issue = next(
        op for op in await store.list_source_operations(TENANT) if op.id == "opbox.invoice.issue"
    )

    # A digest to detect schema drift, and the provider's own consequence, which
    # is what stops a compiler proposing a write as though it were a read.
    assert issue.schema_digest
    assert issue.consequence_hint == "high"
    assert issue.provider == "opbox"


@pytest.mark.asyncio
async def test_boltrig_s_own_adapters_do_not_flood_the_catalogue():
    """Builtins are Boltrig's verbs, not a provider's catalogue.

    Thirty builtin adapters ingesting on every tenant at every startup is a
    cost with no reader today, so the ingestion is scoped to external providers
    and this is the guard that keeps it scoped.
    """
    store = await _register(_Builtin("clock"))

    assert await store.list_source_operations(TENANT) == []
