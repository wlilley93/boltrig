"""Authoring routing policies, and the two routes that would never fire (A5).

``RoutingPolicy`` has had a model, a table and a store since the routing shard
landed, and had ZERO routes, verbs or SDK methods, so selection always fell
through to binding priority. These are the verbs that make the doctrine's
"under these circumstances select this binding" reachable from outside the
process, and the validations that keep an author from writing a route that
resolves to nothing.

There is no foreign key from ``routing_policies`` to ``capability_bindings``,
so every one of these refusals is enforced here or nowhere.
"""

from __future__ import annotations

import pytest

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.config.control_routing_policies import ROUTING_POLICY_INVALID
from boltrig.kernel import Kernel
from boltrig.models import (
    AdapterFailure,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    SourceOperation,
)
from boltrig.store import InMemoryStore

T = "routing-policy-tenant"


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
    await store.upsert_provider_connection(
        ProviderConnection(
            id="pconn:opbox", tenant_id=T, label="Opbox", provider="opbox",
            adapter_id="opbox",
        )
    )
    for operation_id in ("opbox.create_matter", "opbox.close_matter"):
        await store.upsert_source_operation(
            SourceOperation(
                id=operation_id, tenant_id=T, provider="opbox",
                connection_id="pconn:opbox",
            )
        )
    for binding_id, capability, operation, status in (
        ("cb:open", "matter.open", "opbox.create_matter", "approved"),
        ("cb:close", "matter.close", "opbox.close_matter", "proposed"),
    ):
        await store.upsert_capability_binding(
            CapabilityBinding(
                binding_id=binding_id, tenant_id=T, capability_id=capability,
                source_operation_id=operation, connection_id="pconn:opbox",
                status=status,
            )
        )
    kernel = Kernel(store)
    await kernel.register_adapter(
        T,
        build_control_plane_adapter(
            store, loader=kernel.loader, registry=kernel.registry
        ),
    )
    return kernel


async def _approved(kernel: Kernel, verb: str, params: dict) -> dict:
    context = _context(verb)
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, context)
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    return await kernel.invoke(
        "control", verb, params, context, approval_id=request_id
    )


async def _refused(kernel: Kernel, verb: str, params: dict) -> AdapterFailure:
    """An invalid policy is refused at the DOOR, before a human is asked.

    Validation runs in the approval-context hook, which the gate calls while
    minting. If it ran in the executor instead, every one of these would first
    create a HITL request and a reviewer would be asked to approve something the
    kernel already knows it will refuse. The absence of a request is asserted,
    not assumed.
    """
    before = len(await kernel.hitl.list_pending(T))
    with pytest.raises(AdapterFailure) as failure:
        await kernel.invoke("control", verb, params, _context(verb))
    assert failure.value.reason == ROUTING_POLICY_INVALID
    assert failure.value.status_code == 409
    assert len(await kernel.hitl.list_pending(T)) == before
    return failure.value


@pytest.mark.security
async def test_a_policy_can_be_authored_listed_and_deleted() -> None:
    kernel = await _kernel()
    created = await _approved(
        kernel,
        "control.routing_policy.upsert",
        {
            "id": "rp:open-read",
            "capability_id": "matter.open",
            "binding_id": "cb:open",
            "operation_class": "read",
            "precedence": 10,
        },
    )
    assert created["upserted"] == "routing_policy"
    assert created["precedence"] == 10 and created["scope"] == "tenant"

    stored = await kernel.store.list_routing_policies(T)
    assert [policy.id for policy in stored] == ["rp:open-read"]
    assert stored[0].applies(1, "read", None) is True
    assert stored[0].applies(1, "create", None) is False

    deleted = await _approved(
        kernel, "control.routing_policy.delete", {"id": "rp:open-read"}
    )
    assert deleted == {"deleted": "routing_policy", "id": "rp:open-read"}
    assert await kernel.store.list_routing_policies(T) == []


