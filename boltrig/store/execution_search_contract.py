"""Store contract for tenant- and workspace-scoped execution search."""

from __future__ import annotations

from typing import Protocol

from boltrig.models import WorkItem


class ExecutionSearchContract(Protocol):
    # The same department + enforced-workspace and hidden-wins RunScope as the
    # run list is applied before literal text matching and the bounded LIMIT.
    # Callers may request limit+1 to derive a safe ``more`` marker.
    async def search_execution_items_scoped(
        self,
        tenant_id: str,
        query: str,
        *,
        departments: list[str] | None = None,
        workspace_id: str | None = None,
        limit: int,
    ) -> list[WorkItem]: ...
