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
    PendingHuman,
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


async def _kernel(
    *adapter_ids: str, blocking_verbs: set[str] | None = None
) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(
        TenantPermissions(TENANT, GrantSet.of(["crm.*", "hubspot.*", "pipedrive.*"]))
    )
    kernel = Kernel(store, blocking_verbs=blocking_verbs or set())
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


@pytest.mark.kernel
@pytest.mark.invariant("SEC-07")
async def test_route_required_never_reaches_an_ungranted_caller():
    """route_required NAMES the tenant's connections, so it must sit behind the
    grant check rather than in front of it.

    The first cut resolved the route at dispatch step 1 and checked grants at
    step 3, which made an unauthorised /v1/invoke a way to enumerate every CRM a
    tenant had connected, by label. The doctrine's own dispatch order (grant at
    step 3, resolve at step 4) is the fix, and this is why that order is not
    cosmetic.
    """
    kernel, _ = await _kernel("hubspot", "pipedrive")
    ungranted = make_ctx(["hubspot.contact.create", "pipedrive.contact.create"])
    with pytest.raises(GrantMissing) as caught:
        await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, ungranted)
    # The refusal must not carry the destinations - the whole point.
    assert not hasattr(caught.value, "destinations")
    assert "hubspot" not in str(caught.value) and "pipedrive" not in str(caught.value)


@pytest.mark.kernel
@pytest.mark.invariant("SEC-07")
async def test_an_unknown_capability_is_refused_before_the_grant_check():
    """Existence is disclosed, authority is not - the same profile an unknown
    verb id already had, so the capability layer adds no new probe."""
    kernel, _ = await _kernel("hubspot")
    with pytest.raises(BindingNotFound):
        await kernel.invoke("contact", "crm.deal.create", {"email": "a@b"}, make_ctx([]))


@pytest.mark.kernel
@pytest.mark.invariant("SEC-14")
async def test_the_always_block_list_cannot_be_walked_past_by_canonical_name():
    """An operator who blocks hubspot.contact.create means that ACTION, however
    it is addressed. Membership on the typed name alone let the canonical
    spelling skip a deliberate human gate."""
    kernel, _ = await _kernel("hubspot", blocking_verbs={"hubspot.contact.create"})
    with pytest.raises(PendingHuman):
        await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, _ctx())


@pytest.mark.kernel
@pytest.mark.invariant("SEC-14")
async def test_the_always_block_list_also_takes_the_capability_name():
    """Blocking the capability gates the canonical spelling."""
    kernel, _ = await _kernel("hubspot", blocking_verbs={"crm.contact.create"})
    with pytest.raises(PendingHuman):
        await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, _ctx())


@pytest.mark.kernel
@pytest.mark.invariant("SEC-14")
async def test_blocking_a_capability_gates_the_source_operation_it_routes_to():
    """The half that actually matters, and that the first version of this test
    asserted in prose while exercising the trivial path.

    The MCP face offers SOURCE OPERATION verb ids and never capability names, so
    the direct spelling is the only one a model can reach. A capability block
    that governed only the canonical name governed nothing.
    """
    kernel, _ = await _kernel("hubspot", blocking_verbs={"crm.contact.create"})
    with pytest.raises(PendingHuman):
        await kernel.invoke("contact", "hubspot.contact.create", {"email": "a@b"}, _ctx())


@pytest.mark.kernel
@pytest.mark.invariant("SEC-14")
async def test_an_unapproved_binding_does_not_extend_the_block():
    """A block reaches through APPROVED bindings only - the same set routing
    uses. A proposed mapping serves nothing, so it governs nothing."""
    kernel, store = await _kernel("hubspot", blocking_verbs={"crm.contact.create"})
    binding = (await store.list_capability_bindings(TENANT, "crm.contact.create"))[0]
    binding.status = "proposed"
    await store.upsert_capability_binding(binding)
    out = await kernel.invoke(
        "contact", "hubspot.contact.create", {"email": "a@b"}, _ctx()
    )
    assert out["served_by"] == "hubspot"


@pytest.mark.kernel
@pytest.mark.invariant("SEC-14")
async def test_a_version_pinned_block_entry_is_read_as_the_capability():
    """An operator who writes crm.contact.create@1 means that capability.

    Honouring the pin as written makes the gate expire the day a binding's
    version moves; ignoring it makes the gate never fire. Both fail silently, so
    the entry is normalised instead - and it still gates after a version bump.
    """
    kernel, store = await _kernel("hubspot", blocking_verbs={"crm.contact.create@1"})
    with pytest.raises(PendingHuman):
        await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, _ctx())

    binding = (await store.list_capability_bindings(TENANT, "crm.contact.create"))[0]
    binding.capability_version = 2
    await store.upsert_capability_binding(binding)
    with pytest.raises(PendingHuman):
        await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, _ctx())


@pytest.mark.kernel
@pytest.mark.invariant("SEC-14")
async def test_a_binding_consequence_override_raises_the_gate():
    """SPEC §8 step 5: effective consequence comes from the capability AND the
    selected binding. The column was written by the shard and read by nothing,
    so a mapping that declared a route more dangerous than its source operation
    was silently ignored."""
    kernel, store = await _kernel("hubspot")
    binding = (await store.list_capability_bindings(TENANT, "crm.contact.create"))[0]
    binding.consequence_override = "high"
    await store.upsert_capability_binding(binding)
    with pytest.raises(PendingHuman):
        await kernel.invoke("contact", "crm.contact.create", {"email": "a@b"}, _ctx())
    # ... including through the source operation, because the override is a
    # property of the ROUTE and not of the spelling that reached it. Reading it
    # only for the canonical name let the identical call through the identical
    # binding execute ungated.
    with pytest.raises(PendingHuman):
        await kernel.invoke("contact", "hubspot.contact.create", {"email": "a@b"}, _ctx())
    # ... and the un-overridden sibling capability stays ungated.
    out = await kernel.invoke("contact", "crm.contact.search", {"query": "a"}, _ctx())
    assert out["served_by"] == "hubspot"


@pytest.mark.kernel
async def test_the_published_capability_name_is_one_you_can_act_on():
    """The Connections page's most copyable string must be the working one.

    It published `binding.ref` - `crm.contact.search@1` - while every governance
    path reads the UNPINNED id: grant_verbs checks it, blocking_names drops the
    pin, governed_aliases resolves it. So the string most likely to be pasted
    into a role scope or a skill's tool_grants was the one that matches nothing,
    and a grant made from it is legal, silent and inert.
    """
    from boltrig.kernel.platform_routes.integrations import _enabled_capabilities

    kernel, _ = await _kernel("hubspot")
    published = await _enabled_capabilities(kernel, TENANT, "hubspot")
    assert published == ["crm.contact.create", "crm.contact.search"]

    # Each published name, used verbatim as the only capability grant a caller
    # holds, reaches the capability through the real chokepoint.
    for name in published:
        assert GrantSet.of([name]).permits(name), f"{name} is not grantable as written"
    out = await kernel.invoke(
        "contact",
        "crm.contact.search",
        {"query": "a"},
        make_ctx(["crm.contact.search", "hubspot.contact.search"]),
    )
    assert out["served_by"] == "hubspot"
