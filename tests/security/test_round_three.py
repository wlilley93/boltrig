"""Round Three security/governance invariants: SEC-29..33, FR-OBS-02, FR-EVAL-02.

Authoring is RBAC-gated + audited (SEC-32); test-spawns/eval/personal agents
cannot escalate (SEC-29/30); insight is scope-filtered (SEC-33/FR-OBS-02); memory
is scope-isolated (SEC-31).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet import build_spawner
from boltrig.fleet.eval import EvalRunner
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    ActionType,
    AgentCapability,
    AuditEvent,
    EvalCase,
    GrantSet,
    MemoryItem,
    ModelEndpoint,
    Noun,
    Skill,
    TenantPermissions,
    WorkItem,
    WorkStatus,
    Consequence,
    IdempotencyMode,
    RateLimit,
    TargetType,
    Verb,
    VerbBinding,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    await store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 2, True, "cheap")
    )
    await store.upsert_skill(
        Skill(id="risky", tenant_id=T, version="1.0.0", prompt_fragment="p",
              tool_grants=["ticket.create"], context_requirements={})
    )
    return k


def _client(k: Kernel) -> TestClient:
    return TestClient(create_app(k, platform={"spawner": build_spawner(k)}))


def _hdr(role, grants=None, departments=""):
    h = {"x-boltrig-tenant": T, "x-boltrig-subject": "u", "x-boltrig-role": role,
         "x-boltrig-departments": departments}
    if grants is not None:
        h["x-boltrig-grants"] = grants
    return h


# --- SEC-32: authoring is RBAC-gated + audited -------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-32")
def test_authoring_requires_role_and_is_audited():
    k = asyncio.run(_kernel())
    c = _client(k)
    # a viewer (not an author role) is denied
    denied = c.post("/v1/skills", json={"id": "s1"}, headers=_hdr("viewer"))
    assert denied.status_code == 403
    # An org-admin reaches the governed control path. A separate approver clears
    # the high-consequence write, then the same request is applied and audited.
    body = {"id": "s1", "tool_grants": []}
    held = c.post("/v1/skills", json=body, headers=_hdr("org-admin"))
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    asyncio.run(k.hitl.answer(T, request_id, "approve", "security-admin"))
    ok = c.post(
        "/v1/skills",
        json={**body, "approval_id": request_id},
        headers=_hdr("org-admin"),
    )
    assert ok.status_code == 200
    events = asyncio.run(k.store.audit_query(T))
    assert any(e.verb == "control.skill.upsert" and e.actor == "u" for e in events)


@pytest.mark.security
@pytest.mark.invariant("SEC-32")
def test_author_replacement_views_are_complete_and_role_gated():
    k = asyncio.run(_kernel())

    async def _seed():
        skill = await k.store.get_skill(T, "risky")
        assert skill is not None
        skill.description = "Risk review"
        skill.context_requirements = {"type": "object", "required": ["case"]}
        await k.store.upsert_skill(skill)
        await k.store.upsert_noun(
            Noun(id="case", tenant_id=T, description="Case", schema={"type": "object"})
        )
        await k.store.upsert_verb(
            Verb(
                id="case.review",
                tenant_id=T,
                noun_id="case",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                description="Review a case",
                consequence=Consequence.HIGH,
                degraded_mode={"status": "queued"},
                identity_mode="delegated",
                idempotency_mode=IdempotencyMode.DISABLED,
            )
        )
        await k.store.upsert_binding(
            VerbBinding(
                verb_id="case.review",
                tenant_id=T,
                target_type=TargetType.ADAPTER,
                target_ref="tickets",
                rate_limit=RateLimit(per="minute", max=3, scope="verb"),
            )
        )
        await k.store.upsert_model_endpoint(
            ModelEndpoint(
                id="internal",
                tenant_id=T,
                kind="local",
                model="pinned",
                base_url="http://model.internal",
                fallback="backup",
                data_class="sensitive",
            )
        )

    asyncio.run(_seed())
    c = _client(k)
    viewer = _hdr("viewer")
    author = _hdr("org-admin")

    assert c.get("/v1/skills/risky", headers=viewer).status_code == 403
    skill = c.get("/v1/skills/risky", headers=author).json()["skill"]
    assert skill["prompt_fragment"] == "p"
    assert skill["context_requirements"]["required"] == ["case"]
    assert skill["description"] == "Risk review"

    noun = c.get("/v1/nouns/case", headers=author).json()["noun"]
    assert noun == {
        "id": "case",
        "description": "Case",
        "schema": {"type": "object"},
        "is_active": True,
        "status": "active",
    }
    verb = c.get("/v1/verbs/case.review", headers=author).json()
    assert verb["verb"]["degraded_mode"] == {"status": "queued"}
    assert verb["verb"]["identity_mode"] == "delegated"
    assert verb["verb"]["idempotency_mode"] == "disabled"
    assert verb["binding"]["rate_limit"] == {"per": "minute", "max": 3, "scope": "verb"}

    public_endpoints = c.get("/v1/model-endpoints", headers=viewer).json()["endpoints"]
    assert public_endpoints == [{
        "id": "internal",
        "kind": "local",
        "model": "pinned",
        "data_class": "sensitive",
        "is_active": True,
        "status": "active",
    }]
    assert "base_url" not in public_endpoints[0]
    assert c.get("/v1/model-endpoints/internal", headers=viewer).status_code == 403
    endpoint = c.get("/v1/model-endpoints/internal", headers=author).json()["endpoint"]
    assert endpoint["base_url"] == "http://model.internal"
    assert endpoint["fallback"] == "backup"


# --- SEC-29: a test-spawn cannot escalate beyond the author's grants ---------
@pytest.mark.security
@pytest.mark.invariant("SEC-29")
def test_test_spawn_cannot_escalate():
    k = asyncio.run(_kernel())
    c = _client(k)
    # a scoped author (lead) with NO grant for ticket.create
    scoped = c.post("/v1/skills/risky/test-spawn", json={"task": "x"},
                    headers=_hdr("lead", grants=""))
    assert scoped.status_code == 200
    assert "ticket.create" not in scoped.json().get("effective_grants", [])
    # an org-admin (grants *) does get it - the contrast
    admin = c.post("/v1/skills/risky/test-spawn", json={"task": "x"},
                   headers=_hdr("org-admin", grants="*"))
    assert "ticket.create" in admin.json().get("effective_grants", [])


# --- FR-EVAL-02 + SEC-29: eval runs through the chokepoint, no escalation -----
@pytest.mark.invariant("FR-EVAL-02")
async def test_eval_runs_without_escalation():
    k = await _kernel()
    runner = EvalRunner(k, build_spawner(k))
    case = EvalCase(id="e1", tenant_id=T, target_kind="skill", target_ref="risky",
                    input={"task": "x"}, assertions={"forbidden_grants": ["ticket.create"]})
    # the initiator lacks ticket.create; the eval must NOT grant it to the child
    run = await runner.run_case(case, grants=GrantSet.of([]), actor="lead")
    assert run.passed is True
    assert "ticket.create" not in run.detail["effective_grants"]


# --- SEC-30: a personal agent acts only with the owner's delegated authority --
@pytest.mark.security
@pytest.mark.invariant("SEC-30")
def test_personal_agent_is_delegated_only():
    k = asyncio.run(_kernel())
    c = _client(k)
    # owner with no ticket.create grant configures + invokes a personal agent
    h = _hdr("employee", grants="")
    h["x-boltrig-subject"] = "alice"
    assert c.post("/v1/me/agent", json={"runtime": "script", "skills": ["risky"]},
                  headers=h).status_code == 200
    res = c.post("/v1/me/agent/invoke", json={"message": "do it"}, headers=h)
    assert res.status_code == 200
    assert res.json()["agent_type"] == "script-worker"
    assert "ticket.create" not in res.json().get("effective_grants", [])  # capped to owner
    # the run is audited on-behalf-of the owner
    events = asyncio.run(k.store.audit_query(T))
    assert any(e.on_behalf_of == "alice" for e in events)


@pytest.mark.security
@pytest.mark.invariant("SEC-30")
def test_personal_agent_get_and_delete_lifecycle():
    k = asyncio.run(_kernel())
    c = _client(k)
    h = _hdr("employee", grants="")
    h["x-boltrig-subject"] = "alice"

    assert c.get("/v1/me/agent", headers=h).json() == {"agent": None}
    assert c.post("/v1/me/agent", json={"runtime": "script", "skills": ["risky"]},
                  headers=h).status_code == 200
    got = c.get("/v1/me/agent", headers=h)
    assert got.status_code == 200
    assert got.json()["agent"]["runtime"] == "script"
    assert got.json()["agent"]["skills"] == ["risky"]
    # another subject never sees it
    other = _hdr("employee", grants="")
    other["x-boltrig-subject"] = "bob"
    assert c.get("/v1/me/agent", headers=other).json() == {"agent": None}

    assert c.delete("/v1/me/agent", headers=h).status_code == 200
    assert c.get("/v1/me/agent", headers=h).json() == {"agent": None}
    assert c.delete("/v1/me/agent", headers=h).status_code == 404
    # delete is audited
    events = asyncio.run(k.store.audit_query(T))
    assert any(e.verb == "authoring.personal_agent.delete" and e.actor == "alice" for e in events)


# --- SEC-31: memory is scope-isolated ----------------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-31")
def test_memory_scope_isolation():
    k = asyncio.run(_kernel())

    async def _seed():
        await k.store.add_memory_item(MemoryItem(id="m-a", tenant_id=T, owner_scope="user:alice",
                                                  kind="fact", content="alice secret"))
        await k.store.add_memory_item(MemoryItem(id="m-b", tenant_id=T, owner_scope="user:bob",
                                                  kind="fact", content="bob secret"))
        await k.store.add_memory_item(MemoryItem(id="m-o", tenant_id=T, owner_scope="org",
                                                  kind="fact", content="org wide"))
    asyncio.run(_seed())
    c = _client(k)
    h = _hdr("employee")
    h["x-boltrig-subject"] = "alice"
    items = c.post("/v1/memory/query", json={}, headers=h).json()["items"]
    contents = {i["content"] for i in items}
    assert "alice secret" in contents and "org wide" in contents
    assert "bob secret" not in contents  # cross-user memory is denied


# --- SEC-33 + FR-OBS-02: scope-filtered audit/runs ---------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-33")
@pytest.mark.invariant("FR-OBS-02")
def test_audit_and_runs_are_scope_filtered():
    k = asyncio.run(_kernel())

    async def _seed():
        for wid, dept, rid in [("w-eng", "engineering", "run-eng"), ("w-mkt", "marketing", "run-mkt")]:
            await k.store.create_work_item(WorkItem(id=wid, tenant_id=T, source="chat",
                intent=dept, confidence=1.0, convergent=False, status=WorkStatus.IN_FLIGHT,
                owner_member=dept, hatchet_run_id=rid))
            await k.audit.write(AuditEvent(tenant_id=T, ts=utcnow(), actor="agent",
                action_type=ActionType.TOOL_CALL, status="ok", run_id=rid, verb="ticket.read"))
    asyncio.run(_seed())
    c = _client(k)
    eng = c.get("/v1/audit/search", headers=_hdr("engineer", departments="engineering"))
    runs = {r["run_id"] for r in eng.json()["results"]}
    assert "run-eng" in runs and "run-mkt" not in runs  # other dept not visible
    admin = c.get("/v1/audit/search", headers=_hdr("org-admin"))
    admin_runs = {r["run_id"] for r in admin.json()["results"]}
    assert {"run-eng", "run-mkt"} <= admin_runs


@pytest.mark.security
@pytest.mark.invariant("SEC-139")
async def test_v1_spawn_caps_child_to_caller_grants():
    from boltrig.fleet.spawn import make_app_spawner
    from boltrig.kernel.app import Principal, SpawnBody

    k = await _kernel()
    app_spawner = make_app_spawner(k)
    # a caller with NO ticket.create grant spawns the risky skill directly
    scoped = Principal(tenant_id=T, subject="u", grants=GrantSet.of([]))
    res = await app_spawner(scoped, SpawnBody(task="x", skills=["risky"]))
    assert "ticket.create" not in res.get("effective_grants", [])  # capped to caller
    # contrast: an admin (grants *) does get it through the same seam
    admin = Principal(tenant_id=T, subject="u", grants=GrantSet.of(["*"]))
    res_a = await app_spawner(admin, SpawnBody(task="x", skills=["risky"]))
    assert "ticket.create" in res_a.get("effective_grants", [])
