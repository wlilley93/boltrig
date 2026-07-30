"""Recoverable, governed skill/noun/verb archival contracts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AdapterFailure,
    BindingNotFound,
    GrantSet,
    InvocationContext,
    Noun,
    PendingHuman,
    Skill,
    TenantPermissions,
    Verb,
)
from boltrig.skills.loader import SkillNotFound, resolve_skill
from boltrig.store import InMemoryStore

T = "authored-definition-lifecycle"


def _context(label: str) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="author",
        actor_tier="human",
        run_id=f"run-{label}",
        extra={"principal_role": "org-admin", "principal_scope": {"all": True}},
    )


def _headers(*, role: str = "org-admin") -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": role,
        "x-boltrig-grants": "*",
    }


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_tickets())
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
    await kernel.hitl.answer(
        T, held.value.hitl_request_id, "approve", "reviewer"
    )
    return await kernel.invoke(
        "control",
        verb,
        params,
        _context(verb),
        approval_id=held.value.hitl_request_id,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
async def test_direct_authored_routes_finalize_with_caller_held_approval():
    kernel = await _kernel()
    client = TestClient(create_app(kernel))

    async def finalize(path: str, body: dict) -> dict:
        pending = client.post(path, headers=_headers(), json=body)
        assert pending.status_code == 202
        approval_id = pending.json()["hitl_request_id"]
        await kernel.hitl.answer(T, approval_id, "approve", "independent-reviewer")
        completed = client.post(
            path,
            headers={
                **_headers(),
                "x-boltrig-approval-id": approval_id,
            },
            json=body,
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "ok"
        return completed.json()

    await finalize(
        "/v1/skills",
        {
            "id": "review",
            "version": "1",
            "prompt_fragment": "Review carefully.",
        },
    )
    await finalize("/v1/skills/review/archive", {})
    await finalize("/v1/skills/review/restore", {})
    await finalize(
        "/v1/nouns",
        {"id": "project", "description": "Project"},
    )
    await finalize("/v1/nouns/project/archive", {})
    await finalize("/v1/nouns/project/restore", {})
    await finalize(
        "/v1/verbs",
        {
            "id": "project.read",
            "noun_id": "project",
            "input_schema": {},
            "output_schema": {},
        },
    )
    await finalize("/v1/verbs/project.read/archive", {})
    await finalize("/v1/verbs/project.read/restore", {})
    await finalize(
        "/v1/verbs/project.read/binding",
        {
            "target_type": "adapter",
            "target_ref": "memory-tickets",
        },
    )

    assert (await kernel.store.get_skill(T, "review")).is_active is True
    assert (await kernel.store.get_noun(T, "project")).is_active is True
    assert (await kernel.store.get_verb(T, "project.read")).is_active is True
    binding = await kernel.store.get_binding(T, "project.read")
    assert binding is not None and binding.target_ref == "memory-tickets"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-19")
async def test_author_inventory_retains_archived_definitions_and_runtime_omits_them():
    kernel = await _kernel()
    await kernel.store.upsert_skill(
        Skill(
            id="records/active",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Active",
        )
    )
    await kernel.store.upsert_skill(
        Skill(
            id="records/archived",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Archived",
        )
    )
    await kernel.store.upsert_noun(
        Noun(id="orphan", tenant_id=T, description="No verbs")
    )
    await kernel.store.set_skill_active(T, "records/archived", False)
    await kernel.store.set_verb_active(T, "ticket.read", False)
    client = TestClient(create_app(kernel))

    skills = client.get("/v1/skills", headers=_headers()).json()["skills"]
    assert {
        row["id"]: row["status"]
        for row in skills
        if row["id"].startswith("records/")
    } == {
        "records/active": "active",
        "records/archived": "archived",
    }
    nouns = client.get("/v1/nouns", headers=_headers()).json()["nouns"]
    assert next(row for row in nouns if row["id"] == "orphan")["status"] == "active"
    verbs = client.get("/v1/verbs", headers=_headers()).json()["verbs"]
    archived = next(row for row in verbs if row["id"] == "ticket.read")
    assert archived["status"] == "archived"
    assert archived["binding"]["target_ref"] == "memory-tickets"

    discovered = client.get("/v1/capabilities", headers=_headers()).json()
    assert "ticket.read" not in {row["id"] for row in discovered["verbs"]}
    member = _headers(role="member")
    member_skills = client.get("/v1/skills", headers=member).json()["skills"]
    assert "records/archived" not in {row["id"] for row in member_skills}
    assert client.get("/v1/nouns", headers=member).status_code == 403
    assert client.get("/v1/verbs", headers=member).status_code == 403
    assert client.get("/v1/skills/records/archived", headers=_headers()).status_code == 200
    assert client.get("/v1/skills/records/archived", headers=member).status_code == 403

    skill_pending = client.post(
        "/v1/skills/records/active/archive", headers=_headers()
    )
    assert skill_pending.status_code == 202
    assert skill_pending.json()["status"] == "pending_human"
    assert await kernel.store.get_skill(T, "records/active") is not None

    pending = client.post("/v1/nouns/ticket/archive", headers=_headers())
    assert pending.status_code == 202
    assert pending.json()["status"] == "pending_human"
    assert await kernel.store.get_noun(T, "ticket") is not None


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-19")
async def test_noun_and_verb_archive_fail_closed_and_restore_losslessly():
    kernel = await _kernel()
    original_binding = await kernel.store.get_binding(T, "ticket.read")
    assert original_binding is not None

    archived_noun = await _approved(
        kernel, "control.noun.archive", {"id": "ticket"}
    )
    assert archived_noun == {
        "id": "ticket",
        "definition_status": "archived",
    }
    assert await kernel.store.get_noun(T, "ticket") is None
    assert await kernel.store.get_verb(T, "ticket.read") is None
    assert (await kernel.store.get_noun_any(T, "ticket")).is_active is False
    assert (await kernel.store.get_verb_any(T, "ticket.read")).is_active is True
    assert await kernel.store.get_binding(T, "ticket.read") == original_binding
    assert not any(
        row["id"].startswith("ticket.")
        for row in (await kernel.discover(T, _context("discover")))["verbs"]
    )
    with pytest.raises(BindingNotFound):
        await kernel.invoke(
            "ticket",
            "ticket.read",
            {"id": "missing"},
            _context("invoke-archived-noun"),
        )
    with pytest.raises(AdapterFailure) as inactive_binding:
        await kernel.invoke(
            "control",
            "control.binding.set",
            {
                "verb_id": "ticket.read",
                "target_type": "adapter",
                "target_ref": "memory-tickets",
            },
            _context("bind-archived-noun"),
        )
    assert inactive_binding.value.reason == "authored_definition_inactive"
    with pytest.raises(AdapterFailure) as inactive_noun:
        await kernel.invoke(
            "control",
            "control.verb.define",
            {
                "id": "ticket.new",
                "noun_id": "ticket",
            },
            _context("define-under-archived-noun"),
        )
    assert inactive_noun.value.reason == "authored_definition_inactive"
    assert await kernel.store.get_verb_any(T, "ticket.new") is None
    with pytest.raises(AdapterFailure) as missing_noun:
        await kernel.invoke(
            "control",
            "control.verb.define",
            {
                "id": "orphan.read",
                "noun_id": "missing",
            },
            _context("define-orphan"),
        )
    assert missing_noun.value.reason == "control_resource_not_found"
    assert await kernel.store.get_verb_any(T, "orphan.read") is None

    # Replacement authoring is status-preserving, including an existing verb
    # whose unchanged noun is archived.
    await _approved(
        kernel,
        "control.noun.define",
        {"id": "ticket", "description": "Edited while archived"},
    )
    await _approved(
        kernel,
        "control.verb.define",
        {
            "id": "ticket.read",
            "noun_id": "ticket",
            "description": "Edited while archived",
        },
    )
    assert (await kernel.store.get_noun_any(T, "ticket")).is_active is False
    assert (await kernel.store.get_verb_any(T, "ticket.read")).is_active is True

    restored_noun = await _approved(
        kernel, "control.noun.restore", {"id": "ticket"}
    )
    assert restored_noun["definition_status"] == "active"
    assert await kernel.store.get_verb(T, "ticket.read") is not None

    archived_verb = await _approved(
        kernel, "control.verb.archive", {"id": "ticket.read"}
    )
    assert archived_verb["definition_status"] == "archived"
    assert await kernel.store.get_verb(T, "ticket.read") is None
    assert await kernel.store.get_binding(T, "ticket.read") == original_binding
    with pytest.raises(BindingNotFound):
        await kernel.invoke(
            "ticket",
            "ticket.read",
            {"id": "missing"},
            _context("invoke-archived-verb"),
        )
    restored_verb = await _approved(
        kernel, "control.verb.restore", {"id": "ticket.read"}
    )
    assert restored_verb["definition_status"] == "active"
    assert await kernel.store.get_verb(T, "ticket.read") is not None
    assert await kernel.store.get_binding(T, "ticket.read") == original_binding


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-19")
async def test_skill_archive_blocks_leaf_and_inherited_selection_until_restore():
    kernel = await _kernel()
    await kernel.store.upsert_skill(
        Skill(
            id="records/base",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Base",
            tool_grants=["ticket.read"],
        )
    )
    await kernel.store.upsert_skill(
        Skill(
            id="records/child",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Child",
            extends="records/base",
        )
    )

    archived = await _approved(
        kernel, "control.skill.archive", {"id": "records/base"}
    )
    assert archived["definition_status"] == "archived"
    assert await kernel.store.get_skill(T, "records/base") is None
    with pytest.raises(SkillNotFound):
        await resolve_skill(kernel.store, T, "records/base")
    with pytest.raises(SkillNotFound):
        await resolve_skill(kernel.store, T, "records/child")

    await _approved(
        kernel,
        "control.skill.upsert",
        {
            "id": "records/base",
            "version": "1.1.0",
            "prompt_fragment": "Edited base",
            "tool_grants": ["ticket.read"],
        },
    )
    latest = await kernel.store.get_skill_any(T, "records/base")
    assert latest.version == "1.1.0" and latest.is_active is False
    with pytest.raises(AdapterFailure) as archived_parent:
        await kernel.invoke(
            "control",
            "control.skill.upsert",
            {
                "id": "records/new-child",
                "prompt_fragment": "New child",
                "extends": "records/base",
            },
            _context("new-child"),
        )
    assert archived_parent.value.reason == "authored_definition_inactive"

    restored = await _approved(
        kernel, "control.skill.restore", {"id": "records/base"}
    )
    assert restored["definition_status"] == "active"
    resolved = await resolve_skill(kernel.store, T, "records/child")
    assert resolved.prompt_fragment == "Edited base\n\nChild"
    assert resolved.tool_grants == ["ticket.read"]


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-19")
async def test_lifecycle_approval_is_exact_and_reserved_control_surface_is_protected():
    kernel = await _kernel()
    params = {"id": "ticket"}
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "control", "control.noun.archive", params, _context("exact-noun")
        )
    await kernel.store.upsert_verb(
        Verb(
            id="ticket.extra",
            tenant_id=T,
            noun_id="ticket",
            input_schema={},
            output_schema={},
        )
    )
    await kernel.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer")
    with pytest.raises(PendingHuman) as rebound:
        await kernel.invoke(
            "control",
            "control.noun.archive",
            params,
            _context("exact-noun"),
            approval_id=held.value.hitl_request_id,
        )
    assert rebound.value.hitl_request_id != held.value.hitl_request_id
    assert await kernel.store.get_noun(T, "ticket") is not None

    control_noun = await kernel.store.get_noun_any(T, "control")
    control_verb = await kernel.store.get_verb_any(T, "control.noun.archive")
    assert control_noun is not None and control_noun.is_active
    assert control_verb is not None and control_verb.is_active
    with pytest.raises(AdapterFailure) as noun_blocked:
        await kernel.invoke(
            "control",
            "control.noun.archive",
            {"id": "control"},
            _context("protect-control-noun"),
        )
    assert noun_blocked.value.reason == "control_resource_protected"
    with pytest.raises(AdapterFailure) as verb_blocked:
        await kernel.invoke(
            "control",
            "control.verb.archive",
            {"id": "control.noun.restore"},
            _context("protect-control-verb"),
        )
    assert verb_blocked.value.reason == "control_resource_protected"
    assert await kernel.store.get_noun(T, "control") is not None
    assert await kernel.store.get_verb(T, "control.noun.restore") is not None