@pytest.mark.security
async def test_deleting_a_policy_that_never_existed_is_refused_at_the_door() -> None:
    kernel = await _kernel()
    with pytest.raises(AdapterFailure) as failure:
        await kernel.invoke(
            "control",
            "control.routing_policy.delete",
            {"id": "rp:never-was"},
            _context("control.routing_policy.delete"),
        )
    # 404, not a silent success and not a pending approval: "already gone" and
    # "never existed" are different answers to whoever is editing which
    # implementation a live verb reaches.
    assert failure.value.status_code == 404
    assert await kernel.hitl.list_pending(T) == []


@pytest.mark.security
async def test_a_route_to_an_unapproved_binding_is_refused_at_authoring_time() -> None:
    kernel = await _kernel()
    failure = await _refused(
        kernel,
        "control.routing_policy.upsert",
        {
            "id": "rp:close",
            "capability_id": "matter.close",
            "binding_id": "cb:close",
        },
    )
    assert "proposed" in str(failure)
    assert await kernel.store.list_routing_policies(T) == []

    # The counterweight: approve the binding and the identical call succeeds, so
    # the refusal is about the status and not about the shape of the request.
    await kernel.store.set_capability_binding_status(T, "cb:close", "approved", "rev")
    await _approved(
        kernel,
        "control.routing_policy.upsert",
        {"id": "rp:close", "capability_id": "matter.close", "binding_id": "cb:close"},
    )
    assert [p.id for p in await kernel.store.list_routing_policies(T)] == ["rp:close"]


@pytest.mark.security
async def test_a_policy_cannot_point_at_another_capabilitys_binding() -> None:
    kernel = await _kernel()
    await _refused(
        kernel,
        "control.routing_policy.upsert",
        {
            "id": "rp:crossed",
            "capability_id": "matter.open",
            # A real, approved binding - for a different capability. Nothing in
            # the schema forbids this and the router cannot recover from it at
            # call time: it would select an operation that does something else.
            "binding_id": "cb:close",
        },
    )
    await _refused(
        kernel,
        "control.routing_policy.upsert",
        {
            "id": "rp:ghost",
            "capability_id": "matter.open",
            "binding_id": "cb:does-not-exist",
        },
    )
    assert await kernel.store.list_routing_policies(T) == []


@pytest.mark.security
async def test_a_version_pin_must_match_the_binding_it_selects() -> None:
    kernel = await _kernel()
    await _refused(
        kernel,
        "control.routing_policy.upsert",
        {
            "id": "rp:v2",
            "capability_id": "matter.open",
            "binding_id": "cb:open",
            "capability_version": 2,
        },
    )
    # Version 1 is what cb:open implements, and an ABSENT pin means any version.
    for params in (
        {"id": "rp:v1", "capability_id": "matter.open", "binding_id": "cb:open",
         "capability_version": 1},
        {"id": "rp:any", "capability_id": "matter.open", "binding_id": "cb:open"},
    ):
        await _approved(kernel, "control.routing_policy.upsert", params)
    assert len(await kernel.store.list_routing_policies(T)) == 2


@pytest.mark.security
async def test_scope_and_workspace_id_must_agree() -> None:
    kernel = await _kernel()
    await _refused(
        kernel,
        "control.routing_policy.upsert",
        {
            "id": "rp:scopeless",
            "capability_id": "matter.open",
            "binding_id": "cb:open",
            "scope": "workspace",
        },
    )
    await _refused(
        kernel,
        "control.routing_policy.upsert",
        {
            "id": "rp:contradiction",
            "capability_id": "matter.open",
            "binding_id": "cb:open",
            "scope": "tenant",
            "workspace_id": "ws-a",
        },
    )
    scoped = await _approved(
        kernel,
        "control.routing_policy.upsert",
        {
            "id": "rp:ws",
            "capability_id": "matter.open",
            "binding_id": "cb:open",
            "scope": "workspace",
            "workspace_id": "ws-a",
        },
    )
    assert scoped["workspace_id"] == "ws-a"
    policy = (await kernel.store.list_routing_policies(T))[0]
    assert policy.applies(1, "create", "ws-a") is True
    assert policy.applies(1, "create", "ws-b") is False
    assert policy.applies(1, "create", None) is False


