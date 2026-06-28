"""Source-agnostic work-item persistence and status transitions (P10).

:class:`WorkItemStore` is a thin facade over the kernel ``Store`` so the fleet
reads and writes work items without knowing which backend (in-memory, Postgres)
is underneath, and without ever touching a source system directly. It also owns
the small status-transition guard and the per-step discovery cap that bounds
runaway expansion (US-WRK-04, US-EXE-04).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from nankle.models import WorkItem, WorkStatus
from nankle.work.queue import QueueAdapter

# The legal status transitions (a small guard, not a full state machine). DONE is
# terminal; FAILED may be retried back to PENDING.
_TRANSITIONS: dict[WorkStatus, set[WorkStatus]] = {
    WorkStatus.PENDING: {
        WorkStatus.IN_FLIGHT, WorkStatus.BLOCKED, WorkStatus.AWAITING_HUMAN,
        WorkStatus.FAILED,
    },
    WorkStatus.IN_FLIGHT: {
        WorkStatus.BLOCKED, WorkStatus.AWAITING_HUMAN, WorkStatus.DONE,
        WorkStatus.FAILED,
    },
    WorkStatus.BLOCKED: {WorkStatus.PENDING, WorkStatus.IN_FLIGHT, WorkStatus.FAILED},
    WorkStatus.AWAITING_HUMAN: {
        WorkStatus.IN_FLIGHT, WorkStatus.BLOCKED, WorkStatus.DONE, WorkStatus.FAILED,
    },
    WorkStatus.DONE: set(),
    WorkStatus.FAILED: {WorkStatus.PENDING, WorkStatus.IN_FLIGHT},
}


class WorkItemStore:
    """CRUD + status transitions for work items over the kernel store (P10)."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def create(self, item: WorkItem) -> WorkItem:
        """Persist a new work item."""
        await self._store.create_work_item(item)
        return item

    async def get(self, tenant: str, item_id: str) -> WorkItem | None:
        """Fetch one work item, tenant-scoped (SEC-08)."""
        return await self._store.get_work_item(tenant, item_id)

    async def list(
        self,
        tenant: str,
        status: WorkStatus | None = None,
        parent_id: str | None = None,
    ) -> list[WorkItem]:
        """List work items, optionally filtered by status and/or parent."""
        return await self._store.list_work_items(tenant, status, parent_id)

    async def update(self, item: WorkItem) -> WorkItem:
        """Persist changes to an existing work item."""
        await self._store.update_work_item(item)
        return item

    async def transition(
        self, tenant: str, item_id: str, new_status: WorkStatus
    ) -> WorkItem:
        """Move a work item to ``new_status`` if the transition is legal.

        Raises ``LookupError`` if the item is missing and ``ValueError`` if the
        transition is not permitted from the current status.
        """
        item = await self._store.get_work_item(tenant, item_id)
        if item is None:
            raise LookupError(f"unknown work item '{item_id}' for tenant '{tenant}'")
        if new_status != item.status and new_status not in _TRANSITIONS.get(
            item.status, set()
        ):
            raise ValueError(
                f"illegal transition {item.status.value} -> {new_status.value}"
            )
        updated = replace(item, status=new_status)
        await self._store.update_work_item(updated)
        return updated

    async def write_back_discovered(
        self,
        queue_adapter: QueueAdapter,
        parent_id: str,
        items: list[WorkItem],
        cap: int,
    ) -> list[WorkItem]:
        """Persist discovered child items and write them back, capped (US-WRK-04).

        A single step may surface new work; ``cap`` bounds how many are accepted
        per step so a divergent run cannot expand without limit (US-EXE-04). The
        accepted items are stamped with ``parent_id``, persisted to the kernel
        store, and written back to the source via ``queue_adapter``. Returns the
        accepted (capped) list; any overflow is dropped.
        """
        accepted: list[WorkItem] = []
        for item in list(items)[: max(0, cap)]:
            child = item if item.parent_id == parent_id else replace(
                item, parent_id=parent_id
            )
            await self._store.create_work_item(child)
            accepted.append(child)
        await queue_adapter.write_back(parent_id, accepted)
        return accepted
