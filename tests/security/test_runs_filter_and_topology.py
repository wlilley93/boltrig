"""G7: /v1/runs owner/label/external-ref filters + the durable run-topology reader.

Two invariants, at the run_access + store layer (no HTTP needed):
  1. list_run_items_scoped filters only NARROW the already dept+workspace-scoped,
     hidden-wins-deduped set - a filter can remove rows, never widen visibility.
  2. visible_run_topology reconstructs the root's parent/child subtree by BFS,
     with the SAME dept + enforced-workspace visibility - a hidden (cross-dept)
     descendant is structurally absent, and an unknown/foreign root returns None.
"""

from __future__ import annotations

import pytest

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal
from boltrig.kernel.run_access import visible_run_topology
from boltrig.models import GrantSet, WorkItem, WorkStatus
from boltrig.store import InMemoryStore

T = "acme"


def _principal(
    *,
    role: str = "engineer",
    departments: list[str] | None = None,
    workspace: str | None = "ws-1",
) -> Principal:
    scope = {"all": True} if role == "org-admin" else {"departments": departments or []}
    return Principal(
        tenant_id=T,
        subject="reader",
        grants=GrantSet.of(["*"]),
        role=role,
        actor_tier="human",
        scope=scope,
        active_workspace_id=workspace,
    )


async def _seed() -> Kernel:
    store = InMemoryStore()
    kernel = Kernel(store)
    # root(eng) -> eng-child(eng) -> grandchild(eng); plus mkt-child(marketing)
    # under the same root, which an engineering-scoped caller must NOT see.
    items = [
        # id, dept, run_id, parent_id, source, source_id
        ("w-root", "engineering", "run-root", None, "opbox", "matter-1"),
        ("w-eng", "engineering", "run-eng", "w-root", "opbox", "matter-1"),
        ("w-gc", "engineering", "run-gc", "w-eng", "internal", None),
        ("w-mkt", "marketing", "run-mkt", "w-root", "opbox", "matter-1"),
    ]
    for item_id, dept, run_id, parent_id, source, source_id in items:
        await store.create_work_item(
            WorkItem(
                id=item_id,
                tenant_id=T,
                source=source,
                source_id=source_id,
                intent=f"task {item_id}",
                confidence=1.0,
                convergent=True,
                status=WorkStatus.DONE,
                owner_member=dept,
                hatchet_run_id=run_id,
                parent_id=parent_id,
            )
        )
    return kernel


@pytest.mark.invariant("SEC-69")
async def test_run_filters_narrow_within_the_visibility_fence():
    kernel = await _seed()

    # source='opbox' keeps the three opbox items; the internal grandchild drops.
    opbox = await kernel.store.list_run_items_scoped(T, source="opbox")
    assert {w.id for w in opbox} == {"w-root", "w-eng", "w-mkt"}

    # external_ref (opaque source_id) narrows to the matter's items only.
    matter = await kernel.store.list_run_items_scoped(T, external_ref="matter-1")
    assert {w.id for w in matter} == {"w-root", "w-eng", "w-mkt"}
    assert await kernel.store.list_run_items_scoped(T, external_ref="matter-nope") == []

    # A filter can only REMOVE from the dept-scoped set, never widen it: an
    # engineering-scoped caller never sees the marketing row even unfiltered.
    eng = await kernel.store.list_run_items_scoped(
        T, departments=["engineering"], workspace_id="ws-1"
    )
    assert "w-mkt" not in {w.id for w in eng}
    eng_src = await kernel.store.list_run_items_scoped(
        T, departments=["engineering"], workspace_id="ws-1", source="opbox"
    )
    assert {w.id for w in eng_src} <= {w.id for w in eng}


