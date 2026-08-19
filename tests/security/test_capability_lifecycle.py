"""Recoverable, governed agent-capability lifecycle contracts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.fleet.spawn import make_agent_invoker
from boltrig.fleet.spawn_skills import NoCapableRuntime, select_capability
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AgentCapability,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "capability-lifecycle"


def _capability(name: str, *, runtime: str = "python-script") -> AgentCapability:
    return AgentCapability(
        name=name,
        tenant_id=T,
        runtime=runtime,
        supported_skills=["records/*"],
        max_depth=2,
        is_ephemeral=True,
        cost_tier="cheap",
        source="control-plane",
    )


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
    await kernel.register_adapter(
        T,
        build_control_plane_adapter(
            store, loader=kernel.loader, registry=kernel.registry
        ),
    )
    return kernel


async def _approved(kernel: Kernel, verb: str, params: dict) -> dict:
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context(verb))
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    return await kernel.invoke(
        "control", verb, params, _context(verb), approval_id=request_id
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-12")
async def test_author_inventory_retains_inactive_profiles_but_discovery_does_not() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_capability(_capability("active"))
    await kernel.store.upsert_capability(_capability("retired"))
    await kernel.store.set_capability_active(T, "retired", False)
    client = TestClient(create_app(kernel))
    author = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }

    inventory = client.get("/v1/agent-capabilities", headers=author)
    assert inventory.status_code == 200
    rows = inventory.json()["agent_capabilities"]
    assert [(row["name"], row["status"]) for row in rows] == [
        ("active", "active"),
        ("retired", "retired"),
    ]
    assert all(row["source"] == "control-plane" for row in rows)
    discovery = client.get("/v1/capabilities", headers=author).json()
    assert [row["name"] for row in discovery["agent_capabilities"]] == ["active"]

    pending = client.post("/v1/agent-capabilities/active/retire", headers=author)
    assert pending.status_code == 202
    assert pending.json()["status"] == "pending_human"
    assert (await kernel.store.list_capabilities(T))[0].name == "active"
    approval_id = pending.json()["hitl_request_id"]
    await kernel.hitl.answer(T, approval_id, "approve", "independent-reviewer")
    completed = client.post(
        "/v1/agent-capabilities/active/retire",
        headers={**author, "x-boltrig-approval-id": approval_id},
    )
    assert completed.status_code == 200
    assert completed.json() == {
        "status": "ok",
        "id": "active",
        "capability_status": "retired",
        # The scope the mutation landed on (0083). Reported so an author can see
        # they edited the org-wide profile rather than shadowing it per workspace.
        "workspace_id": None,
        "scope": "organisation",
    }
    viewer = {**author, "x-boltrig-role": "member"}
    assert client.get("/v1/agent-capabilities", headers=viewer).status_code == 403


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-12")
async def test_retire_blocks_every_capability_route_and_only_restore_reactivates() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_capability(_capability("archivist"))
    retired = await _approved(
        kernel, "control.capability.retire", {"name": "archivist"}
    )
    assert retired == {
        "id": "archivist",
        "capability_status": "retired",
        "workspace_id": None,
        "scope": "organisation",
    }
    assert await kernel.store.list_capabilities(T) == []
    assert (await kernel.store.list_all_capabilities(T))[0].is_active is False
    with pytest.raises(NoCapableRuntime):
        await select_capability(kernel.store, T, ["records/read"], {})

    invoked = await make_agent_invoker(kernel)(
        "records.read", {}, _context("records.read"), "archivist"
    )
    assert invoked.ok is False
    assert invoked.error is not None and invoked.error.message.endswith("is retired")

    edited = await _approved(
        kernel,
        "control.capability.upsert",
        {"name": "archivist", "runtime": "python-script", "cost_tier": "standard"},
    )
    assert edited["capability_status"] == "retired"
    assert await kernel.store.list_capabilities(T) == []

    restored = await _approved(
        kernel, "control.capability.restore", {"name": "archivist"}
    )
    assert restored == {
        "id": "archivist",
        "capability_status": "active",
        "workspace_id": None,
        "scope": "organisation",
    }
    assert (await select_capability(
        kernel.store, T, ["records/read"], {"capability": "archivist"}
    )).name == "archivist"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-12")
async def test_capability_approval_is_bound_to_the_exact_mutable_profile() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_capability(_capability("mutable"))
    params = {"name": "mutable"}
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "control", "control.capability.retire", params, _context("retire")
        )
    await kernel.store.upsert_capability(_capability("mutable", runtime="codex"))
    await kernel.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer")

    with pytest.raises(PendingHuman) as rebound:
        await kernel.invoke(
            "control",
            "control.capability.retire",
            params,
            _context("retire"),
            approval_id=held.value.hitl_request_id,
        )
    assert rebound.value.hitl_request_id != held.value.hitl_request_id
    current = (await kernel.store.list_all_capabilities(T))[0]
    assert current.runtime == "codex" and current.is_active is True
