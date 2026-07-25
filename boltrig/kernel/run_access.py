"""Visibility checks for run-scoped event streams."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol

from boltrig.identity.rbac import departments_for
from boltrig.models import AuditEvent, WorkItem
from boltrig.models.work import work_item_run_id


class RunEventPrincipal(Protocol):
    tenant_id: str
    role: str
    scope: dict[str, Any]
    active_workspace_id: str | None


class RunEventStore(Protocol):
    async def audit_query(
        self, tenant_id: str, run_id: str | None = None, limit: int = 200
    ) -> list[AuditEvent]: ...

    async def get_work_item_by_run_id(
        self,
        tenant_id: str,
        run_id: str,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> WorkItem | None: ...

    async def list_work_items(
        self,
        tenant_id: str,
        status: Any = None,
        parent_id: str | None = None,
        departments: list[str] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> list[WorkItem]: ...

    async def list_run_items_scoped(
        self,
        tenant_id: str,
        *,
        departments: list[str] | None = None,
        workspace_id: str | None = None,
        owner: str | None = None,
        on_behalf_of: str | None = None,
        label: str | None = None,
        source: str | None = None,
        external_ref: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> list[WorkItem]: ...


def _workspace_visible(principal: RunEventPrincipal, row: AuditEvent) -> bool:
    active = principal.active_workspace_id
    return row.workspace_id is None or row.workspace_id == active


async def visible_work_item_by_run(
    store: RunEventStore, principal: RunEventPrincipal, run_id: str
) -> WorkItem | None:
    return await store.get_work_item_by_run_id(
        principal.tenant_id,
        run_id,
        workspace_id=principal.active_workspace_id,
        enforce_workspace=True,
    )


class AssertingPrincipal(Protocol):
    tenant_id: str
    subject: str


async def asserted_run_is_foreign(
    store: RunEventStore, principal: AssertingPrincipal, run_id: str | None
) -> bool:
    """True when the caller asserted a run id that belongs to somebody else.

    The write doors (``POST /v1/invoke``, ``POST /v1/spawn``) let the request
    body name the run its work executes under. That string is not decoration: it
    is the id the dispatcher publishes ``tool_call``/``tool_result`` frames
    against and the id ``_ask_user`` binds a new HITL to, so an unchecked one
    lets a same-tenant bystander write into a stranger's run. Every READ path
    already fences this (``visible_run_events``, ``cancel_run``,
    ``answer_hitl_question`` at ``hitl_http.py``, all on the work item's
    ``on_behalf_of``); the write doors did not, and this closes that asymmetry
    with the same predicate they use.

    Deliberately narrow, so it denies impersonation without breaking the run id's
    long-standing second job as a free correlation label:

    * A run with no work item is owned by nobody, so asserting it impersonates
      nobody. It also confers nothing: run-scoped credentials are additionally
      bound to their sealing owner (``kernel/credentials.py``), so an invented
      run id resolves no material.
    * A work item with no ``on_behalf_of`` is an internal/system item that no
      user owns; there is no owner to impersonate.

    Existence is checked WITHOUT the workspace fence on purpose. Scoping the
    lookup would report a run in another workspace as "no such run" and then
    admit it under the first allowance above, which is exactly backwards: the
    further away the caller is from the run, the less they should be trusted to
    name it.
    """
    if not run_id:
        return False
    item = await store.get_work_item_by_run_id(principal.tenant_id, run_id)
    if item is None or not item.on_behalf_of:
        return False
    return item.on_behalf_of != principal.subject


async def foreign_run_asserted(
    store: RunEventStore, principal: AssertingPrincipal, context: dict[str, Any]
) -> bool:
    """``asserted_run_is_foreign`` over both run ids a request body can carry.

    ``parent_run_id`` is the same claim one level up and is fenced identically:
    a spawn naming a stranger's run as its parent inherits that run's sealed
    adapter bearer (``fleet/spawn.py::_inherit_adapter_bearer``).
    """
    for key in ("run_id", "parent_run_id"):
        if await asserted_run_is_foreign(store, principal, context.get(key)):
            return True
    return False


async def visible_run_events(
    store: RunEventStore,
    principal: RunEventPrincipal,
    run_id: str,
    *,
    audit_limit: int = 1000,
) -> list[AuditEvent] | None:
    """Return run audit rows only when the caller may subscribe to its raw events."""
    rows = await store.audit_query(principal.tenant_id, run_id=run_id, limit=audit_limit)
    if not rows:
        return None

    departments = departments_for(principal.role, principal.scope)
    item = await store.get_work_item_by_run_id(principal.tenant_id, run_id)
    if item is not None:
        item = await visible_work_item_by_run(store, principal, run_id)
        if item is None:
            return None
        if departments is not None and item.owner_member not in set(departments):
            return None
    elif departments is not None:
        return None

    if any(not _workspace_visible(principal, row) for row in rows):
        return None

    return rows


async def visible_audit_tree_events(
    store: RunEventStore,
    principal: RunEventPrincipal,
    root_run_id: str,
    *,
    audit_limit: int = 10_000,
) -> list[AuditEvent] | None:
    """Return only rows the caller may use to reconstruct an execution tree.

    Tree assembly recursively follows parent links, so authorising only the root
    still leaks hidden descendants. Filter every source row with the same strict
    run-id department predicate as audit search, plus its workspace predicate,
    before any node or aggregate is built.
    """
    departments = departments_for(principal.role, principal.scope)
    root_item = await store.get_work_item_by_run_id(
        principal.tenant_id, root_run_id
    )
    if root_item is not None:
        root_item = await visible_work_item_by_run(store, principal, root_run_id)
        if root_item is None:
            return None
        if departments is not None and root_item.owner_member not in set(departments):
            return None
    elif departments is not None:
        return None

    all_items = await store.list_work_items(principal.tenant_id)
    visible_items = await store.list_work_items(
        principal.tenant_id,
        departments=departments,
        workspace_id=principal.active_workspace_id,
        enforce_workspace=True,
    )
    visible_item_ids = {item.id for item in visible_items}
    visible_work_ids = {work_item_run_id(item) for item in visible_items}
    hidden_work_ids = {
        work_item_run_id(item)
        for item in all_items
        if item.id not in visible_item_ids
    }

    def _run_visible(run_id: str) -> bool:
        if run_id in hidden_work_ids:
            return False
        return departments is None or run_id in visible_work_ids

    rows = await store.audit_query(principal.tenant_id, limit=audit_limit)
    visible = []
    for row in rows:
        if (
            row.run_id is None
            or not _run_visible(row.run_id)
            or not _workspace_visible(principal, row)
        ):
            continue
        if row.parent_run_id is not None and not _run_visible(row.parent_run_id):
            row = replace(row, parent_run_id=None)
        visible.append(row)
    # Preserve legitimate child-only trees, but never let a visible child revive a
    # root whose own tenant rows exist and were removed by the caller's scope.
    own_rows_exist = any(row.run_id == root_run_id for row in rows)
    known = any(row.run_id == root_run_id for row in visible)
    if not own_rows_exist:
        known = any(row.parent_run_id == root_run_id for row in visible)
    return visible if known else None


def build_run_topology(items: list[WorkItem], root_item: WorkItem) -> dict[str, Any]:
    """Assemble the subagent roster tree from an ALREADY-VISIBLE item slice.

    Parent links are WorkItem.parent_id (id -> parent id); each node exposes the
    durable run identity ``work_item_run_id``. Only items present in ``items``
    (the caller-scoped slice) can appear, so a hidden descendant is structurally
    absent and a hidden parent link is reported as ``parent_run_id: null``.
    Cycle-guarded like the audit-tree assembler.
    """
    by_id: dict[str, WorkItem] = {item.id: item for item in items}
    # Guarantee the root is present even if a clamp dropped it from the slice.
    by_id.setdefault(root_item.id, root_item)
    children_of: dict[str, list[str]] = {}
    for item in by_id.values():
        if item.parent_id is not None and item.parent_id in by_id:
            children_of.setdefault(item.parent_id, []).append(item.id)
    for kids in children_of.values():
        kids.sort()

    def node(item_id: str, seen: frozenset[str]) -> dict[str, Any]:
        item = by_id[item_id]
        base: dict[str, Any] = {
            "run_id": work_item_run_id(item),
            "work_item": item.id,
            "parent_run_id": (
                work_item_run_id(by_id[item.parent_id])
                if item.parent_id is not None and item.parent_id in by_id
                else None
            ),
            "member": item.owner_member,
            "task": item.intent,
            "status": item.status.value,
            "depth": item.depth,
            "source": item.source,
            "external_ref": item.source_id,
            "on_behalf_of": item.on_behalf_of,
            "attempts": item.attempts,
            "degraded": item.degraded,
        }
        if item_id in seen:
            return {**base, "children": [], "cycle": True}
        seen = seen | {item_id}
        base["children"] = [
            node(child_id, seen) for child_id in children_of.get(item_id, [])
        ]
        return base

    return {"root": node(root_item.id, frozenset())}


async def visible_run_topology(
    store: RunEventStore,
    principal: RunEventPrincipal,
    root_run_id: str,
    *,
    max_nodes: int = 5000,
) -> dict[str, Any] | None:
    """Reconstruct the durable subagent topology under a root run, or None.

    The root is gated exactly like visible_audit_tree_events (workspace-enforced
    resolve + department owner check); a hidden/unknown root returns None (404).

    The descendant slice is walked by the WorkItem parent/child link, level by
    level, with the SAME dept + enforced-workspace visibility the /v1/work
    children route uses (``store.list_work_items(parent_id=..., departments=...,
    workspace_id=..., enforce_workspace=True)``). A hidden descendant is
    structurally absent (its parent link is never followed for it), so the roster
    can never expose a run the caller could not see. ``max_nodes`` is a real node
    budget (BFS stops once reached) - NOT a single tenant-wide id-ordered page,
    which would silently clamp to MAX_WORK_PAGE and omit a root's real children.
    """
    departments = departments_for(principal.role, principal.scope)
    root_item = await store.get_work_item_by_run_id(principal.tenant_id, root_run_id)
    if root_item is None:
        return None
    root_item = await visible_work_item_by_run(store, principal, root_run_id)
    if root_item is None:
        return None
    if departments is not None and root_item.owner_member not in set(departments):
        return None

    # BFS the root's SUBTREE by parent link. Each level is fetched under the
    # caller's dept + enforced-workspace scope; the ``collected`` set is the
    # cycle/DAG re-entry guard, and the node budget bounds an adversarial forest.
    collected: dict[str, WorkItem] = {root_item.id: root_item}
    frontier: list[str] = [root_item.id]
    while frontier and len(collected) < max_nodes:
        parent_id = frontier.pop()
        children = await store.list_work_items(
            principal.tenant_id,
            parent_id=parent_id,
            departments=departments,
            workspace_id=principal.active_workspace_id,
            enforce_workspace=True,
            limit=max_nodes,
        )
        for child in children:
            if child.id in collected:
                continue
            collected[child.id] = child
            frontier.append(child.id)
            if len(collected) >= max_nodes:
                break

    return build_run_topology(list(collected.values()), root_item)