@pytest.mark.security
@pytest.mark.invariant("SEC-69")
async def test_execution_search_is_literal_bounded_and_preserves_hidden_wins():
    kernel = await _seed()
    searchable = WorkItem(
        id=r"exec%_\visible",
        tenant_id=T,
        workspace_id="ws-1",
        source="linear-source",
        source_id=r"case%_\42",
        intent="Quarterly Renewal Plan",
        confidence=1.0,
        convergent=True,
        status=WorkStatus.FAILED,
        owner_member="specialists",
        hatchet_run_id="run-renewal-42",
        on_behalf_of="alice-search",
    )
    await kernel.store.create_work_item(searchable)
    await kernel.store.create_work_item(WorkItem(
        id="collision-hidden",
        tenant_id=T,
        workspace_id="ws-1",
        source="internal",
        intent="hidden owner",
        confidence=1.0,
        convergent=True,
        owner_member="marketing",
        hatchet_run_id="run-collision",
    ))
    await kernel.store.create_work_item(WorkItem(
        id="collision-visible",
        tenant_id=T,
        workspace_id="ws-1",
        source="internal",
        intent="resurrect-me",
        confidence=1.0,
        convergent=True,
        owner_member="specialists",
        hatchet_run_id="run-collision",
    ))
    rival = WorkItem(
        id="rival-match",
        tenant_id="rival",
        workspace_id="ws-1",
        source="internal",
        intent="Quarterly Renewal Plan",
        confidence=1.0,
        convergent=True,
        owner_member="specialists",
    )
    await kernel.store.create_work_item(rival)

    for query in (
        "quarterly renewal",
        r"exec%_\visible",
        "RUN-RENEWAL-42",
        "specialists",
        "ALICE-SEARCH",
        "LINEAR-SOURCE",
        r"case%_\42",
        "FAILED",
    ):
        rows = await kernel.store.search_execution_items_scoped(
            T,
            query,
            departments=["specialists"],
            workspace_id="ws-1",
            limit=10,
        )
        assert [row.id for row in rows] == [searchable.id]

    # LIKE metacharacters stay literal, the caller-supplied bound is honoured,
    # and an out-of-department alias prevents its visible twin resurfacing.
    literal = await kernel.store.search_execution_items_scoped(
        T, "%_\\", departments=["specialists"], workspace_id="ws-1", limit=1
    )
    assert [row.id for row in literal] == [searchable.id]
    assert await kernel.store.search_execution_items_scoped(
        T, "resurrect-me", departments=["specialists"], workspace_id="ws-1", limit=10
    ) == []


@pytest.mark.invariant("SEC-69")
async def test_topology_reconstructs_subtree_and_excludes_hidden_descendant():
    kernel = await _seed()

    # Org-admin sees the whole subtree under the root, marketing child included.
    admin_tree = await visible_run_topology(kernel.store, _principal(role="org-admin", workspace=None), "run-root")
    assert admin_tree is not None
    root = admin_tree["root"]
    assert root["run_id"] == "run-root"
    child_runs = {c["run_id"] for c in root["children"]}
    assert child_runs == {"run-eng", "run-mkt"}
    eng_node = next(c for c in root["children"] if c["run_id"] == "run-eng")
    assert {g["run_id"] for g in eng_node["children"]} == {"run-gc"}
    assert root["external_ref"] == "matter-1"

    # An engineering-scoped caller sees root + eng-child + grandchild, but the
    # marketing child is structurally absent (BFS never followed a hidden link).
    eng_tree = await visible_run_topology(
        kernel.store, _principal(role="engineer", departments=["engineering"]), "run-root"
    )
    assert eng_tree is not None
    eng_child_runs = {c["run_id"] for c in eng_tree["root"]["children"]}
    assert eng_child_runs == {"run-eng"}


@pytest.mark.invariant("SEC-69")
async def test_topology_unknown_root_is_none():
    kernel = await _seed()
    admin = _principal(role="org-admin", workspace=None)
    assert await visible_run_topology(kernel.store, admin, "run-does-not-exist") is None

    # A cross-department root the caller cannot see is indistinguishable (None).
    eng = _principal(role="engineer", departments=["engineering"])
    assert await visible_run_topology(kernel.store, eng, "run-mkt") is None
