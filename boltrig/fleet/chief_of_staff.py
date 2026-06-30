"""The tier-1 permanent agent: the Chief of Staff (US-FLT-01).

The Chief of Staff holds the global view of work for a tenant and routes each
normalised ``WorkItem`` to the department head best placed to own it. It is a
thin reasoning-loop seam: it *can* use a ``Runtime`` to make the routing call,
but always has a deterministic fallback (route by source / intent keyword) so it
is fully functional offline (P9). It never executes work itself - it delegates.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from boltrig.models import InvocationContext, WorkItem

if TYPE_CHECKING:  # type-only seams (no runtime import cost / no cycle)
    from boltrig.kernel import Kernel

    from .runtime import Runtime


@dataclass
class Department:
    """A department the Chief of Staff can route to (configuration, not code).

    * ``domain_skills`` - skill patterns the department owns (e.g. ``finance/*``).
    * ``queue_sources`` - source channels it owns (``jira``, ``monday``, ...).
    * ``intent_keywords`` - words in a work item's intent that map to it.
    """

    name: str
    domain_skills: list[str] = field(default_factory=list)
    queue_sources: list[str] = field(default_factory=list)
    intent_keywords: list[str] = field(default_factory=list)


class ChiefOfStaff:
    """Tier-1 router with a global, source-agnostic view of work (US-FLT-01)."""

    def __init__(
        self,
        kernel: Kernel,
        departments: list[Department],
        *,
        runtime: Runtime | None = None,
        default_department: str | None = None,
        departments_provider: Callable[[], list[Department]] | None = None,
    ) -> None:
        self._kernel = kernel
        self._departments = list(departments)
        self._runtime = runtime
        self._default = default_department or (
            departments[0].name if departments else "general"
        )
        # Control-plane live-reload (Round Seven gap 2.1): when a provider is
        # given, the current department set is re-read on every route, so an
        # admin/manifest edit takes effect WITHOUT reconstructing the router. The
        # provider must never raise the routing path - it falls back to the
        # construction-time list on any failure (P9).
        self._departments_provider = departments_provider

    def _current_departments(self) -> list[Department]:
        """The live department set (re-read per call when a provider is wired)."""
        if self._departments_provider is None:
            return self._departments
        try:
            current = self._departments_provider()
        except Exception:  # config read must never crash routing (P9)
            return self._departments
        return list(current) if current else self._departments

    async def global_view(self, tenant_id: str) -> list[WorkItem]:
        """The maintained global view: all work items for the tenant (US-FLT-01)."""
        return await self._kernel.store.list_work_items(tenant_id)

    async def route(
        self, work_item: WorkItem, context: InvocationContext | None = None
    ) -> str:
        """Return the department name that should own ``work_item``.

        Tries the reasoning runtime first (if configured and it names a known
        department); otherwise falls back to deterministic source/keyword
        routing. Never raises - an unmatched item routes to the default.
        """
        if self._runtime is not None:
            chosen = await self._route_with_runtime(work_item, context)
            if chosen is not None:
                return chosen
        return self._route_deterministic(work_item)

    # --- internals ------------------------------------------------------------
    async def _route_with_runtime(
        self, work_item: WorkItem, context: InvocationContext | None
    ) -> str | None:
        """Ask the runtime for a department; accept only a known name."""
        ctx = context or InvocationContext(
            tenant_id=work_item.tenant_id, actor="chief-of-staff", actor_tier="tier1"
        )
        names = [d.name for d in self._current_departments()]
        prompt = (
            "Route this work item to exactly one department.\n"
            f"Departments: {', '.join(names)}\n"
            f"Source: {work_item.source}\nIntent: {work_item.intent}\n"
            "Reply with the department name."
        )
        try:
            result = await self._runtime.run(prompt, ctx, tools=[])
        except Exception:  # routing must never crash the loop (P9)
            return None
        candidate = _extract_department(result.output, result.summary)
        if candidate and candidate in names:
            return candidate
        return None

    def _route_deterministic(self, work_item: WorkItem) -> str:
        """Deterministic fallback: source channel, then intent keyword."""
        departments = self._current_departments()
        for dept in departments:
            if work_item.source in dept.queue_sources:
                return dept.name
        intent = (work_item.intent or "").lower()
        for dept in departments:
            if any(kw.lower() in intent for kw in dept.intent_keywords):
                return dept.name
        return self._default


def _extract_department(output: dict[str, Any], summary: str) -> str | None:
    """Pull a department name from a runtime result (structured or free text)."""
    if isinstance(output, dict):
        value = output.get("department") or output.get("route")
        if isinstance(value, str) and value.strip():
            return value.strip()
        text = output.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip().splitlines()[0].strip()
    if summary:
        return summary.strip().splitlines()[0].strip()
    return None
