"""Caller-scoped discovery (US-KER-05): /v1/capabilities omits out-of-scope verbs.

Discovery returns only the verbs the caller is scoped to see (tenant ceiling
intersected with the caller's own grants), not the whole tenant ceiling. An
org-admin sees everything; a scoped caller sees only their verbs; dev discovery
(role-derived grants) is not empty.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import (
    AgentCapability,
    GrantSet,
    Noun,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel() -> Kernel:
    from boltrig.adapters.builtin.memory_tickets import build as build_tickets
    from boltrig.adapters.builtin.ms_graph import build as build_graph

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())  # ticket.* verbs
    await k.register_adapter(T, build_graph())  # document.* / email.* / ... verbs
    return k


def _client() -> TestClient:
    return TestClient(create_app(asyncio.run(_kernel())))


def _hdr(**kw):
    base = {"x-boltrig-tenant": T, "x-boltrig-subject": "u"}
    base.update(kw)
    return base


def _ids(resp):
    return {v["id"] for v in resp.json()["verbs"]}


@pytest.mark.security
@pytest.mark.invariant("US-KER-05")
def test_scoped_caller_sees_only_scoped_verbs():
    c = _client()
    admin = _ids(c.get("/v1/capabilities", headers=_hdr(**{"x-boltrig-role": "org-admin"})))
    assert "ticket.create" in admin and any(i.startswith("document.") for i in admin)

    scoped = _ids(
        c.get("/v1/capabilities", headers=_hdr(**{"x-boltrig-grants": "ticket.*"}))
    )
    assert "ticket.create" in scoped
    assert not any(i.startswith("document.") or i.startswith("email.") for i in scoped)


@pytest.mark.security
def test_dev_admin_discovery_not_empty():
    # role-derived grants (org-admin -> "*") keep dev discovery non-empty
    c = _client()
    verbs = _ids(c.get("/v1/capabilities", headers=_hdr(**{"x-boltrig-role": "org-admin"})))
    assert len(verbs) > 0


@pytest.mark.security
@pytest.mark.invariant("US-KER-05")
@pytest.mark.invariant("SEC-WRK-10")
def test_discovery_catalogue_is_grant_tenant_and_workspace_scoped():
    async def build():
        k = await _kernel()
        await k.store.upsert_noun(
            Noun(
                id="ticket",
                tenant_id=T,
                description="A support ticket",
                schema={"type": "object"},
            )
        )
        for wf_id, workspace_id, required in (
            ("org-workflow", None, ["task"]),
            ("own-workflow", "ws-1", ["ticket_id"]),
            ("other-workspace", "ws-2", ["secret"]),
        ):
            await k.store.upsert_workflow(
                WorkflowDefinition(
                    id=wf_id,
                    tenant_id=T,
                    version="1.0.0",
                    source=WorkflowSource.PRECREATED,
                    definition={
                        "input_schema": {
                            "type": "object",
                            "required": required,
                        }
                    },
                    workspace_id=workspace_id,
                )
            )
        await k.store.upsert_workflow(
            WorkflowDefinition(
                id="foreign-workflow",
                tenant_id="other",
                version="1.0.0",
                source=WorkflowSource.PRECREATED,
                definition={"input_schema": {"foreign": True}},
            )
        )
        await k.store.upsert_capability(
            AgentCapability(
                name="local-worker",
                tenant_id=T,
                runtime="pi",
                supported_skills=["analysis/*"],
                max_depth=2,
                is_ephemeral=True,
                cost_tier="cheap",
                model_endpoint="local-model",
            )
        )
        await k.store.upsert_capability(
            AgentCapability(
                name="foreign-worker",
                tenant_id="other",
                runtime="remote",
                supported_skills=["*"],
                max_depth=9,
                is_ephemeral=False,
                cost_tier="expensive",
                model_endpoint="foreign-model",
            )
        )
        return k

    async def resolver(_request):
        return Principal(
            tenant_id=T,
            subject="scoped-user",
            grants=GrantSet.of(["ticket.*"]),
            active_workspace_id="ws-1",
        )

    body = TestClient(
        create_app(asyncio.run(build()), principal_resolver=resolver, platform={})
    ).get("/v1/capabilities").json()

    assert set(body) == {"nouns", "verbs", "workflows", "agent_capabilities"}
    assert {noun["id"] for noun in body["nouns"]} == {"ticket"}
    assert body["nouns"] == [
        {
            "id": "ticket",
            "description": "A support ticket",
            "schema": {"type": "object"},
        }
    ]

    assert body["verbs"]
    assert all(verb["noun"] == "ticket" for verb in body["verbs"])
    assert set(body["verbs"][0]) == {
        "id",
        "noun",
        "input_schema",
        "output_schema",
        "consequence",
        "idempotency_mode",
        "binding",
        "health",
    }
    create = next(verb for verb in body["verbs"] if verb["id"] == "ticket.create")
    assert create["input_schema"]["required"] == ["title"]
    assert create["output_schema"]["required"] == ["id"]
    assert create["consequence"] == "low"
    assert create["idempotency_mode"] == "cacheable"
    assert create["binding"] == {
        "target_type": "adapter",
        "target_ref": "memory-tickets",
    }

    assert {workflow["id"] for workflow in body["workflows"]} == {
        "org-workflow",
        "own-workflow",
    }
    own = next(w for w in body["workflows"] if w["id"] == "own-workflow")
    assert own == {
        "id": "own-workflow",
        "version": "1.0.0",
        "source": "precreated",
        "workspace_id": "ws-1",
        "input_schema": {"type": "object", "required": ["ticket_id"]},
    }

    assert body["agent_capabilities"] == [
        {
            "name": "local-worker",
            "runtime": "pi",
            "supported_skills": ["analysis/*"],
            "max_depth": 2,
            "is_ephemeral": True,
                "cost_tier": "cheap",
                "model_endpoint": "local-model",
                "vision_model_endpoint": None,
                "model_routes": {"text": "local-model"},
                "familiar_genotype": {
                "source": "agent_capability.name.v1",
                "seed": 104173362,
                "body": "pioneer",
                "palette": ["#fce7f3", "#ec4899", "#831843"],
                "markings": ["orbit"],
                "accessories": ["signal-pin"],
                "voice_id": None,
            },
        }
    ]
