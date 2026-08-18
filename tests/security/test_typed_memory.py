"""Typed memory-plane invariants: MEM-TYP-01..06 (decision 0029).

The typed write gate governs what may become durable memory: one active value
per semantic/procedural slot with source-precedence supersession (MEM-TYP-01);
present-state wording is never a durable fact (MEM-TYP-02); unapproved
procedure candidates never govern and active procedures are selected
deterministically, not by similarity (MEM-TYP-03); episodes are embedded by
their problem representation, not their resolution (MEM-TYP-04); the bundle
respects per-plane budgets and working state is pass-through, never memory
(MEM-TYP-05); explicit review is the only activation path for candidates
(MEM-TYP-06). Scope fencing of the typed paths rides SEC-40.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.memory import LocalMemoryEngine
from boltrig.memory.adapter import build_memory_adapter
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    adapter = build_memory_adapter(LocalMemoryEngine(), store, audit=k.audit)
    await k.register_adapter(T, adapter)
    return k, store


def _client(k) -> TestClient:
    return TestClient(create_app(k, platform={}))


def _h(sub, role="employee", grants="*"):
    return {"x-boltrig-tenant": T, "x-boltrig-subject": sub, "x-boltrig-role": role,
            "x-boltrig-grants": grants}


def _propose(c, sub, **overrides):
    body = {
        "plane": "semantic",
        "subject_type": "repository",
        "subject_id": "repo19",
        "predicate": "package_manager",
        "confidence": 0.9,
        "source_authority": "human_statement",
    }
    body.update(overrides)
    return c.post("/v1/memory/propose", json=body, headers=_h(sub)).json()


def _review(c, k, candidate_id, decision, sub="alice"):
    """Complete the (HITL-gated) review verb: high consequence means an agent
    can never self-serve an activation - a human must answer the request."""
    url = f"/v1/memory/candidates/{candidate_id}/review"
    response = c.post(url, json={"decision": decision}, headers=_h(sub))
    if response.status_code == 202:
        request_id = response.json()["hitl_request_id"]
        asyncio.run(k.hitl.answer(T, request_id, "approve", "independent-reviewer"))
        response = c.post(url, json={"decision": decision},
                          headers={**_h(sub), "x-boltrig-approval-id": request_id})
    return response


def _resolve(c, sub, subject_id="repo19"):
    return c.get(
        "/v1/memory/resolve",
        params={"subject_type": "repository", "subject_id": subject_id},
        headers=_h(sub),
    )


# --- MEM-TYP-01: one active value per slot; supersession + source precedence --
@pytest.mark.security
@pytest.mark.invariant("MEM-TYP-01")
def test_semantic_supersession_returns_only_current_value():
    k, store = asyncio.run(_kernel())
    c = _client(k)
    first = _propose(c, "alice", value="npm", statement="repo19 uses npm.",
                     source_authority="verified_integration")
    assert first["decision"] == "ACCEPT_NEW"
    second = _propose(c, "alice", value="pnpm",
                      statement="repo19 uses pnpm.",
                      source_authority="authoritative_system")
    assert second["decision"] == "SUPERSEDE_EXISTING"
    # Only the current value is resolvable; the old one is history, not truth.
    facts = _resolve(c, "alice").json()["facts"]
    assert [f["value"] for f in facts] == ["pnpm"]
    assert facts[0]["version"] == 2
    # A lower-authority source cannot overwrite the authoritative current value.
    stale = _propose(c, "alice", value="npm", statement="repo19 uses npm again.",
                     source_authority="unverified_inference")
    assert stale["decision"] == "REJECT_LOWER_AUTHORITY"
    assert stale["persisted"] is False
    # Equal authority + different value is a conflict, not a silent overwrite.
    conflict = _propose(c, "alice", value="yarn", statement="repo19 uses yarn.",
                        source_authority="authoritative_system")
    assert conflict["decision"] == "REQUEST_HUMAN_REVIEW"
    assert _resolve(c, "alice").json()["facts"][0]["value"] == "pnpm"
    # The timeline keeps the full auditable history - including the equal-
    # authority conflict parked as a candidate - while only v2 governs.
    timeline = c.get("/v1/memory/timeline", params={
        "subject_type": "repository", "subject_id": "repo19",
        "predicate": "package_manager"}, headers=_h("alice")).json()["versions"]
    assert [(v["version"], v["status"]) for v in timeline] == [
        (2, "active"),
        (1, "superseded"),
        (1, "candidate"),
    ]
    events = asyncio.run(store.list_memory_events(T))
    kinds = {e.event for e in events}
    assert "memory_superseded" in kinds and "memory_activated" in kinds


# --- MEM-TYP-02: present state is never durable semantic memory ---------------
@pytest.mark.security
@pytest.mark.invariant("MEM-TYP-02")
def test_transient_statement_never_becomes_semantic():
    k, store = asyncio.run(_kernel())
    c = _client(k)
    transient = _propose(c, "alice", value="failing",
                         statement="The repository's tests are failing this morning.")
    assert transient["decision"] == "REJECT_TRANSIENT"
    assert transient["persisted"] is False
    assert _resolve(c, "alice").json()["facts"] == []
    # An explicit durability assertion is respected (the extractor's judgement).
    durable = _propose(c, "alice", value="pnpm",
                       statement="The repository's tests run via pnpm test.",
                       is_durable=True)
    assert durable["decision"] == "ACCEPT_NEW"


# --- MEM-TYP-03: procedures govern only after review; deterministic selection --
@pytest.mark.security
@pytest.mark.invariant("MEM-TYP-03")
def test_unapproved_procedures_never_govern_and_selection_is_deterministic():
    k, _ = asyncio.run(_kernel())
    c = _client(k)
    bundle_body = {
        "query": "garden plants and unrelated poetry",
        "agent_role": "coding-agent",
        "workflow": "repository-change",
        "subjects": [],
    }
    proposed = c.post("/v1/memory/propose", json={
        "plane": "procedural",
        "procedure_key": "platform::coding-agent::repository-change",
        "title": "Repository change completion",
        "summary": "Inspect repo instructions before editing; use the existing "
                   "package manager; run the narrowest validation.",
        "body_markdown": "# Repository change completion\nInspect before editing.",
        "applies_to_roles": ["coding-agent"],
        "applies_to_workflows": ["repository-change"],
        "invariants": ["Inspect repository instructions before editing.",
                       "Report tests actually run."],
        "confidence": 0.95,
    }, headers=_h("alice")).json()
    assert proposed["decision"] == "REQUEST_HUMAN_REVIEW"
    # A candidate never governs: the bundle (even with a semantically similar
    # query) carries no procedure.
    before = c.post("/v1/memory/bundle", json={
        **bundle_body, "query": "repository change completion package manager validation",
    }, headers=_h("alice")).json()
    assert before["procedures"] == []
    # After explicit review it governs - selected by role/workflow, with a
    # query that shares none of its wording (deterministic, not similarity).
    approved = _review(c, k, proposed["candidate_id"], "approve").json()
    assert approved["status"] == "ok"
    assert approved["candidate_status"] == "active"
    after = c.post("/v1/memory/bundle", json=bundle_body, headers=_h("alice")).json()
    assert len(after["procedures"]) == 1
    assert after["procedures"][0]["payload"]["procedure_key"] == \
        "platform::coding-agent::repository-change"
    assert "<active_procedures>" in after["prompt"]
    # A role the procedure does not address never receives it.
    other = c.post("/v1/memory/bundle", json={
        **bundle_body, "agent_role": "browser-agent"}, headers=_h("alice")).json()
    assert other["procedures"] == []


# --- MEM-TYP-04: episodes are embedded by the problem, not the resolution ------
@pytest.mark.security
@pytest.mark.invariant("MEM-TYP-04")
def test_episodes_are_retrieved_by_problem_not_resolution():
    k, _ = asyncio.run(_kernel())
    c = _client(k)
    proposed = c.post("/v1/memory/propose", json={
        "plane": "episodic",
        "title": "Fresh macOS pnpm installation failure",
        "retrieval_text": "pnpm ERR_PNPM_NO_GLOBAL_BIN_DIR on fresh macos: "
                          "PNPM_HOME not configured, corepack disabled",
        "outcome": "succeeded",
        "is_terminal": True,
        "attempted": ["re-ran pnpm install"],
        "failed_attempts": ["repeating the installation did not change the error"],
        "root_cause": "Corepack and PNPM_HOME had not been initialised",
        "resolution": "Enable Corepack, configure PNPM_HOME and restart the shell",
        "confidence": 0.9,
    }, headers=_h("alice")).json()
    assert proposed["decision"] == "ACCEPT_NEW"
    # A future agent's SYMPTOM wording retrieves the episode; the prompt shows
    # the problem, the failed attempts and the resolution as precedent.
    bundle = c.post("/v1/memory/bundle", json={
        "query": "pnnpm global bin dir error macos fresh setup",
        "subjects": [], "agent_role": "", "workflow": "",
    }, headers=_h("alice")).json()
    assert len(bundle["episodes"]) == 1
    episode = bundle["episodes"][0]
    assert "ERR_PNPM_NO_GLOBAL_BIN_DIR" in episode["retrieval_text"]
    assert "Corepack" in episode["resolution"]
    assert episode["failed_attempts"]
    assert 'advisory="true"' in bundle["prompt"]
    assert "precedent" in bundle["prompt"]
    # A non-terminal run is working state, not an episode.
    running = c.post("/v1/memory/propose", json={
        "plane": "episodic",
        "title": "Investigation in progress",
        "retrieval_text": "pnpm install error still being investigated",
        "outcome": "succeeded",
        "is_terminal": False,
        "confidence": 0.9,
    }, headers=_h("alice")).json()
    assert running["decision"] == "REJECT_NOT_TERMINAL"
    assert running["persisted"] is False


# --- MEM-TYP-05: budgets clip; working state passes through, never persists ----
@pytest.mark.security
@pytest.mark.invariant("MEM-TYP-05")
def test_bundle_budgets_clip_and_working_state_never_persists():
    k, _ = asyncio.run(_kernel())
    c = _client(k)
    _propose(c, "alice", predicate="test_command", value="pnpm test:unit",
             statement="repo19 test_command is pnpm test:unit.")
    bundle = c.post("/v1/memory/bundle", json={
        "query": "unrelated query",
        "subjects": [{"type": "repository", "id": "repo19"}],
        "working_context": ["61 of 92 tests complete, still running"],
        "config": {"budget": {"semantic_chars": 10}},
    }, headers=_h("alice")).json()
    assert bundle["working_context"] == ["61 of 92 tests complete, still running"]
    assert "<working_state>" in bundle["prompt"]
    assert "61 of 92 tests complete" in bundle["prompt"]
    assert "semantic section clipped to budget" in bundle["warnings"]
    # Working state never becomes memory: a later run cannot recall it.
    later = c.post("/v1/memory/bundle", json={
        "query": "61 of 92 tests complete still running",
        "subjects": [{"type": "repository", "id": "repo19"}],
    }, headers=_h("alice")).json()
    flat = str(later["episodes"]) + str(later["semantic_facts"]) + str(later["source_context"])
    assert "61 of 92" not in flat
    # Per-plane toggles exist for the ablation harness.
    ablated = c.post("/v1/memory/bundle", json={
        "query": "pnpm test:unit",
        "subjects": [{"type": "repository", "id": "repo19"}],
        "config": {"semantic": False},
    }, headers=_h("alice")).json()
    assert ablated["config_label"] == "no-semantic"
    assert ablated["semantic_facts"] == []


# --- MEM-TYP-06: review is the only activation path for candidates ------------
@pytest.mark.security
@pytest.mark.invariant("MEM-TYP-06")
def test_review_is_the_only_activation_path():
    k, store = asyncio.run(_kernel())
    c = _client(k)
    proposed = c.post("/v1/memory/propose", json={
        "plane": "procedural",
        "procedure_key": "platform::coding-agent::security-diff-review",
        "title": "Security diff review",
        "body_markdown": "# Security diff review",
        "applies_to_roles": ["coding-agent"],
        "applies_to_workflows": ["security-diff-review"],
        "confidence": 0.99,
    }, headers=_h("alice")).json()
    assert proposed["decision"] == "REQUEST_HUMAN_REVIEW"
    row = asyncio.run(store.get_memory_fact(T, proposed["candidate_id"]))
    assert row.status == "candidate"  # confidence alone never activates
    rejected = _review(c, k, proposed["candidate_id"], "reject").json()
    assert rejected["candidate_status"] == "rejected"
    # A rejected candidate cannot be re-activated by reviewing it again.
    rereview = _review(c, k, proposed["candidate_id"], "approve")
    assert rereview.status_code == 400
    # Every decision left a gate event with the policy version attached.
    events = asyncio.run(store.list_memory_events(T, memory_id=proposed["candidate_id"]))
    assert {e.event for e in events} == {"candidate_created", "candidate_rejected"}
    assert all(e.policy_version == "typed-write-v1" for e in events)


# --- SEC-40 extension: the typed paths are scope-fenced ------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-40")
def test_typed_recall_is_scope_fenced():
    k, _ = asyncio.run(_kernel())
    c = _client(k)
    assert _propose(c, "bob", value="npm",
                    statement="repo19 uses npm.").get("decision") == "ACCEPT_NEW"
    # Alice cannot see bob's slot through any typed read path.
    assert _resolve(c, "alice").json()["facts"] == []
    timeline = c.get("/v1/memory/timeline", params={
        "subject_type": "repository", "subject_id": "repo19",
        "predicate": "package_manager", "owner_scope": "user:bob",
    }, headers=_h("alice"))
    assert timeline.status_code == 404
    bundle = c.post("/v1/memory/bundle", json={
        "query": "repo19 package manager npm",
        "subjects": [{"type": "repository", "id": "repo19"}],
    }, headers=_h("alice")).json()
    assert bundle["semantic_facts"] == []
    assert "npm" not in bundle["prompt"]
    # Bob's own scope resolves fine.
    assert [f["value"] for f in _resolve(c, "bob").json()["facts"]] == ["npm"]