@pytest.mark.security
async def test_an_approval_cannot_publish_a_route_the_binding_stopped_deserving() -> None:
    """The reason validation lives in the approval-context hook, not the executor.

    The binding's status is part of the approval fingerprint, so rejecting the
    binding between the approval and its redemption makes the write refuse. If
    validation ran only at mint time this would publish a route to a disabled
    binding; if it ran only in the executor a reviewer would have been asked
    about a policy the kernel already knew to refuse.
    """
    kernel = await _kernel()
    params = {
        "id": "rp:races",
        "capability_id": "matter.open",
        "binding_id": "cb:open",
    }
    context = _context("control.routing_policy.upsert")
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", "control.routing_policy.upsert", params, context)
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")

    await kernel.store.set_capability_binding_status(T, "cb:open", "disabled", "rev")
    with pytest.raises(AdapterFailure) as refused:
        await kernel.invoke(
            "control",
            "control.routing_policy.upsert",
            params,
            context,
            approval_id=request_id,
        )
    # The re-validation fires first and says WHY, which is more use than the
    # generic "approved resource changed" the fingerprint comparison would give.
    assert refused.value.reason == ROUTING_POLICY_INVALID
    assert "disabled" in str(refused.value)
    assert await kernel.store.list_routing_policies(T) == []


@pytest.mark.security
async def test_a_binding_change_that_still_validates_still_breaks_the_approval() -> None:
    """The fingerprint half, which the re-validation above hides.

    Re-publishing the binding at version 2 leaves it approved and leaves the
    policy valid, so nothing refuses it on the merits. The approval was minted
    against version 1, and version is IN the fingerprint, so the redemption is
    refused anyway. Without this leg the test above is equally consistent with
    a fingerprint that binds nothing.
    """
    kernel = await _kernel()
    params = {
        "id": "rp:versioned",
        "capability_id": "matter.open",
        "binding_id": "cb:open",
    }
    context = _context("control.routing_policy.upsert")
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", "control.routing_policy.upsert", params, context)
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")

    await kernel.store.upsert_capability_binding(
        CapabilityBinding(
            binding_id="cb:open", tenant_id=T, capability_id="matter.open",
            source_operation_id="opbox.create_matter", connection_id="pconn:opbox",
            status="approved", capability_version=2,
        )
    )
    with pytest.raises(PendingHuman) as again:
        await kernel.invoke(
            "control",
            "control.routing_policy.upsert",
            params,
            context,
            approval_id=request_id,
        )
    # The GATE refuses first, one layer above the executor's re-check: the
    # resource context is part of approval_request_fingerprint, so the old
    # approval no longer names this request and a fresh one is minted. Stronger
    # than the executor refusing, because the write is never reached at all.
    assert again.value.hitl_request_id != request_id
    assert await kernel.store.list_routing_policies(T) == []


@pytest.mark.security
async def test_an_unchanged_binding_lets_the_same_approval_through() -> None:
    """The counterweight. Without it the refusal above is equally consistent
    with an approval that can never be redeemed at all."""
    kernel = await _kernel()
    params = {
        "id": "rp:steady",
        "capability_id": "matter.open",
        "binding_id": "cb:open",
    }
    context = _context("control.routing_policy.upsert")
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", "control.routing_policy.upsert", params, context)
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    result = await kernel.invoke(
        "control",
        "control.routing_policy.upsert",
        params,
        context,
        approval_id=request_id,
    )
    assert result["id"] == "rp:steady"
    assert [p.id for p in await kernel.store.list_routing_policies(T)] == ["rp:steady"]
