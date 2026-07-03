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

from boltrig.models import InvocationContext, WorkflowDefinition, utcnow

from .interpreter import run_workflow_definition


class WorkflowLibrary:
    """Selection facade over the store's :class:`WorkflowDefinition` records.

    An optional ``executor`` (the fleet's durable backbone from
    ``register_workers``) makes ``trigger`` actually enqueue a run; without one,
    ``trigger`` returns a plain descriptor (offline-safe, P9).

    An optional ``kernel`` enables ``execute`` (Round Seven): the generic
    interpreter that walks a stored definition's steps and dispatches each
    through the chokepoint. ``trigger`` stays the enqueue seam (in production the
    enqueued run's body calls ``execute``)."""

    def __init__(self, store: Any, executor: Any | None = None, *, kernel: Any | None = None) -> None:
        self._store = store
        self._executor = executor
        self._kernel = kernel

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
        """Best workflow by intent-tag overlap, promotion-aware (US-WFL-01/08).

        Picks the definition sharing the most ``intent_tags`` with the request.
        Intent overlap stays the PRIMARY key (a promoted workflow can never be
        surfaced for an intent it does not match); among equally-matching
        workflows the eval-gated reuse weight is the tiebreak, so a PROMOTED
        workflow is preferred and a DEMOTED one deferred; workflow id is the final,
        deterministic tiebreak. Returns ``None`` when no workflow overlaps at all
        (a generated workflow is the fallback path).

        The reuse weight is RANKING only ([2026] VJS-COUNTY 5): it changes which
        equally-relevant workflow is reused, never what any workflow may do. With
        no promotion records every weight is 0, so behaviour is unchanged.

        The learning-loop retrieval half, wired by the engine plan Phase 3
        (``learn_from_success`` + ``match``); a reserved API.
        """
        wanted = set(intent_tags or [])
        if not wanted:
            return None
        weights = await self._reuse_weights(tenant)
        candidates = [
            wf for wf in await self._store.list_workflows(tenant)
            if wanted & set(wf.intent_tags)
        ]
        if not candidates:
            return None
        # Deterministic order: highest overlap, then highest reuse weight, then the
        # smallest id. The negations make ``min`` prefer larger overlap/weight while
        # ascending id still breaks the final tie.
        return min(
            candidates,
            key=lambda wf: (
                -len(wanted & set(wf.intent_tags)),
                -weights.get(wf.id, 0.0),
                wf.id,
            ),
        )

    async def _reuse_weights(self, tenant: str) -> dict[str, float]:
        """Map workflow id -> bounded reuse weight (ranking only); {} on any gap.

        Best-effort: a store without the promotion methods (or a read failure) is
        treated as no promotions - the matcher then behaves exactly as before (P9).
        """
        from .promotion import reuse_weight  # local import: avoid a load cycle

        lister = getattr(self._store, "list_workflow_promotions", None)
        if lister is None:
            return {}
        try:
            promotions = await lister(tenant)
        except Exception:  # a promotion-read failure never breaks selection (P9)
            return {}
        return {p.workflow_id: reuse_weight(p) for p in promotions}

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
        durable = bool(self._executor and getattr(self._executor, "durable", False))
        run_id = (
            self._executor.new_run_id() if self._executor is not None else uuid.uuid4().hex
        )
        descriptor = {
            "run_id": run_id,
            "tenant_id": tenant,
            "workflow_id": wf.id,
            "version": wf.version,
            "source": wf.source.value,
            "engine": "hatchet" if durable else "local",
            "durable": durable,
            "status": "queued",
            "inputs": dict(inputs or {}),
            "queued_at": utcnow().isoformat(),
        }
        if self._executor is not None:
            # enqueue through the backbone so the run boundary is recorded
            # (durable under Hatchet; in-process under the local fallback).
            async def _enqueue() -> dict[str, Any]:
                return descriptor

            await self._executor.run_step(
                f"workflow:{wf.id}", _enqueue, run_id=run_id
            )
        return descriptor

    async def execute(
        self, tenant: str, wf_id: str, inputs: dict[str, Any], context: InvocationContext
    ) -> dict[str, Any]:
        """Interpret a stored workflow: run its steps through the chokepoint.

        Resolves the definition, then hands it to the generic interpreter, which
        walks the steps in dependency order and dispatches each as its own
        durable boundary via ``kernel.invoke`` (Round Seven, control-plane gap 3).
        Raises ``LookupError`` if the workflow is unknown (fail-closed). Requires
        a ``kernel`` (wired at construction); without one this is a config error.
        """
        if self._kernel is None:
            raise RuntimeError("WorkflowLibrary.execute requires a kernel")
        wf = await self.get(tenant, wf_id)
        if wf is None:
            raise LookupError(f"unknown workflow '{wf_id}' for tenant '{tenant}'")
        return await run_workflow_definition(
            self._kernel, wf, inputs, context, executor=self._executor
        )
