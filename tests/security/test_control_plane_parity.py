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

Authority note (recorded per the beat): like the Round Seven control.* verbs,
the new verbs rely on the grant lattice, not a role check - a caller reaches
control.* only when its grant profile permits it (org-admin's ``{all: true}``
scope maps to the tenant-wide ``*`` grant; any other role mapping must name the
``control`` noun/verbs in its scope). The direct routes keep their can_author
role gate unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.config.admin import AdminConfig
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.fleet import build_spawner
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AgentCapability,
    GrantMissing,
    GrantSet,
    InvocationContext,
    PendingHuman,
    SchemaValidationError,
    TenantPermissions,
)
from boltrig.skills.loader import load_skills_dir
from boltrig.store import InMemoryStore

T = "acme"
_AUTHORING_SKILLS_DIR = Path(__file__).resolve().parents[2] / "libraries" / "skills" / "authoring"

# The six Beat 3.5 verbs with schema-valid params (used by the gate/deny loops).
_VERB_PARAMS: dict[str, dict] = {
    "control.skill.upsert": {"id": "authoring/new-skill", "prompt_fragment": "do x",
                             "tool_grants": ["ticket.read"]},
    "control.noun.define": {"id": "invoice", "description": "an invoice"},
    "control.verb.define": {"id": "invoice.read", "noun_id": "invoice"},
    "control.binding.set": {"verb_id": "invoice.read", "target_type": "adapter",
                            "target_ref": "memory-tickets"},
    "control.mcp_server.register": {"id": "ext-mcp", "url": "https://mcp.example.com"},
    "control.config.upsert": {"section": "hierarchy", "value": {"tiers": ["cos"]}},
}


async def _kernel(*, admin: AdminConfig | None = None) -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    await k.register_adapter(
        T, build_control_plane_adapter(store, loader=k.loader, admin=admin)
    )
    return k


def _ctx(grants: list[str], *, actor: str = "u", run_id: str = "run-35") -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(grants), actor=actor, run_id=run_id)


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
    body = {"id": "authoring/new-skill", "version": "2.0.0", "prompt_fragment": "do x",
            "tool_grants": ["ticket.read"], "locale": "en"}
    out = await _approved(kv, "control.skill.upsert", body)
    assert out == {"upserted": "skill", "id": body["id"], "version": "2.0.0"}
    assert client.post("/v1/skills", json=body, headers=_hdr()).status_code == 200
    assert await kv.store.get_skill(T, body["id"]) == await kr.store.get_skill(T, body["id"])

    # noun
    body = {"id": "invoice", "description": "an invoice", "schema": {"type": "object"}}
    await _approved(kv, "control.noun.define", body)
    assert client.post("/v1/nouns", json=body, headers=_hdr()).status_code == 200
    assert await kv.store.get_noun(T, "invoice") == await kr.store.get_noun(T, "invoice")

    # verb - including the safe-by-default consequence rule (SEC-39): "approve"
    # is a destructive token, so with no explicit consequence it stores as high.
    body = {"id": "invoice.approve", "noun_id": "invoice", "description": "approve one"}
    out = await _approved(kv, "control.verb.define", body)
    assert out["consequence"] == "high"
    assert client.post("/v1/verbs", json=body, headers=_hdr()).json()["consequence"] == "high"
    assert await kv.store.get_verb(T, "invoice.approve") == await kr.store.get_verb(
        T, "invoice.approve"
    )

    # binding
    body = {"verb_id": "invoice.approve", "target_type": "adapter", "target_ref": "billing"}
    await _approved(kv, "control.binding.set", body)
    r = client.post("/v1/verbs/invoice.approve/binding",
                    json={"target_type": "adapter", "target_ref": "billing"}, headers=_hdr())
    assert r.status_code == 200
    assert await kv.store.get_binding(T, "invoice.approve") == await kr.store.get_binding(
        T, "invoice.approve"
    )

    # MCP server registration - both paths park the consumer INERT (SEC-22)
    body = {"id": "ext-mcp", "url": "https://mcp.example.com"}
    out = await _approved(kv, "control.mcp_server.register", body)
    assert out["activated"] is False
    assert client.post("/v1/mcp/servers", json=body, headers=_hdr()).status_code == 200
    for k_ in (kv, kr):
        consumer = await k_.loader.get(T, "ext-mcp")
        assert consumer is not None and consumer.activated is False

    # config section - same revision recording as the PUT route, one AdminConfig
    body = {"section": "hierarchy", "value": {"tiers": ["cos", "head"]}}
    out = await _approved(kv, "control.config.upsert", body)
    r = client.put("/v1/admin/config/hierarchy", json={"value": body["value"]}, headers=_hdr())
    assert r.status_code == 200
    assert admin_v.section("hierarchy") == admin_r.section("hierarchy") == body["value"]
    revs_v = await admin_v.history("hierarchy")
    revs_r = await admin_r.history("hierarchy")
    assert [rv.payload for rv in revs_v] == [rr.payload for rr in revs_r]
    assert revs_v[0].id == out["revision"] and revs_v[0].actor == "u"

    # every verb dispatch was audited as a kernel verb (governed, SEC-16)
    events = await kv.store.audit_query(T, limit=200)
    for verb in _VERB_PARAMS:
        assert any(e.verb == verb and e.status == "ok" for e in events)


