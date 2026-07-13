"""Beat 3.5 control-plane verb parity - security invariants (SEC-75/76/77).

SEC-75  every console authoring operation (skill / noun / verb / binding /
        MCP-server registration / config section) is dispatchable as a governed
        control.* verb through the one chokepoint, held by the HITL gate at high
        consequence, audited, and writes the SAME store state as the direct
        author-gated route (one shared write helper per noun - the paths cannot
        drift).
SEC-76  the control.* authoring verbs are denied to a caller whose grants lack
        them, and the MCP-registration verb leaves the consumer INERT (SEC-22
        review activates it; there is no activation verb) and accepts no secret.
SEC-77  the chat/agent lane preserves grant context end to end: a chat-style
        spawn carrying the shipped authoring skill hands control.* to the child
        (intersected with the caller ceiling), and the run-scoped MCP token the
        Pi runtime issues reaches the control verbs through the chokepoint; a
        non-author ceiling strips them.
SEC-78  bare chat-turn authority is manifest data under a caller ceiling
        ([2026] VJS-COUNTY 1): the turn executor selects the spawn's skill set
        from the chat.skills_by_role knob (default_skills when unmapped,
        shipped []), passes a grant ceiling equal to the caller's role-resolved
        grants on EVERY chat spawn (empty when unresolved), skips a manifest
        entry naming a missing skill without escalation, and trims a manifest
        skill's grants to the caller intersection - the knob can only reduce.

Authority note (recorded per the beat): like the Round Seven control.* verbs,
the new verbs rely on the grant lattice, not a role check - a caller reaches
control.* only when its grant profile permits it (org-admin's ``{all: true}``
scope maps to the tenant-wide ``*`` grant; any other role mapping must name the
``control`` noun/verbs in its scope). The direct routes keep their can_author
role gate unchanged.
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.config.admin import AdminConfig
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.config.manifest import ChatConfig, load_manifest
from boltrig.fleet import build_spawner
from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.events import EventRelay
from boltrig.models import (
    AdapterFailure,
    AdapterRecord,
    AgentCapability,
    GrantMissing,
    GrantSet,
    IdempotencyConflict,
    InvocationContext,
    PendingHuman,
    Noun,
    SchemaValidationError,
    Skill,
    TenantPermissions,
    TargetType,
    User,
    Verb,
    VerbBinding,
)
from boltrig.skills.loader import load_skills_dir
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary

T = "acme"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUTHORING_SKILLS_DIR = _REPO_ROOT / "libraries" / "skills" / "authoring"
_EXAMPLE_MANIFEST = _REPO_ROOT / "manifest.example.yaml"

_OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Control test", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/things": {
            "get": {
                "operationId": "thing.list",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}

# Every control verb with schema-valid params (used by the grant-denial loop).
_VERB_PARAMS: dict[str, dict] = {
    "control.workflow.upsert": {"id": "wf-control", "definition": {"steps": []}},
    "control.workflow.schedule": {
        "workflow_id": "wf-control",
        "cron": "0 9 * * 1-5",
        "timezone": "UTC",
    },
    "control.workflow.trigger": {"workflow_id": "wf-control", "inputs": {}},
    "control.workflow.execute": {"workflow_id": "wf-control", "inputs": {}},
    "control.capability.upsert": {"name": "worker", "runtime": "script"},
    "control.model_endpoint.upsert": {
        "id": "local",
        "kind": "local",
        "model": "test",
    },
    "control.skill.upsert": {
        "id": "authoring/new-skill",
        "prompt_fragment": "do x",
        "tool_grants": ["ticket.read"],
    },
    "control.noun.define": {"id": "invoice", "description": "an invoice"},
    "control.verb.define": {"id": "invoice.read", "noun_id": "invoice"},
    "control.binding.set": {
        "verb_id": "invoice.read",
        "target_type": "adapter",
        "target_ref": "memory-tickets",
    },
    "control.adapter.generate": {"adapter_id": "generated", "spec": _OPENAPI_SPEC},
    "control.adapter.activate": {"adapter_id": "generated"},
    "control.mcp_server.register": {"id": "ext-mcp", "url": "https://mcp.example.com"},
    "control.config.upsert": {"section": "hierarchy", "value": {"tiers": ["cos"]}},
    "control.config.rollback": {"section": "hierarchy", "revision_id": 1},
    "control.user.update": {"user_id": "target", "role": "member"},
    "control.user.deactivate": {"user_id": "target"},
    "control.invitation.create": {"email": "new@example.com", "role": "member"},
    "control.notification.route": {"event_type": "approval", "channel": "email"},
}

_HIGH_VERBS = {
    verb: params
    for verb, params in _VERB_PARAMS.items()
    if verb
    not in {
        "control.workflow.execute",
        "control.adapter.generate",
        "control.mcp_server.register",
        "control.invitation.create",
        "control.notification.route",
    }
}


async def _kernel(*, admin: AdminConfig | None = None) -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    control = build_control_plane_adapter(store, loader=k.loader, registry=k.registry, admin=admin)
    control.set_workflows(WorkflowLibrary(store, kernel=k))
    await k.register_adapter(
        T,
        control,
    )
    return k


def _ctx(grants: list[str], *, actor: str = "u", run_id: str = "run-35") -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(grants),
        actor=actor,
        actor_tier="human",
        run_id=run_id,
        extra={"principal_role": "superadmin"},
    )


async def _approved(k: Kernel, verb: str, params: dict, *, actor: str = "u") -> dict:
    """Dispatch a high-consequence control verb through the full gate: first call
    is HELD (PendingHuman), then an approval releases the SAME call (SEC-14)."""
    with pytest.raises(PendingHuman) as exc:
        await k.invoke("control", verb, params, _ctx(["*"], actor=actor))
    req_id = exc.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    return await k.invoke("control", verb, params, _ctx(["*"], actor=actor), approval_id=req_id)


def _hdr(role="org-admin"):
    return {"x-boltrig-tenant": T, "x-boltrig-subject": "u", "x-boltrig-role": role}


async def _approved_route(client, kernel, method: str, path: str, body: dict):
    held = client.request(method, path, json=body, headers=_hdr())
    assert held.status_code == 202 and held.json()["status"] == "pending_human"
    request_id = held.json()["hitl_request_id"]
    await kernel.hitl.answer(T, request_id, "approve", "route-reviewer@acme")
    return client.request(
        method,
        path,
        json={**body, "approval_id": request_id},
        headers=_hdr(),
    )


# --------------------------------------------------------------------------- #
# SEC-75  verb and route write the same state through one shared write path
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-75")
async def test_control_verbs_write_the_same_state_as_the_direct_routes():
    admin_v = AdminConfig(InMemoryStore(), tenant_id=T, doc={})
    kv = await _kernel(admin=admin_v)  # written via governed verbs
    kr = await _kernel()  # written via the direct author-gated routes
    admin_r = AdminConfig(InMemoryStore(), tenant_id=T, doc={})
    client = TestClient(create_app(kr, platform={"admin": admin_r}))

    # skill
    body = {
        "id": "authoring/new-skill",
        "version": "2.0.0",
        "prompt_fragment": "do x",
        "tool_grants": ["ticket.read"],
        "locale": "en",
    }
    out = await _approved(kv, "control.skill.upsert", body)
    assert out == {"upserted": "skill", "id": body["id"], "version": "2.0.0"}
    assert (await _approved_route(client, kr, "POST", "/v1/skills", body)).status_code == 200
    assert await kv.store.get_skill(T, body["id"]) == await kr.store.get_skill(T, body["id"])

    # noun
    body = {"id": "invoice", "description": "an invoice", "schema": {"type": "object"}}
    await _approved(kv, "control.noun.define", body)
    assert (await _approved_route(client, kr, "POST", "/v1/nouns", body)).status_code == 200
    assert await kv.store.get_noun(T, "invoice") == await kr.store.get_noun(T, "invoice")

    # verb - including the safe-by-default consequence rule (SEC-39): "approve"
    # is a destructive token, so with no explicit consequence it stores as high.
    body = {"id": "invoice.approve", "noun_id": "invoice", "description": "approve one"}
    out = await _approved(kv, "control.verb.define", body)
    assert out["consequence"] == "high"
    route_verb = await _approved_route(client, kr, "POST", "/v1/verbs", body)
    assert route_verb.json()["consequence"] == "high"
    assert await kv.store.get_verb(T, "invoice.approve") == await kr.store.get_verb(
        T, "invoice.approve"
    )

    # binding
    body = {"verb_id": "invoice.approve", "target_type": "adapter", "target_ref": "billing"}
    await _approved(kv, "control.binding.set", body)
    r = await _approved_route(
        client,
        kr,
        "POST",
        "/v1/verbs/invoice.approve/binding",
        {"target_type": "adapter", "target_ref": "billing"},
    )
    assert r.status_code == 200
    assert await kv.store.get_binding(T, "invoice.approve") == await kr.store.get_binding(
        T, "invoice.approve"
    )

    # MCP server registration - both paths park the consumer INERT (SEC-22)
    body = {"id": "ext-mcp", "url": "https://mcp.example.com"}
    out = await kv.invoke("control", "control.mcp_server.register", body, _ctx(["*"]))
    assert out["activated"] is False
    assert client.post("/v1/mcp/servers", json=body, headers=_hdr()).status_code == 200
    for k_ in (kv, kr):
        consumer = await k_.loader.get(T, "ext-mcp")
        assert consumer is not None and consumer.activated is False

    # config section - same revision recording as the PUT route, one AdminConfig
    body = {"section": "hierarchy", "value": {"tiers": ["cos", "head"]}}
    out = await _approved(kv, "control.config.upsert", body)
    r = await _approved_route(
        client,
        kr,
        "PUT",
        "/v1/admin/config/hierarchy",
        {"value": body["value"]},
    )
    assert r.status_code == 200
    assert admin_v.section("hierarchy") == admin_r.section("hierarchy") == body["value"]
    revs_v = await admin_v.history("hierarchy")
    revs_r = await admin_r.history("hierarchy")
    assert [rv.payload for rv in revs_v] == [rr.payload for rr in revs_r]
    assert revs_v[0].id == out["revision"] and revs_v[0].actor == "u"

    # every verb dispatch was audited as a kernel verb (governed, SEC-16)
    events = await kv.store.audit_query(T, limit=200)
    for verb in {
        "control.skill.upsert",
        "control.noun.define",
        "control.verb.define",
        "control.binding.set",
        "control.mcp_server.register",
        "control.config.upsert",
    }:
        assert any(e.verb == verb and e.status == "ok" for e in events)


@pytest.mark.security
@pytest.mark.invariant("SEC-75")
async def test_every_high_control_verb_is_hitl_held_and_writes_nothing_while_pending():
    admin = AdminConfig(InMemoryStore(), tenant_id=T, doc={})
    k = await _kernel(admin=admin)
    for verb, params in _HIGH_VERBS.items():
        with pytest.raises(PendingHuman):
            await k.invoke("control", verb, params, _ctx(["*"]))
    # held means held: none of the writes happened (fail-closed while pending)
    assert await k.store.get_skill(T, "authoring/new-skill") is None
    assert await k.store.get_noun(T, "invoice") is None
    assert await k.store.get_verb(T, "invoice.read") is None
    assert await k.store.get_binding(T, "invoice.read") is None
    assert admin.section("hierarchy") is None


@pytest.mark.security
@pytest.mark.invariant("SEC-75")
async def test_expanded_control_plane_operations_are_functional_and_secret_safe():
    k = await _kernel()
    admin = AdminConfig(k.store, tenant_id=T, doc={})
    control = k.loader.peek(T, "control")
    control.set_admin(admin)

    # Inert generation is governed but does not need a second human. Activation
    # does, and the generated review record names the real HITL respondent.
    generated = await k.invoke(
        "control",
        "control.adapter.generate",
        {"adapter_id": "generated", "spec": _OPENAPI_SPEC},
        _ctx(["*"]),
    )
    assert generated["activated"] is False
    activated = await _approved(k, "control.adapter.activate", {"adapter_id": "generated"})
    assert activated["activated"] is True
    adapter = await k.loader.get(T, "generated")
    assert adapter.review_gate.reviewer == "admin@acme"
    assert await k.store.get_binding(T, "thing.list") is not None

    await _approved(
        k,
        "control.workflow.upsert",
        {"id": "wf-control", "definition": {"steps": []}},
    )
    scheduled = await _approved(
        k,
        "control.workflow.schedule",
        {"workflow_id": "wf-control", "cron": "0 9 * * 1-5", "timezone": "UTC"},
    )
    assert scheduled["schedule"]["cron"] == "0 9 * * 1-5"
    workflow = next(w for w in await k.store.list_workflows(T) if w.id == "wf-control")
    assert workflow.definition["schedule"] == scheduled["schedule"]
    triggered = await _approved(
        k, "control.workflow.trigger", {"workflow_id": "wf-control", "inputs": {}}
    )
    assert triggered["status"] == "queued" and triggered["run_id"]
    executed = await k.invoke(
        "control",
        "control.workflow.execute",
        {"workflow_id": "wf-control", "inputs": {}},
        _ctx(["*"]),
    )
    assert executed["status"] == "completed"

    first = await admin.update_section("privacy", {"retention_days": 30}, "seed")
    await admin.update_section("privacy", {"retention_days": 90}, "seed")
    rolled_back = await _approved(
        k,
        "control.config.rollback",
        {"section": "privacy", "revision_id": first.id},
    )
    assert rolled_back["value"] == {"retention_days": 30}

    await k.store.upsert_user(
        User(id="target", tenant_id=T, email="target@example.com", role="member")
    )
    updated = await _approved(
        k,
        "control.user.update",
        {"user_id": "target", "role": "admin", "scope": {"verbs": ["ticket.*"]}},
    )
    assert updated["user"]["role"] == "admin"
    deactivated = await _approved(k, "control.user.deactivate", {"user_id": "target"})
    assert deactivated["user"]["status"] == "deactivated"

    invitation = await k.invoke(
        "control",
        "control.invitation.create",
        {"email": "new@example.com", "role": "member"},
        _ctx(["*"]),
    )
    assert invitation["invite_token"].startswith("boltrig_invite_")
    events = k.events.snapshot("run-35")
    assert invitation["invite_token"] not in repr(events)
    assert any(
        event.get("output", {}).get("invite_token") == "[redacted]"
        for event in events
        if event.get("type") == "tool_result"
    )

    routed = await k.invoke(
        "control",
        "control.notification.route",
        {"event_type": "approval", "channel": "email", "target": "new@example.com"},
        _ctx(["*"]),
    )
    assert any(pref.id == routed["id"] for pref in await k.store.list_notification_prefs(T))


# --------------------------------------------------------------------------- #
# SEC-76  denied without the grant; MCP registration inert + secret-free
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-76")
async def test_control_verbs_denied_to_a_caller_without_the_grant():
    k = await _kernel(admin=AdminConfig(InMemoryStore(), tenant_id=T, doc={}))
    # a member-profile grant set (ticket authority only) reaches NO control verb
    for verb, params in _VERB_PARAMS.items():
        with pytest.raises(GrantMissing):
            await k.invoke("control", verb, params, _ctx(["ticket.*"]))
    # and discovery hides them: the MCP tool list for that grant profile is
    # control-free, so a non-author never even sees the authoring verbs (SEC-23)
    token = k.mcp.issue_run_token(T, GrantSet.of(["ticket.*"]), run_id="r", actor="eph")
    resp = await k.mcp.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert not any(n.startswith("control.") for n in names)


@pytest.mark.security
@pytest.mark.invariant("SEC-76")
async def test_mcp_register_verb_is_inert_and_refuses_a_secret():
    k = await _kernel()
    # a token in verb params would surface on the run event stream, so the verb's
    # schema refuses it outright (SEC-27): secrets never transit verb-space
    with pytest.raises(SchemaValidationError):
        await k.invoke(
            "control",
            "control.mcp_server.register",
            {"id": "ext-mcp", "url": "https://mcp.example.com", "token": "s3cret"},
            _ctx(["*"]),
        )
    out = await k.invoke(
        "control",
        "control.mcp_server.register",
        {"id": "ext-mcp", "url": "https://mcp.example.com"},
        _ctx(["*"]),
    )
    assert out == {"registered": "mcp_server", "id": "ext-mcp", "activated": False}
    consumer = await k.loader.get(T, "ext-mcp")
    assert consumer.activated is False  # inert until the SEC-22 review route
    activation = await k.store.get_verb(T, "control.adapter.activate")
    assert activation is not None and activation.consequence.value == "high"


@pytest.mark.security
@pytest.mark.invariant("SEC-76")
async def test_low_consequence_adapter_creation_rejects_every_occupied_namespace():
    k = await _kernel()
    original_control = k.loader.peek(T, "control")

    attempts = [
        ("control.adapter.generate", {"adapter_id": "control", "spec": _OPENAPI_SPEC}),
        (
            "control.adapter.generate",
            {"adapter_id": "memory-tickets", "spec": _OPENAPI_SPEC},
        ),
    ]
    await k.store.upsert_adapter(
        AdapterRecord("stored-only", T, "1.0.0", "script", "manual", "test")
    )
    attempts.append(
        (
            "control.mcp_server.register",
            {"id": "stored-only", "url": "https://mcp.example.com"},
        )
    )
    await k.store.upsert_noun(Noun("orphan", T))
    await k.store.upsert_verb(Verb("orphan.call", T, "orphan", {}, {}))
    await k.store.upsert_binding(VerbBinding("orphan.call", T, TargetType.ADAPTER, "binding-only"))
    attempts.append(
        (
            "control.mcp_server.register",
            {"id": "binding-only", "url": "https://mcp.example.com"},
        )
    )

    for verb, params in attempts:
        with pytest.raises(AdapterFailure) as exc:
            await k.invoke("control", verb, params, _ctx(["*"]))
        assert exc.value.reason == "adapter_conflict"
    assert k.loader.peek(T, "control") is original_control
    assert k.loader.peek(T, "stored-only") is None
    assert k.loader.peek(T, "binding-only") is None


def _operation_spec(operation_id: str) -> dict:
    spec = copy.deepcopy(_OPENAPI_SPEC)
    spec["paths"]["/things"]["get"]["operationId"] = operation_id
    return spec


@pytest.mark.security
@pytest.mark.invariant("SEC-76")
@pytest.mark.parametrize("operation_id", ["control.user.deactivate", "ticket.read"])
async def test_activation_rejects_reserved_or_owned_verbs_before_publication(
    operation_id: str,
):
    k = await _kernel()
    adapter_id = f"collision-{operation_id.replace('.', '-')}"
    await k.invoke(
        "control",
        "control.adapter.generate",
        {"adapter_id": adapter_id, "spec": _operation_spec(operation_id)},
        _ctx(["*"]),
    )
    original = await k.store.get_binding(T, operation_id)

    with pytest.raises(PendingHuman) as held:
        await k.invoke(
            "control", "control.adapter.activate", {"adapter_id": adapter_id}, _ctx(["*"])
        )
    await k.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer@acme")
    with pytest.raises(AdapterFailure) as exc:
        await k.invoke(
            "control",
            "control.adapter.activate",
            {"adapter_id": adapter_id},
            _ctx(["*"]),
            approval_id=held.value.hitl_request_id,
        )
    assert exc.value.reason == "adapter_conflict"
    assert await k.store.get_binding(T, operation_id) == original
    adapter = await k.loader.get(T, adapter_id)
    assert adapter.activated is False
    assert (await k.store.get_adapter(T, adapter_id)).activated is False


@pytest.mark.security
@pytest.mark.invariant("SEC-76")
async def test_invitation_is_uncacheable_and_concurrent_creation_is_single_winner():
    k = await _kernel()
    params = {"email": "once@example.com", "role": "member"}
    with pytest.raises(IdempotencyConflict):
        await k.invoke(
            "control",
            "control.invitation.create",
            params,
            _ctx(["*"]),
            idempotency_key="must-not-cache-secret",
        )
    assert await k.store.list_invitations(T) == []

    results = await asyncio.gather(
        *(k.invoke("control", "control.invitation.create", params, _ctx(["*"])) for _ in range(2)),
        return_exceptions=True,
    )
    successes = [item for item in results if isinstance(item, dict)]
    conflicts = [item for item in results if isinstance(item, AdapterFailure)]
    assert len(successes) == len(conflicts) == 1
    assert conflicts[0].reason == "adapter_conflict"
    assert len(await k.store.list_invitations(T)) == 1


# --------------------------------------------------------------------------- #
# SEC-77  the chat/agent lane reaches control.* through the chokepoint
# --------------------------------------------------------------------------- #
async def _chat_lane_spawn(k: Kernel, skills: list[str], ceiling: GrantSet | None) -> dict:
    """A chat-style spawn: the same call shape the turn executor makes
    (fleet/chat.py build_turn_executor), with the skill set under test."""
    await k.store.upsert_capability(
        AgentCapability("script-worker", T, "script", ["*"], 2, True, "cheap")
    )
    perms = await k.store.get_tenant_permissions(T)
    ctx = InvocationContext(
        tenant_id=T,
        grants=perms.grants,
        actor="chief-of-staff",
        actor_tier="tier1",
        run_id="turn-1",
        on_behalf_of="alice",
    )
    spawner = build_spawner(k)
    return await spawner.spawn(
        T,
        "author a workflow for invoices",
        skills,
        {},
        ctx,
        partial_on_budget=True,
        grant_ceiling=ceiling,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-77")
async def test_chat_lane_spawn_with_authoring_skill_reaches_control_verbs():
    k = await _kernel()
    loaded = await load_skills_dir(k.store, T, str(_AUTHORING_SKILLS_DIR))
    assert "authoring/control-plane" in loaded  # the shipped data artifact
    result = await _chat_lane_spawn(k, ["authoring/control-plane"], GrantSet.of(["*"]))
    # the spawn hands the skill's control.* grant to the child untrimmed
    assert "control.*" in result["effective_grants"]
    # the run-scoped MCP token (exactly what the Pi runtime issues for the child)
    # sees and reaches the authoring verbs through the unchanged chokepoint...
    token = k.mcp.issue_run_token(
        T, GrantSet.of(result["effective_grants"]), run_id=result["run_id"], actor="ephemeral"
    )
    resp = await k.mcp.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"control.skill.upsert", "control.verb.define", "control.config.upsert"} <= names
    # ...and a call is HELD by the HITL gate (governed, not bypassed)
    call = await k.mcp.handle(
        token,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "control.workflow.upsert",
                "arguments": {"id": "chat-authored", "definition": {"steps": []}},
            },
        },
    )
    assert call["result"]["_boltrig"]["status"] == "pending_human"


@pytest.mark.security
@pytest.mark.invariant("SEC-77")
async def test_chat_lane_non_author_ceiling_strips_control_grants():
    k = await _kernel()
    await load_skills_dir(k.store, T, str(_AUTHORING_SKILLS_DIR))
    # a non-author caller ceiling (SEC-29/30 pattern) strips the skill's control
    # grant: loading the authoring skill can never escalate past the caller
    result = await _chat_lane_spawn(k, ["authoring/control-plane"], GrantSet.of(["ticket.*"]))
    assert "control.*" not in result["effective_grants"]
    token = k.mcp.issue_run_token(
        T, GrantSet.of(result["effective_grants"]), run_id=result["run_id"], actor="ephemeral"
    )
    call = await k.mcp.handle(
        token,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "control.skill.upsert", "arguments": {"id": "x"}},
        },
    )
    assert call["result"]["_boltrig"]["status"] == "denied"
    # The bare-turn authority fork recorded here was resolved by
    # [2026] VJS-COUNTY 1 (SEC-78 below): the production turn executor now
    # selects a bare turn's skill set from the manifest chat.skills_by_role knob
    # and ceilings every chat spawn with the caller's role-resolved grants. A
    # skill-less spawn still carries no verb grants at all:
    bare = await _chat_lane_spawn(k, [], None)
    assert bare["effective_grants"] == []


@pytest.mark.security
@pytest.mark.invariant("SEC-78")
async def test_bare_chat_turn_uses_manifest_skills_under_caller_ceiling():
    manifest = load_manifest(str(_EXAMPLE_MANIFEST))
    assert manifest.chat.skills_by_role["org-admin"] == ("authoring/control-plane",)
    assert manifest.chat.default_skills == ()

    k = await _kernel()
    await k.store.upsert_skill(
        Skill(
            id="authoring/control-plane",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="authoring",
            tool_grants=["control.*"],
        )
    )
    calls: list[dict] = []

    class _SpySpawner:
        async def spawn(
            self,
            tenant_id,
            task,
            skills,
            prefer,
            context,
            *,
            partial_on_budget=True,
            grant_ceiling=None,
        ):
            calls.append(
                {
                    "tenant_id": tenant_id,
                    "skills": list(skills),
                    "grant_ceiling": grant_ceiling,
                    "partial_on_budget": partial_on_budget,
                }
            )
            return {"summary": "ok"}

    svc = ChatService(
        k.store,
        EventRelay(),
        turn_executor=build_turn_executor(
            k,
            _SpySpawner(),
            continuity=False,
            chat_config=ChatConfig(
                skills_by_role={"org-admin": ("authoring/control-plane", "missing/skill")},
                default_skills=("missing/default",),
            ),
        ),
    )

    events = [
        ev
        async for ev in svc.handle_turn(
            tenant_id=T,
            user_id="alice",
            role="org-admin",
            grants=GrantSet.of(["ticket.*"]),
            message="author a workflow",
        )
    ]
    assert any(ev.get("type") == "text_delta" and ev.get("delta") == "ok" for ev in events)
    assert calls[0]["skills"] == ["authoring/control-plane"]
    assert calls[0]["grant_ceiling"] == GrantSet.of(["ticket.*"])
    assert calls[0]["partial_on_budget"] is True

    async for _ in svc.handle_turn(
        tenant_id=T,
        user_id="bob",
        role="viewer",
        grants=None,
        message="read only",
    ):
        pass
    assert calls[-1]["skills"] == []
    assert calls[-1]["grant_ceiling"] == GrantSet.of([])
