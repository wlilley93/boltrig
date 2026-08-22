"""Per-workspace agent rosters (0083), and the authority the scope withdraws.

One account can run two businesses. These are the contracts that make that true
and keep it safe: a spawn inside a workspace routes to that workspace's roster
plus the shared org-wide profiles and to nothing else; a caller operating inside
a workspace can author only inside it; and an org-scoped manifest apply leaves
every workspace roster alone.

The manifest test is the one that would otherwise fail silently.
``deactivate_absent_manifest_capabilities`` took ``(tenant_id,
declared_names)``, so the first apply after any workspace authored a manifest
agent would have soft-deactivated it - and a soft-deactivated row still exists,
so nothing looks wrong except that the agent stops being selectable.
"""

from __future__ import annotations

import pytest

from boltrig.config.capability_scope import WORKSPACE_SCOPE_FORBIDDEN
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.fleet.spawn_skills import NoCapableRuntime, select_capability
from boltrig.kernel import Kernel
from boltrig.models import (
    AdapterFailure,
    AgentCapability,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "roster-tenant"
WS_A = "ws-northwind"
WS_B = "ws-acme"


def _capability(
    name: str, *, workspace_id: str | None = None, source: str = "control-plane"
) -> AgentCapability:
    return AgentCapability(
        name=name,
        tenant_id=T,
        runtime="python-script",
        supported_skills=["records/*"],
        max_depth=2,
        is_ephemeral=True,
        cost_tier="cheap",
        workspace_id=workspace_id,
        source=source,
    )


def _context(verb: str, workspace_id: str | None) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="author",
        actor_tier="human",
        run_id=f"run-{verb.rsplit('.', 1)[-1]}-{workspace_id or 'org'}",
        workspace_id=workspace_id,
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


async def _approved(
    kernel: Kernel, verb: str, params: dict, workspace_id: str | None
) -> dict:
    context = _context(verb, workspace_id)
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, context)
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    return await kernel.invoke(
        "control", verb, params, context, approval_id=request_id
    )


# --- the roster itself -------------------------------------------------------


@pytest.mark.security
async def test_two_workspaces_see_different_rosters_and_share_the_org_wide_one() -> None:
    store = InMemoryStore()
    await store.upsert_capability(_capability("shared-researcher"))
    await store.upsert_capability(_capability("northwind-only", workspace_id=WS_A))
    await store.upsert_capability(_capability("acme-only", workspace_id=WS_B))

    async def roster(workspace_id: str | None) -> set[str]:
        return {
            item.name
            for item in await store.list_capabilities(
                T, workspace_id=workspace_id, enforce_workspace=True
            )
        }

    assert await roster(WS_A) == {"shared-researcher", "northwind-only"}
    assert await roster(WS_B) == {"shared-researcher", "acme-only"}
    # Org scope with the fence up is org-wide ONLY, never the union of every
    # workspace: an unscoped caller holds un-narrowed org grants, so widening
    # here would answer an unscoped request with more than either workspace has.
    assert await roster(None) == {"shared-researcher"}
    # The trusted unfiltered read is the only way to see everything.
    assert {item.name for item in await store.list_capabilities(T)} == {
        "shared-researcher",
        "northwind-only",
        "acme-only",
    }


@pytest.mark.security
async def test_one_name_per_scope_so_a_workspace_can_shadow_a_shared_agent() -> None:
    store = InMemoryStore()
    await store.upsert_capability(_capability("researcher"))
    await store.upsert_capability(_capability("researcher", workspace_id=WS_A))
    shadowed = await store.list_capabilities(T, workspace_id=WS_A, enforce_workspace=True)
    assert sorted(item.workspace_id or "" for item in shadowed) == ["", WS_A]
    # Same scope, same name: an upsert REPLACES rather than adding a third row.
    await store.upsert_capability(_capability("researcher", workspace_id=WS_A))
    assert len(await store.list_capabilities(T)) == 2


@pytest.mark.security
async def test_a_spawn_cannot_route_to_another_workspaces_agent() -> None:
    store = InMemoryStore()
    await store.upsert_capability(_capability("acme-only", workspace_id=WS_B))
    with pytest.raises(NoCapableRuntime):
        await select_capability(store, T, ["records/read"], {}, workspace_id=WS_A)
    chosen = await select_capability(store, T, ["records/read"], {}, workspace_id=WS_B)
    assert chosen.name == "acme-only"
    # A spawn with NO active workspace is org-wide only, not the union of every
    # workspace. Fail-closed: an unscoped caller holds un-narrowed org grants, so
    # letting it reach a workspace roster would answer an unscoped request with
    # more authority than either workspace has.
    with pytest.raises(NoCapableRuntime):
        await select_capability(store, T, ["records/read"], {})

    # The negative control, seeding the case the fence must NOT catch: make the
    # same agent org-wide and every one of those three calls now succeeds.
    # Without this the three refusals above are equally consistent with a
    # selector that never finds anything.
    await store.upsert_capability(_capability("acme-only"))
    for scope in (WS_A, WS_B, None):
        selected = await select_capability(
            store, T, ["records/read"], {}, workspace_id=scope
        )
        assert selected.name == "acme-only"


