"""Authenticated role/scope cannot be replaced by caller context metadata."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.hatchet_app import context_from_envelope, context_to_envelope
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, SpawnBody, create_app
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"
MALICIOUS = {
    "principal_role": "superadmin",
    "principal_scope": {"all": True},
    "epic_id": "ENG-441",
}


class CaptureSpawner:
    def __init__(self) -> None:
        self.context = None

    async def spawn(self, tenant_id, task, skills, prefer, context, **kwargs):
        self.context = context
        return {"run_id": "captured", "status": "ok"}


def _principal() -> Principal:
    return Principal(
        tenant_id=T,
        subject="alice",
        grants=GrantSet.of(["ticket.read"]),
        role="manager",
        actor_tier="human",
        scope={"departments": ["engineering"], "verbs": ["ticket.read"]},
    )


async def _kernel():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    adapter = build_tickets()
    await kernel.register_adapter(T, adapter)
    return kernel, adapter


def _assert_trusted(context) -> None:
    assert context.extra["principal_role"] == "manager"
    assert context.extra["principal_scope"] == {
        "departments": ["engineering"],
        "verbs": ["ticket.read"],
    }
    assert context.extra["epic_id"] == "ENG-441"


@pytest.mark.security
@pytest.mark.invariant("SEC-07")
def test_principal_context_reserved_authority_is_resolver_owned():
    context = _principal().context(extra=MALICIOUS)
    _assert_trusted(context)
    # The caller's object is not mutated as a side effect of stamping authority.
    assert MALICIOUS["principal_role"] == "superadmin"


@pytest.mark.security
@pytest.mark.invariant("SEC-07")
def test_platform_invoke_cannot_spoof_principal_authority():
    kernel, adapter = asyncio.run(_kernel())
    seen = {}
    original = adapter.execute

    async def capture(verb, params, credential, context):
        seen["context"] = context
        return await original(verb, params, credential, context)

    adapter.execute = capture
    client = TestClient(create_app(kernel, platform={}))
    response = client.post(
        "/v1/invoke",
        json={
            "noun": "ticket",
            "verb": "ticket.read",
            "params": {"id": "missing"},
            "context": MALICIOUS,
        },
        headers={
            "x-boltrig-tenant": T,
            "x-boltrig-subject": "alice",
            "x-boltrig-role": "manager",
            "x-boltrig-tier": "human",
            "x-boltrig-grants": "ticket.read",
            "x-boltrig-verbs": "ticket.read",
            "x-boltrig-departments": "engineering",
        },
    )
    assert response.status_code == 404  # adapter's ordinary not-found mapping
    assert seen["context"].extra["principal_role"] == "manager"
    assert seen["context"].extra["principal_scope"] != {"all": True}


@pytest.mark.security
@pytest.mark.invariant("SEC-07")
def test_skill_and_personal_routes_cannot_spoof_principal_authority():
    kernel, _ = asyncio.run(_kernel())
    capture = CaptureSpawner()
    client = TestClient(create_app(kernel, platform={"spawner": capture}))
    headers = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "alice",
        "x-boltrig-role": "manager",
        "x-boltrig-tier": "human",
        "x-boltrig-grants": "ticket.read",
        "x-boltrig-verbs": "ticket.read",
        "x-boltrig-departments": "engineering",
    }

    skill = client.post(
        "/v1/skills/risky/test-spawn",
        json={"task": "x", "context": MALICIOUS},
        headers=headers,
    )
    assert skill.status_code == 200
    _assert_trusted(capture.context)

    configured = client.post(
        "/v1/me/agent", json={"runtime": "script", "skills": []}, headers=headers
    )
    assert configured.status_code == 200
    personal = client.post(
        "/v1/me/agent/invoke",
        json={"message": "x", "context": MALICIOUS},
        headers=headers,
    )
    assert personal.status_code == 200
    _assert_trusted(capture.context)
    assert capture.context.on_behalf_of == "alice"


@pytest.mark.security
@pytest.mark.invariant("SEC-07")
async def test_spawn_runtime_and_mcp_preserve_trusted_principal_metadata(monkeypatch):
    import boltrig.fleet.spawn as spawn_module

    kernel, _ = await _kernel()
    capture = CaptureSpawner()
    monkeypatch.setattr(
        spawn_module,
        "build_spawner",
        lambda _kernel, *, codex_config=None, model_catalogue=None, sensitive_endpoint_id=None: (
            capture
        ),
    )
    app_spawner = spawn_module.make_app_spawner(kernel)
    await app_spawner(
        _principal(),
        SpawnBody(task="x", context=dict(MALICIOUS)),
    )
    _assert_trusted(capture.context)

    # Durable runtime serialisation and MCP token propagation retain the same
    # resolver-owned values rather than re-reading caller payload metadata.
    restored = context_from_envelope(context_to_envelope(capture.context))
    _assert_trusted(restored)
    token = kernel.mcp.issue_run_token(
        T,
        restored.grants,
        run_id="run-1",
        actor="worker",
        extra=restored.extra,
    )
    run_token = kernel.mcp._lookup(token)
    assert run_token is not None
    run_context = kernel.mcp._context(run_token)
    _assert_trusted(run_context)
