"""Round Fifteen - the extension contract (FR-SKILL/EXT, SEC-57).

The on-demand skill shelf (browse-by-description, load-on-demand), governed config
loading from a project bundle (adapter module_ref, mcp.consume), all behind the
chokepoint.

FR-SKILL-01  skill.search returns the shelf as descriptions only - never bodies.
FR-SKILL-02  skill.load composes the (inheritance-merged) body bound to the job's
             context, validated against the skill's context_requirements.
SEC-57       skill.* run the chokepoint (grant-checked, tenant-scoped) AND a loaded
             skill is data not authority - load returns the skill's tool_grants but
             does NOT grant them, so it cannot escalate.
FR-EXT-01    a manifest adapter declared by module_ref (non-builtin) is loaded.
FR-EXT-02    external MCP servers in manifest mcp.consume register inert (SEC-22).
"""

from __future__ import annotations

import pytest

from nankle.adapters.builtin.memory_tickets import build as build_tickets
from nankle.kernel import Kernel
from nankle.models import GrantMissing, GrantSet, InvocationContext, Skill, TenantPermissions
from nankle.skills.shelf import build_skill_shelf_adapter
from nankle.store import InMemoryStore

T = "acme"


async def _kernel_with_shelf() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_skill_shelf_adapter(store))
    await k.register_adapter(T, build_tickets())
    # seed a shelf: a parent + a child skill with a description, grants, and a
    # per-job context requirement.
    await store.upsert_skill(Skill(
        id="renewal/base", tenant_id=T, version="1.0.0",
        prompt_fragment="Base renewal procedure.", tool_grants=["ticket.read"],
        description="Foundations for any renewal workup."))
    await store.upsert_skill(Skill(
        id="renewal/adgm", tenant_id=T, version="1.0.0", extends="renewal/base",
        prompt_fragment="ADGM-specific renewal steps.",
        tool_grants=["ticket.create"],
        context_requirements={"type": "object",
                              "properties": {"entity_id": {"type": "string"}},
                              "required": ["entity_id"]},
        description="Do an ADGM company renewal workup."))
    return k


def _ctx(grants: list[str]) -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(grants), actor="u", run_id="r15")


# --------------------------------------------------------------------------- #
# FR-SKILL-01  the shelf is descriptions, never bodies
# --------------------------------------------------------------------------- #
@pytest.mark.invariant("FR-SKILL-01")
async def test_skill_search_returns_descriptions_not_bodies():
    k = await _kernel_with_shelf()
    out = await k.invoke("skill", "skill.search", {"query": "renewal"}, _ctx(["*"]))
    ids = {s["id"] for s in out["skills"]}
    assert ids == {"renewal/base", "renewal/adgm"}
    for s in out["skills"]:
        assert s["description"]  # a shelf label is present
        assert "prompt_fragment" not in s  # the body is NEVER on the shelf
    # query filters the shelf
    only = await k.invoke("skill", "skill.search", {"query": "adgm"}, _ctx(["*"]))
    assert {s["id"] for s in only["skills"]} == {"renewal/adgm"}


# --------------------------------------------------------------------------- #
# FR-SKILL-02  load composes the inherited body bound to validated job context
# --------------------------------------------------------------------------- #
@pytest.mark.invariant("FR-SKILL-02")
async def test_skill_load_composes_body_and_binds_context():
    k = await _kernel_with_shelf()
    out = await k.invoke("skill", "skill.load",
                         {"id": "renewal/adgm", "context": {"entity_id": "E-1"}}, _ctx(["*"]))
    # inheritance merged parent-first into the body
    assert "Base renewal procedure." in out["prompt_fragment"]
    assert "ADGM-specific renewal steps." in out["prompt_fragment"]
    assert out["bound_context"] == {"entity_id": "E-1"}  # the job context bound in

    # missing required job context is refused (ContextRequirementsUnmet -> 400)
    from nankle.models import ContextRequirementsUnmet

    with pytest.raises(ContextRequirementsUnmet):
        await k.invoke("skill", "skill.load", {"id": "renewal/adgm"}, _ctx(["*"]))


# --------------------------------------------------------------------------- #
# SEC-57  governed + data-not-authority
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-57")
async def test_skill_shelf_is_governed_and_load_does_not_escalate():
    k = await _kernel_with_shelf()
    # the shelf runs the chokepoint: a caller without skill.* is denied
    with pytest.raises(GrantMissing):
        await k.invoke("skill", "skill.search", {}, _ctx(["ticket.read"]))

    # a caller may load a skill (has skill.*) but lacks ticket.create
    grants = ["skill.search", "skill.describe", "skill.load", "ticket.read"]
    loaded = await k.invoke("skill", "skill.load",
                            {"id": "renewal/adgm", "context": {"entity_id": "E-1"}}, _ctx(grants))
    # the skill's wanted grant is returned as DATA...
    assert "ticket.create" in loaded["tool_grants"]
    # ...but loading did NOT grant it: the caller still cannot call ticket.create
    with pytest.raises(GrantMissing):
        await k.invoke("ticket", "ticket.create", {"title": "x"}, _ctx(grants))