@pytest.mark.security
@pytest.mark.invariant("SEC-75")
async def test_every_control_verb_is_hitl_held_and_writes_nothing_while_pending():
    admin = AdminConfig(InMemoryStore(), tenant_id=T, doc={})
    k = await _kernel(admin=admin)
    for verb, params in _VERB_PARAMS.items():
        with pytest.raises(PendingHuman):
            await k.invoke("control", verb, params, _ctx(["*"]))
    # held means held: none of the writes happened (fail-closed while pending)
    assert await k.store.get_skill(T, "authoring/new-skill") is None
    assert await k.store.get_noun(T, "invoice") is None
    assert await k.store.get_verb(T, "invoice.read") is None
    assert await k.store.get_binding(T, "invoice.read") is None
    assert await k.loader.get(T, "ext-mcp") is None
    assert admin.section("hierarchy") is None


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
        await k.invoke("control", "control.mcp_server.register",
                       {"id": "ext-mcp", "url": "https://mcp.example.com", "token": "s3cret"},
                       _ctx(["*"]))
    out = await _approved(k, "control.mcp_server.register",
                          {"id": "ext-mcp", "url": "https://mcp.example.com"})
    assert out == {"registered": "mcp_server", "id": "ext-mcp", "activated": False}
    consumer = await k.loader.get(T, "ext-mcp")
    assert consumer.activated is False  # inert until the SEC-22 review route
    # activation deliberately has NO verb - the human review route is the gate
    assert await k.store.get_verb(T, "control.mcp_server.activate") is None


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
    ctx = InvocationContext(tenant_id=T, grants=perms.grants, actor="chief-of-staff",
                            actor_tier="tier1", run_id="turn-1", on_behalf_of="alice")
    spawner = build_spawner(k)
    return await spawner.spawn(T, "author a workflow for invoices", skills, {}, ctx,
                               partial_on_budget=True, grant_ceiling=ceiling)


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
    token = k.mcp.issue_run_token(T, GrantSet.of(result["effective_grants"]),
                                  run_id=result["run_id"], actor="ephemeral")
    resp = await k.mcp.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"control.skill.upsert", "control.verb.define", "control.config.upsert"} <= names
    # ...and a call is HELD by the HITL gate (governed, not bypassed)
    call = await k.mcp.handle(token, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "control.workflow.upsert",
                   "arguments": {"id": "chat-authored", "definition": {"steps": []}}},
    })
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
    token = k.mcp.issue_run_token(T, GrantSet.of(result["effective_grants"]),
                                  run_id=result["run_id"], actor="ephemeral")
    call = await k.mcp.handle(token, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "control.skill.upsert", "arguments": {"id": "x"}},
    })
    assert call["result"]["_boltrig"]["status"] == "denied"
    # Recorded fork, not a fix (see the beat notes): the production turn executor
    # spawns with skills=[] (fleet/chat.py), so a BARE chat turn's child carries
    # no verb grants at all - authoring from chat needs the authoring skill in
    # the spawn's skill set. Which authority a bare turn should carry is a
    # design decision, deliberately not changed here.
    bare = await _chat_lane_spawn(k, [], None)
    assert bare["effective_grants"] == []
