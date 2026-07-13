"""The workflow library: register, look up, intent-match and trigger (US-WFL-01).

A :class:`WorkflowLibrary` is a thin facade over the store's workflow records.
Workflows are *data* (precreated, generated or learned); this class never owns
business logic, only selection. ``trigger`` returns a run descriptor: it is the
seam where a durable Hatchet run is started in production. Keeping it a plain
dict means the core stays offline-safe and engine-agnostic (P4, P9).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, cast

from boltrig.models import InvocationContext, WorkflowDefinition, utcnow

from .interpreter import run_workflow_definition
from .snapshot import build_workflow_snapshot


def _visible_in_workspace(wf: WorkflowDefinition, active_workspace_id: str | None) -> bool:
    """Workspace visibility rule ([2026] VJS-COUNTY 8, D2).

    A workflow is visible to the caller when it is ORG-WIDE (``workspace_id`` is
    None - every existing workflow, so backward-compat) OR it belongs to the
    caller's ACTIVE workspace. A workflow scoped to a DIFFERENT workspace is never
    visible. With no active workspace (``None``) only org-wide workflows are visible
    - which is exactly the pre-workspace set. Scoping only NARROWS which workflows a
    workspace sees; it never widens authority (COUNTY 5).
    """
    return wf.workspace_id is None or wf.workspace_id == active_workspace_id


class WorkflowLibrary:
    """Selection facade over the store's :class:`WorkflowDefinition` records.

    An optional ``executor`` (the fleet's durable backbone from
    ``register_workers``) makes ``trigger`` actually enqueue a run; without one,
    ``trigger`` returns a plain descriptor (offline-safe, P9).

    An optional ``kernel`` enables ``execute`` (Round Seven): the generic
    interpreter that walks a stored definition's steps and dispatches each
    through the chokepoint. ``trigger`` stays the enqueue seam (in production the
    enqueued run's body calls ``execute``)."""

    def __init__(
        self, store: Any, executor: Any | None = None, *, kernel: Any | None = None
    ) -> None:
        self._store = store
        self._executor = executor
        self._kernel = kernel

    async def register(self, wf: WorkflowDefinition) -> None:
        """Persist (or replace) a workflow definition."""
        await self._store.upsert_workflow(wf)

    async def get(
        self, tenant: str, id: str, *, active_workspace_id: str | None = None
    ) -> WorkflowDefinition | None:
        """Return the workflow with ``id`` for ``tenant``, or ``None``.

        Workspace-scoped ([2026] VJS-COUNTY 8, D2): returns the workflow only when it
        is org-wide (``workspace_id`` None) OR belongs to the caller's active
        workspace; a workflow scoped to a DIFFERENT workspace is invisible (``None``,
        as if it did not exist - fail-closed). ``active_workspace_id`` defaults to
        None (no active workspace), which sees exactly the org-wide set (backward-
        compat).
        """
        for wf in await self._store.list_workflows(tenant):
            if wf.id == id and _visible_in_workspace(wf, active_workspace_id):
                return cast(WorkflowDefinition, wf)
        return None

    async def match(
        self,
        tenant: str,
        intent_tags: list[str],
        *,
        active_workspace_id: str | None = None,
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

        Workspace-scoped ([2026] VJS-COUNTY 8, D2): a candidate must be visible to
        the caller - org-wide (``workspace_id`` None) OR the caller's active
        workspace - so ``match`` never surfaces a workflow scoped to a DIFFERENT
        workspace. With no active workspace only org-wide workflows match (the pre-
        workspace set, byte-for-byte backward-compat). Scoping is applied BEFORE the
        reuse weighting, so it only narrows which workflows are reusable, never what
        any workflow may do (COUNTY 5).
        """
        wanted = set(intent_tags or [])
        if not wanted:
            return None
        weights = await self._reuse_weights(tenant)
        candidates = [
            wf
            for wf in await self._store.list_workflows(tenant)
            if wanted & set(wf.intent_tags) and _visible_in_workspace(wf, active_workspace_id)
        ]
        if not candidates:
            return None
        # Deterministic order: highest overlap, then highest reuse weight, then the
        # smallest id. The negations make ``min`` prefer larger overlap/weight while
        # ascending id still breaks the final tie.
        return cast(
            WorkflowDefinition,
            min(
                candidates,
                key=lambda wf: (
                    -len(wanted & set(wf.intent_tags)),
                    -weights.get(wf.id, 0.0),
                    wf.id,
                ),
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
        self,
        tenant: str,
        wf_id: str,
        inputs: dict[str, Any],
        *,
        active_workspace_id: str | None = None,
        context: InvocationContext | None = None,
    ) -> dict[str, Any]:
        """Start a workflow and return a run descriptor (Hatchet seam).

        The actual durable execution is owned by Hatchet; here we resolve the
        definition, mint a run id and hand back a descriptor the caller (or a
        Hatchet bridge) acts on. Raises ``LookupError`` if the workflow is
        unknown for the tenant (fail-closed, K-13). Workspace-scoped ([2026]
        VJS-COUNTY 8, D2): a workflow scoped to a DIFFERENT workspace is unknown to
        this caller (LookupError), so it can never be triggered cross-workspace.
        """
        wf = await self.get(tenant, wf_id, active_workspace_id=active_workspace_id)
        if wf is None:
            raise LookupError(f"unknown workflow '{wf_id}' for tenant '{tenant}'")
        durable = bool(self._executor and getattr(self._executor, "durable", False))
        run_id = self._executor.new_run_id() if self._executor is not None else uuid.uuid4().hex
        snapshot = build_workflow_snapshot(wf)
        descriptor = {
            "run_id": run_id,
            "tenant_id": tenant,
            "workflow_id": wf.id,
            "version": wf.version,
            "workflow_sha256": snapshot["sha256"],
            "source": wf.source.value,
            "engine": "hatchet" if durable else "local",
            "durable": durable,
            "status": "queued",
            "inputs": dict(inputs or {}),
            "queued_at": utcnow().isoformat(),
        }
        if self._executor is not None and context is not None:
            # The route/control path carries the authenticated context envelope
            # into the registered workflow task. Hatchet therefore executes the
            # definition durably; the local executor runs the exact same task body
            # inline. A bare library caller without a context retains the legacy
            # descriptor-only seam below rather than inventing authority.
            from boltrig.fleet.hatchet_app import (
                TASK_WORKFLOW_RUN,
                context_to_envelope,
            )

            queued_context = replace(context, run_id=run_id)
            engine_run_id = await self._executor.enqueue(
                TASK_WORKFLOW_RUN,
                {
                    "tenant": tenant,
                    "workflow_id": wf.id,
                    "workflow_snapshot": snapshot,
                    "inputs": dict(inputs or {}),
                    "ctx_envelope": context_to_envelope(queued_context),
                    "run_id": run_id,
                },
            )
            descriptor["engine_run_id"] = engine_run_id
        elif self._executor is not None:

            async def _describe() -> dict[str, Any]:
                return descriptor

            await self._executor.run_step(f"workflow:{wf.id}", _describe, run_id=run_id)
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
        # Scope resolution to the caller's active workspace ([2026] VJS-COUNTY 8, D2):
        # the InvocationContext already carries it (re-authorized every request), so a
        # workflow scoped to a different workspace is unknown here (LookupError).
        wf = await self.get(tenant, wf_id, active_workspace_id=context.workspace_id)
        if wf is None:
            raise LookupError(f"unknown workflow '{wf_id}' for tenant '{tenant}'")
        return await run_workflow_definition(
            self._kernel, wf, inputs, context, executor=self._executor
        )
