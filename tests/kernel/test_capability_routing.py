"""Multi-binding capability routing (docs/SPEC-capability-doctrine.md §2, §8).

The doctrine's determinism principle in test form: a capability may have several
eligible implementations, and every invocation still produces exactly ONE
execution plan - or a structured refusal naming the destinations. The failure
these guard against is the tempting one: picking whichever binding sorted first.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from boltrig.adapters.base import Result, VerbSpec
from boltrig.kernel import Kernel
from boltrig.kernel.routing import operation_class_for, resolve_execution_plan
from boltrig.models import (
    BindingNotFound,
    GrantMissing,
    GrantSet,
    RouteRequired,
    TenantPermissions,
)
from boltrig.models.capability_routing import RoutingPolicy
from boltrig.store import InMemoryStore
from tests.conftest import make_ctx

TENANT = "acme"


class _Crm:
    """A minimal CRM adapter declaring the canonical contact capabilities."""

    runtime = "script"
    source = "builtin"

    def __init__(self, adapter_id: str) -> None:
        self.id = adapter_id
        self.version = "1.0.0"

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id=f"{self.id}.contact.search",
                noun_id="contact",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                output_schema={"type": "object"},
                description="Search contacts",
                implements="crm.contact.search",
            ),
            VerbSpec(
                verb_id=f"{self.id}.contact.create",
                noun_id="contact",
                input_schema={
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                },
                output_schema={"type": "object"},
                # Deliberately LOW: this file is about route selection. Naming the
                # chosen destination inside the HITL prompt is the doctrine's
                # dispatch step 6 and belongs with the transforms work.
                description="Create a contact",
                implements="crm.contact.create",
            ),
        ]

    async def execute(self, verb, params, credential, context) -> Result:
        return Result.success({"served_by": self.id, "verb": verb})

    async def health(self) -> str:
        return "ok"


async def _kernel(*adapter_ids: str) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(
        TenantPermissions(TENANT, GrantSet.of(["crm.*", "hubspot.*", "pipedrive.*"]))
    )
    kernel = Kernel(store)
    for adapter_id in adapter_ids:
        await kernel.register_adapter(TENANT, _Crm(adapter_id))
    return kernel, store


def _ctx():
    return make_ctx(
        [
            "crm.contact.search",
            "crm.contact.create",
            "hubspot.contact.search",
            "hubspot.contact.create",
            "pipedrive.contact.search",
            "pipedrive.contact.create",
        ]
    )


@pytest.mark.kernel
async def test_declared_implements_records_connection_operation_and_binding():
    _, store = await _kernel("hubspot")
    connections = await store.list_provider_connections(TENANT)
    assert [c.id for c in connections] == ["pconn:hubspot"]
    assert connections[0].trust_level == "first_party"
    operations = await store.list_source_operations(TENANT, "pconn:hubspot")
    assert [o.id for o in operations] == [
        "hubspot.contact.create",
        "hubspot.contact.search",
    ]
    bindings = await store.list_capability_bindings(TENANT, "crm.contact.search")
    assert [(b.status, b.created_from, b.ref) for b in bindings] == [
        ("approved", "declared", "crm.contact.search@1")
    ]
    # The digest is what makes a provider schema change detectable rather than
    # silent, so it must actually be recorded on both records.
    assert bindings[0].source_schema_digest == operations[1].schema_digest != ""


@pytest.mark.kernel
async def test_a_second_binding_coexists_rather_than_replacing():
    """The single-binding contract measured in SPEC §11.1, undone at the layer
    that was wrong: two adapters implementing one capability keep both claims."""
    _, store = await _kernel("hubspot", "pipedrive")
    bindings = await store.list_capability_bindings(TENANT, "crm.contact.search")
    assert [b.connection_id for b in bindings] == ["pconn:hubspot", "pconn:pipedrive"]
    # ... while the verb -> adapter binding stays singular, which is correct:
    # one adapter executes one source operation.
    binding = await store.get_binding(TENANT, "hubspot.contact.search")
    assert binding.target_ref == "hubspot"


@pytest.mark.kernel
async def test_one_eligible_binding_routes_the_capability():
    kernel, _ = await _kernel("hubspot")
    out = await kernel.invoke("contact", "crm.contact.search", {"query": "a"}, _ctx())
    assert out["served_by"] == "hubspot"
    assert out["verb"] == "hubspot.contact.search"


@pytest.mark.kernel
async def test_pinned_version_addresses_the_same_route():
    kernel, _ = await _kernel("hubspot")
    out = await kernel.invoke("contact", "crm.contact.search@1", {"query": "a"}, _ctx())
    assert out["served_by"] == "hubspot"


@pytest.mark.kernel
async def test_two_eligible_bindings_refuse_with_named_destinations():
    kernel, _ = await _kernel("hubspot", "pipedrive")
    with pytest.raises(RouteRequired) as caught:
        await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, _ctx())
    detail = caught.value.caller_detail()
    assert detail["capability"] == "crm.contact.create@1"
    assert detail["operation_class"] == "create"
    assert [d["connection"] for d in detail["destinations"]] == ["hubspot", "pipedrive"]
    assert caught.value.status_code == 409


@pytest.mark.kernel
async def test_a_read_is_ambiguous_too_until_fan_out_exists():
    """WP2 refuses rather than answering from one of two CRMs. Doctrine step 3
    turns this into a merged fan-out; until then the refusal is the honest
    answer, and this test is the marker for that change."""
    kernel, _ = await _kernel("hubspot", "pipedrive")
    with pytest.raises(RouteRequired):
        await kernel.invoke("contact", "crm.contact.search", {"query": "a"}, _ctx())


@pytest.mark.kernel
async def test_a_tenant_routing_policy_makes_the_route_deterministic():
    kernel, store = await _kernel("hubspot", "pipedrive")
    await store.upsert_routing_policy(
        RoutingPolicy(
            id="rp-create",
            tenant_id=TENANT,
            capability_id="crm.contact.create",
            binding_id="cb:pconn:pipedrive:pipedrive.contact.create",
            operation_class="create",
        )
    )
    out = await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, _ctx())
    assert out["served_by"] == "pipedrive"


@pytest.mark.kernel
async def test_a_workspace_policy_beats_the_tenant_policy():
    kernel, store = await _kernel("hubspot", "pipedrive")
    for policy in (
        RoutingPolicy(
            id="rp-tenant",
            tenant_id=TENANT,
            capability_id="crm.contact.create",
            binding_id="cb:pconn:hubspot:hubspot.contact.create",
            operation_class="create",
        ),
        RoutingPolicy(
            id="rp-workspace",
            tenant_id=TENANT,
            capability_id="crm.contact.create",
            binding_id="cb:pconn:pipedrive:pipedrive.contact.create",
            operation_class="create",
            scope="workspace",
            workspace_id="ws-1",
        ),
    ):
        await store.upsert_routing_policy(policy)
    ctx = replace(
        make_ctx(["crm.contact.create", "pipedrive.contact.create"]),
        workspace_id="ws-1",
    )
    out = await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, ctx)
    assert out["served_by"] == "pipedrive"


@pytest.mark.kernel
async def test_a_policy_naming_a_dead_binding_is_skipped_not_fatal():
    kernel, store = await _kernel("hubspot")
    await store.upsert_routing_policy(
        RoutingPolicy(
            id="rp-stale",
            tenant_id=TENANT,
            capability_id="crm.contact.create",
            binding_id="cb:pconn:gone:gone.contact.create",
            operation_class="create",
        )
    )
    out = await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, _ctx())
    assert out["served_by"] == "hubspot"


@pytest.mark.kernel
async def test_a_disabled_connection_removes_its_binding_from_routing():
    kernel, store = await _kernel("hubspot", "pipedrive")
    connection = await store.get_provider_connection(TENANT, "pconn:pipedrive")
    connection.status = "disabled"
    await store.upsert_provider_connection(connection)
    out = await kernel.invoke("contact", "crm.contact.search", {"query": "a"}, _ctx())
    assert out["served_by"] == "hubspot"


@pytest.mark.kernel
async def test_no_eligible_binding_fails_closed():
    kernel, store = await _kernel("hubspot")
    connection = await store.get_provider_connection(TENANT, "pconn:hubspot")
    connection.health = "revoked"
    await store.upsert_provider_connection(connection)
    with pytest.raises(BindingNotFound):
        await kernel.invoke("contact", "crm.contact.search", {"query": "a"}, _ctx())


@pytest.mark.kernel
@pytest.mark.invariant("SEC-07")
async def test_the_capability_grant_does_not_bypass_the_source_operation_grant():
    """A canonical name must ADD a check, never replace one: the caller holds
    ``crm.contact.search`` but was never granted the verb behind it."""
    kernel, _ = await _kernel("hubspot")
    ctx = make_ctx(["crm.contact.search"])
    with pytest.raises(GrantMissing):
        await kernel.invoke("contact", "crm.contact.search", {"query": "a"}, ctx)


@pytest.mark.kernel
async def test_an_unknown_capability_still_fails_closed():
    kernel, _ = await _kernel("hubspot")
    with pytest.raises(BindingNotFound):
        await kernel.invoke("contact", "crm.deal.search", {"query": "a"}, _ctx())


@pytest.mark.kernel
async def test_a_stored_verb_never_reaches_the_router():
    """Regression fence for the whole shard: an existing verb id resolves the way
    it always did, so routing can add a destination and never move one."""
    kernel, _ = await _kernel("hubspot")
    out = await kernel.invoke(
        "contact", "hubspot.contact.search", {"query": "a"}, _ctx()
    )
    assert out["verb"] == "hubspot.contact.search"


@pytest.mark.kernel
async def test_operation_class_defaults_to_a_write():
    assert operation_class_for("crm.contact.search") == "read"
    assert operation_class_for("matter.open") == "create"
    assert operation_class_for("filing.archive") == "delete"
    # An unrecognised suffix must land on the branch that never fans out.
    assert operation_class_for("beneficial_owner.verify") == "update"


@pytest.mark.kernel
async def test_the_plan_records_why_it_chose():
    _, store = await _kernel("hubspot")
    plan = await resolve_execution_plan(store, TENANT, "crm.contact.search")
    assert plan.selected_by == "only_eligible"
    assert plan.ref == "crm.contact.search@1"
    assert plan.target.connection_label == "hubspot"
