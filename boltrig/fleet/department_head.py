"""The tier-2 permanent agent: a Department Head (US-FLT-02, US-EXE-04).

A department head receives a ``WorkItem`` the Chief of Staff routed to it,
decomposes it into sub-tasks, and spawns an ephemeral child per sub-task through
the ``Spawner``. It enforces the per-step fan-out caps that stop a runaway tree
(US-EXE-04): too many children in one step, or too many newly-discovered work
items, is rejected and escalated (a HITL escalation) rather than executed. It is
a thin reasoning seam with a deterministic decomposition fallback (P9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from boltrig.models import HITLType, InvocationContext, Urgency, WorkItem

if TYPE_CHECKING:  # type-only seams (no runtime import cost / no cycle)
    from .runtime import Runtime
    from .spawn import Spawner


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
        max_children_per_step: int = 8,
        max_new_items_per_step: int = 16,
    ) -> None:
        self.name = name
        self.domain_skills = list(domain_skills)
        self.queue_sources = list(queue_sources)
        self.spawn_budget = spawn_budget  # total children this head may spawn
        self._spawner = spawner
        self._runtime = runtime
        self.max_children_per_step = max_children_per_step
        self.max_new_items_per_step = max_new_items_per_step
        self._spawned = 0  # running total against ``spawn_budget``

    async def handle(
        self, work_item: WorkItem, context: InvocationContext, *, prefer: dict | None = None
    ) -> dict[str, Any]:
        """Decompose and spawn children for ``work_item`` (one step, US-FLT-02).

        Enforces ``max_children_per_step`` and ``spawn_budget`` up front, and
        ``max_new_items_per_step`` as children report follow-on work; on a cap
        breach it escalates (HITL) and returns a structured escalation instead of
        spawning the over-cap fan-out (US-EXE-04).
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
        remaining_budget = self.spawn_budget - self._spawned
        if len(subtasks) > remaining_budget:
            return await self._escalate(
                work_item, context,
                reason="spawn_budget_exhausted",
                detail=f"{len(subtasks)} children > remaining budget {remaining_budget}",
            )

        children: list[dict[str, Any]] = []
        new_items: list[Any] = []
        for subtask in subtasks:
            child = await self._spawner.spawn(
                tenant_id=work_item.tenant_id,
                task=subtask,
                skills=self.domain_skills,
                prefer=prefer,
                context=context,
            )
            self._spawned += 1
            children.append(child)
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
                pass
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
