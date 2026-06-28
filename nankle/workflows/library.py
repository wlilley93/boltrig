"""The workflow library: register, look up, intent-match and trigger (US-WFL-01).

A :class:`WorkflowLibrary` is a thin facade over the store's workflow records.
Workflows are *data* (precreated, generated or learned); this class never owns
business logic, only selection. ``trigger`` returns a run descriptor: it is the
seam where a durable Hatchet run is started in production. Keeping it a plain
dict means the core stays offline-safe and engine-agnostic (P4, P9).
"""

from __future__ import annotations

import uuid
from typing import Any

from nankle.models import WorkflowDefinition, utcnow


class WorkflowLibrary:
    """Selection facade over the store's :class:`WorkflowDefinition` records."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def register(self, wf: WorkflowDefinition) -> None:
        """Persist (or replace) a workflow definition."""
        await self._store.upsert_workflow(wf)

    async def get(self, tenant: str, id: str) -> WorkflowDefinition | None:
        """Return the workflow with ``id`` for ``tenant``, or ``None``."""
        for wf in await self._store.list_workflows(tenant):
            if wf.id == id:
                return wf
        return None

    async def match(
        self, tenant: str, intent_tags: list[str]
    ) -> WorkflowDefinition | None:
        """Best workflow by intent-tag overlap (US-WFL-01).

        Picks the definition sharing the most ``intent_tags`` with the request.
        Ties break deterministically on workflow id. Returns ``None`` when no
        workflow overlaps at all (a generated workflow is the fallback path).
        """
        wanted = set(intent_tags or [])
        if not wanted:
            return None
        best: WorkflowDefinition | None = None
        best_score = 0
        for wf in await self._store.list_workflows(tenant):
            score = len(wanted & set(wf.intent_tags))
            if score > best_score or (
                score == best_score and best is not None and wf.id < best.id
            ):
                if score > 0:
                    best, best_score = wf, score
        return best

    async def trigger(
        self, tenant: str, wf_id: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Start a workflow and return a run descriptor (Hatchet seam).

        The actual durable execution is owned by Hatchet; here we resolve the
        definition, mint a run id and hand back a descriptor the caller (or a
        Hatchet bridge) acts on. Raises ``LookupError`` if the workflow is
        unknown for the tenant (fail-closed, K-13).
        """
        wf = await self.get(tenant, wf_id)
        if wf is None:
            raise LookupError(f"unknown workflow '{wf_id}' for tenant '{tenant}'")
        return {
            "run_id": uuid.uuid4().hex,
            "tenant_id": tenant,
            "workflow_id": wf.id,
            "version": wf.version,
            "source": wf.source.value,
            "engine": "hatchet",
            "status": "queued",
            "inputs": dict(inputs or {}),
            "queued_at": utcnow().isoformat(),
        }
