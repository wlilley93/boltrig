"""Closed-debt checks for legacy writes migrated to governed control verbs."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.api.readiness_control import REQUIRED_CONTROL_VERBS
from boltrig.config.control_specs import control_specs
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AdapterFailure,
    GrantSet,
    InvocationContext,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "default"

_COMPAT_VERBS = frozenset(
    {
        "control.ai_key.set",
        "control.ai_key.delete",
        "control.org.update",
        "control.workspace.create",
        "control.workspace.update",
        "control.workspace.member.add",
        "control.workspace.member.remove",
        "control.channel.connect",
        "control.channel.configure",
        "control.channel.disconnect",
        "control.channel.pair",
        "control.channel.bind",
        "control.channel.unbind",
        "control.eval_case.archive",
        "control.eval_case.restore",
        "control.eval_case.upsert",
    }
)


def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store), store


def _headers(*, role: str = "org-admin", subject: str = "admin") -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": subject,
        "x-boltrig-role": role,
        "x-boltrig-grants": "*",
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-140")
def test_compatibility_verbs_are_registered_high_consequence_and_readiness_required():
    specs = {spec.verb_id: spec for spec in control_specs()}
    assert _COMPAT_VERBS <= specs.keys()
    assert _COMPAT_VERBS <= REQUIRED_CONTROL_VERBS
    assert {specs[verb].consequence for verb in _COMPAT_VERBS} == {"high"}
    assert specs["control.channel.pair"].idempotency_mode == "disabled"


@pytest.mark.security
@pytest.mark.invariant("SEC-140")
def test_workspace_compat_route_is_dispatch_audited_and_idempotent():
    kernel, store = _kernel()
    client = TestClient(create_app(kernel, platform={}))
    headers = {**_headers(), "idempotency-key": "workspace-create-once"}

    held = client.post("/v1/workspaces", headers=headers, json={"name": "Idempotent"})
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    asyncio.run(kernel.hitl.answer(T, request_id, "approve", "reviewer"))
    first = client.post(
        "/v1/workspaces",
        headers={**headers, "x-boltrig-approval-id": request_id},
        json={"name": "Idempotent"},
    )
    replay = client.post("/v1/workspaces", headers=headers, json={"name": "Idempotent"})

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    workspace_id = first.json()["workspace"]["id"]
    assert [row.id for row in asyncio.run(store.list_workspaces(T))] == [workspace_id]
    members = asyncio.run(store.list_workspace_members(T, workspace_id))
    assert [(row.user_id, row.role) for row in members] == [("admin", "owner")]
    events = asyncio.run(store.audit_query(T, limit=100))
    assert any(
        event.verb == "control.workspace.create" and event.status == "ok" for event in events
    )
    assert any(event.verb == "workspace.create" for event in events)


@pytest.mark.security
@pytest.mark.invariant("SEC-140")
async def test_direct_control_invocation_cannot_bypass_org_role_authorization():
    kernel, store = _kernel()
    from boltrig.config.control_plane import build_control_plane_adapter

    await kernel.register_adapter(
        T,
        build_control_plane_adapter(store, loader=kernel.loader, registry=kernel.registry),
    )
    context = InvocationContext(
        tenant_id=T,
        actor="ordinary-member",
        actor_tier="human",
        grants=GrantSet.of(["*"]),
        extra={"principal_role": "member"},
    )

    with pytest.raises(AdapterFailure) as exc:
        await kernel.invoke("control", "control.org.update", {"name": "Hijack"}, context)
    assert exc.value.status_code == 403
    assert await store.get_org(T) is None
    events = await store.audit_query(T, limit=20)
    assert any(
        event.verb == "control.org.update" and event.status == "control_unauthorised"
        for event in events
    )