# --- authoring authority -----------------------------------------------------


@pytest.mark.security
async def test_a_workspace_author_may_not_touch_another_workspace() -> None:
    kernel = await _kernel()
    with pytest.raises(AdapterFailure) as refused:
        await kernel.invoke(
            "control",
            "control.capability.upsert",
            {"name": "smuggled", "runtime": "python-script", "workspace_id": WS_B},
            _context("control.capability.upsert", WS_A),
        )
    assert refused.value.status_code == 403
    assert refused.value.reason == WORKSPACE_SCOPE_FORBIDDEN
    assert await kernel.store.list_capabilities(T) == []


@pytest.mark.security
async def test_a_workspace_author_can_no_longer_edit_the_org_wide_profile() -> None:
    """THE AUTHORITY THIS CHANGE WITHDRAWS.

    ``WORKSPACE_ROLE_CEILINGS`` denies a workspace admin only
    ``control.workspace.*``, so before 0083 an author operating inside a
    workspace could edit an agent profile the whole organisation sees. Omitting
    ``workspace_id`` now means THEIR workspace, so the same call authors a
    workspace-scoped profile and the shared one is untouched.
    """
    kernel = await _kernel()
    await kernel.store.upsert_capability(_capability("researcher"))
    result = await _approved(
        kernel,
        "control.capability.upsert",
        {"name": "researcher", "runtime": "codex", "max_depth": 9},
        WS_A,
    )
    assert result["workspace_id"] == WS_A
    assert result["scope"] == "workspace"

    rows = {
        (item.workspace_id, item.runtime, item.max_depth)
        for item in await kernel.store.list_all_capabilities(T)
    }
    assert rows == {(None, "python-script", 2), (WS_A, "codex", 9)}


@pytest.mark.security
async def test_an_org_author_reaches_org_wide_and_any_named_workspace() -> None:
    kernel = await _kernel()
    org = await _approved(
        kernel,
        "control.capability.upsert",
        {"name": "researcher", "runtime": "python-script"},
        None,
    )
    assert org["scope"] == "organisation" and org["workspace_id"] is None
    scoped = await _approved(
        kernel,
        "control.capability.upsert",
        {"name": "researcher", "runtime": "codex", "workspace_id": WS_B},
        None,
    )
    assert scoped["workspace_id"] == WS_B
    assert sorted(
        (item.workspace_id or "") for item in await kernel.store.list_all_capabilities(T)
    ) == ["", WS_B]


@pytest.mark.security
async def test_retiring_inside_a_workspace_leaves_the_shared_agent_active() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_capability(_capability("researcher"))
    await kernel.store.upsert_capability(_capability("researcher", workspace_id=WS_A))
    retired = await _approved(
        kernel, "control.capability.retire", {"name": "researcher"}, WS_A
    )
    assert retired["workspace_id"] == WS_A
    states = {
        (item.workspace_id, item.is_active)
        for item in await kernel.store.list_all_capabilities(T)
    }
    assert states == {(None, True), (WS_A, False)}


# --- manifest reconciliation -------------------------------------------------


@pytest.mark.security
async def test_an_org_manifest_apply_leaves_every_workspace_roster_alone() -> None:
    """The trap the plan named. An org-scoped reconcile must match the scope
    EXACTLY; the union predicate the reads use would deactivate both rows."""
    store = InMemoryStore()
    await store.upsert_capability(_capability("keeper", source="manifest"))
    await store.upsert_capability(_capability("dropped-org", source="manifest"))
    await store.upsert_capability(
        _capability("workspace-agent", workspace_id=WS_A, source="manifest")
    )
    deactivated = await store.deactivate_absent_manifest_capabilities(
        T, ["keeper"], workspace_id=None
    )
    assert deactivated == ["dropped-org"]
    active = {
        (item.workspace_id, item.name)
        for item in await store.list_capabilities(T)
    }
    assert active == {(None, "keeper"), (WS_A, "workspace-agent")}

    # The counterweight: a reconcile pinned to the workspace touches only its own
    # rows, so the scope is a real fence in both directions rather than a filter
    # that happens to exclude one case.
    assert await store.deactivate_absent_manifest_capabilities(
        T, [], workspace_id=WS_A
    ) == ["workspace-agent"]
    assert {item.name for item in await store.list_capabilities(T)} == {"keeper"}
