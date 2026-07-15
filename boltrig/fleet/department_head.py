"""The tier-2 permanent agent: a Department Head (US-FLT-02, US-EXE-04).

A department head receives a ``WorkItem`` the Chief of Staff routed to it,
decomposes it into sub-tasks, and spawns an ephemeral child per sub-task through
the ``Spawner``. It enforces the per-step fan-out caps that stop a runaway tree
(US-EXE-04): too many children in one step, or too many newly-discovered work
items, is rejected and escalated (a HITL escalation) rather than executed. The
total-tree budget is a store-backed atomic counter shared across worker
processes (US-EXE-07), keyed by the tree's ROOT work-item id, so two pumps over
one store can never jointly exceed it. Children run bounded-parallel under a
semaphore of ``max_children_per_step``; a failed child becomes a failed-child
record, never an exception past the join (D8). It is a thin reasoning seam with
a deterministic decomposition fallback (P9).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from boltrig.models import HITLType, InvocationContext, Urgency, WorkItem, WorkStatus

if TYPE_CHECKING:  # type-only seams (no runtime import cost / no cycle)
    from .runtime import Runtime
    from .spawn import Spawner

log = logging.getLogger("boltrig.fleet.department_head")


async def tree_root_id(store: Any, item: WorkItem) -> str:
    """The id of ``item``'s tree root, walking the parent chain (cycle-safe).

    The root id keys the shared fan-out counter (US-EXE-07): every step in one
    delegation tree draws from the same budget. With no store, the item is its
    own root.
    """
    if store is None:
        return item.id
    current = item
    seen = {item.id}
    while current.parent_id and current.parent_id not in seen:
        parent = await store.get_work_item(item.tenant_id, current.parent_id)
        if parent is None:
            break
        seen.add(parent.id)
        current = parent
    return current.id


class DepartmentHead:
    """Tier-2 agent: decompose a work item and spawn bounded children (US-FLT-02)."""

    def __init__(
        self,
        name: str,
        domain_skills: list[str],
        queue_sources: list[str],
        spawn_budget: int,
        *,
        spawner: Spawner,
        runtime: Runtime | None = None,
        store: Any = None,
        max_children_per_step: int = 8,
        max_new_items_per_step: int = 16,
    ) -> None:
        self.name = name
        self.domain_skills = list(domain_skills)
        self.queue_sources = list(queue_sources)
        self.spawn_budget = spawn_budget  # total children this head's trees may spawn
        self._spawner = spawner
        self._runtime = runtime
        # The budget counter's home (US-EXE-07): the shared store's atomic CAS.
        # Falls back to the spawner's kernel store; with neither, a per-process
        # counter keeps the cap for storeless stubs (P9).
        self._store = store or getattr(getattr(spawner, "_kernel", None), "store", None)
        self.max_children_per_step = max_children_per_step
        self.max_new_items_per_step = max_new_items_per_step
        self._spawned = 0  # per-process fallback only (no store wired)

    async def handle(
        self,
        work_item: WorkItem,
        context: InvocationContext,
        *,
        prefer: dict | None = None,
        tree_id: str | None = None,
    ) -> dict[str, Any]:
        """Decompose and spawn children for ``work_item`` (one step, US-FLT-02).

        Enforces ``max_children_per_step`` and the store-backed ``spawn_budget``
        (atomic per-tree CAS, US-EXE-07) up front, and ``max_new_items_per_step``
        as children report follow-on work; on a cap breach it escalates (HITL)
        and returns a structured escalation instead of spawning the over-cap
        fan-out (US-EXE-04). Children run bounded-parallel; a child failure is
        captured as a failed-child record, never raised past the join (D8).
        """
        prefer = dict(prefer or {})
        prefer.setdefault("department", self.name)
        subtasks = await self._decompose(work_item, context)

        # US-EXE-04: reject/escalate when the step's fan-out exceeds the cap.
        if len(subtasks) > self.max_children_per_step:
            return await self._escalate(
                work_item, context,
                reason="max_children_per_step",
                detail=f"{len(subtasks)} children > cap {self.max_children_per_step}",
            )
        # US-EXE-07: reserve the whole step against the shared per-tree budget
        # atomically, so concurrent workers can never jointly exceed it.
        tree = tree_id or await tree_root_id(self._store, work_item)
        if not await self._reserve_budget(work_item.tenant_id, tree, len(subtasks)):
            return await self._escalate(
                work_item, context,
                reason="spawn_budget_exhausted",
                detail=(
                    f"{len(subtasks)} children would exceed spawn budget "
                    f"{self.spawn_budget} for tree {tree}"
                ),
            )

        # D8: bounded-parallel children under a per-step semaphore; every result
        # (including a failure record) is captured, and the join never raises.
        semaphore = asyncio.Semaphore(self.max_children_per_step)
        children = list(await asyncio.gather(
            *(self._run_child(work_item, s, prefer, context, semaphore) for s in subtasks)
        ))

        new_items: list[Any] = []
        for child in children:
            new_items.extend(child.get("new_work_items", []))
        if len(new_items) > self.max_new_items_per_step:
            escalation = await self._escalate(
                work_item, context,
                reason="max_new_items_per_step",
                detail=f"{len(new_items)} new items > cap {self.max_new_items_per_step}",
            )
            escalation["children"] = children
            return escalation

        return {
            "status": "ok",
            "department": self.name,
            "work_item_id": work_item.id,
            "children": children,
            "spawned": len(children),
            "new_work_items": new_items,
        }

    # --- internals ------------------------------------------------------------
    async def _reserve_budget(self, tenant_id: str, tree_id: str, n: int) -> bool:
        """Reserve ``n`` spawns against the tree budget - atomic CAS (US-EXE-07)."""
        if self._store is not None:
            return await self._store.try_increment_fanout(
                tenant_id, tree_id, "spawned", n, self.spawn_budget
            )
        # storeless stub fallback: the old per-process counter (P9)
        if self._spawned + n > self.spawn_budget:
            return False
        self._spawned += n
        return True

    async def _run_child(
        self,
        work_item: WorkItem,
        subtask: str,
        prefer: dict[str, Any],
        context: InvocationContext,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        """Run one child: a child WorkItem records it in the tree (US-FLT-06),
        the spawn does the work, and any exception becomes a failed-child record
        marked degraded - honesty over a raised join (D8, US-FLT-07)."""
        child_item = await self._create_child_item(work_item, subtask)
        async with semaphore:
            try:
                result = await self._spawner.spawn(
                    tenant_id=work_item.tenant_id,
                    task=subtask,
                    skills=self.domain_skills,
                    prefer=prefer,
                    context=context,
                )
            except Exception as exc:  # captured, never raised past the join (D8)
                result = {
                    "status": "error",
                    "degraded": True,
                    "error": type(exc).__name__,
                    "summary": f"child failed: {type(exc).__name__}",
                    "output": {},
                    "new_work_items": [],
                }
        if child_item is not None:
            child_item.hatchet_run_id = result.get("run_id")
            child_item.status = (
                WorkStatus.FAILED if result.get("status") == "error" else WorkStatus.DONE
            )
            child_item.degraded = bool(result.get("degraded"))
            child_item.result = result
            await self._store.update_work_item(child_item)
            result = dict(result)
            result["work_item_id"] = child_item.id
        return result

    async def _create_child_item(
        self, parent: WorkItem, subtask: str
    ) -> WorkItem | None:
        """Persist the sub-task as a child WorkItem so the delegation tree is
        visible in the store (US-FLT-06). Created IN_FLIGHT - this step owns it,
        the pump must never claim it. Storeless stubs skip the record."""
        if self._store is None:
            return None
        child = WorkItem(
            id=uuid.uuid4().hex,
            tenant_id=parent.tenant_id,
            source="internal",
            intent=subtask,
            confidence=parent.confidence,
            convergent=parent.convergent,
            status=WorkStatus.IN_FLIGHT,
            parent_id=parent.id,
            owner_member=self.name,
            depth=parent.depth + 1,
            on_behalf_of=parent.on_behalf_of,
            workspace_id=parent.workspace_id,
        )
        await self._store.create_work_item(child)
        return child

    async def _decompose(
        self, work_item: WorkItem, context: InvocationContext
    ) -> list[str]:
        """Break a work item into sub-task strings (reasoning, then fallback)."""
        if self._runtime is not None:
            try:
                result = await self._runtime.run(
                    self._decompose_prompt(work_item), context, tools=[]
                )
                tasks = _extract_subtasks(result.output)
                if tasks:
                    return tasks
            except Exception:  # decomposition must never crash the loop (P9)
                log.debug(
                    "decomposition failed for %s; using fallback",
                    work_item.id, exc_info=True,
                )
        # Deterministic fallback: a single sub-task carrying the item's intent.
        return [work_item.intent]

    def _decompose_prompt(self, work_item: WorkItem) -> str:
        return (
            f"You are the {self.name} department head. Decompose this work item "
            "into a short list of independent sub-tasks.\n"
            f"Intent: {work_item.intent}\nSource: {work_item.source}\n"
            "Reply with one sub-task per line."
        )

    async def _escalate(
        self,
        work_item: WorkItem,
        context: InvocationContext,
        *,
        reason: str,
        detail: str,
    ) -> dict[str, Any]:
        """Raise a HITL escalation for an over-cap step and return its record."""
        request = await self._spawner._kernel.hitl.create(
            tenant_id=work_item.tenant_id,
            run_id=context.run_id or "",
            type=HITLType.ESCALATION,
            question=f"{self.name}: step exceeded a fan-out cap ({reason}).",
            context=detail,
            urgency=Urgency.ASYNC,
            work_item_id=work_item.id,
            requested_by=self.name,
            requested_on_behalf_of=work_item.on_behalf_of,
            workspace_id=context.workspace_id,
            department_scope=[self.name],
        )
        return {
            "status": "escalated",
            "department": self.name,
            "work_item_id": work_item.id,
            "reason": reason,
            "detail": detail,
            "hitl_request_id": request.id,
            "children": [],
            "new_work_items": [],
        }


def _extract_subtasks(output: dict[str, Any]) -> list[str]:
    """Pull sub-task strings from a runtime result (structured or line-based)."""
    if isinstance(output, dict):
        tasks = output.get("subtasks") or output.get("tasks")
        if isinstance(tasks, (list, tuple)):
            return [str(t).strip() for t in tasks if str(t).strip()]
        text = output.get("text")
        if isinstance(text, str):
            return [line.strip() for line in text.splitlines() if line.strip()]
    return []
