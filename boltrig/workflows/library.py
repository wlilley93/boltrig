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


def _archived(wf: WorkflowDefinition) -> bool:
    lifecycle = wf.definition.get("_boltrig_lifecycle")
    return isinstance(lifecycle, dict) and lifecycle.get("status") == "archived"


# Draft rows (chat-first authoring) live under this reserved id prefix and are
# working copies, never runnable: excluded from get/match/trigger/execute so a
# draft can never be selected, matched, or run. Kept as a string literal here
# to avoid importing config into the workflows package (layering).
_DRAFT_ID_PREFIX = "__draft__:"


def _is_draft(wf: WorkflowDefinition) -> bool:
    return wf.id.startswith(_DRAFT_ID_PREFIX)


def _run_id(executor: Any | None, requested: str | None) -> str:
    if requested:
        return requested
    return executor.new_run_id() if executor is not None else uuid.uuid4().hex


def _snapshot(wf: WorkflowDefinition, expected_sha256: str | None) -> dict[str, Any]:
    snapshot = build_workflow_snapshot(wf)
    if expected_sha256 is not None and snapshot["sha256"] != expected_sha256:
        raise RuntimeError("workflow_snapshot_changed")
    return snapshot


class WorkflowLibrary:
    """Selection facade over the store's :class:`WorkflowDefinition` records.

    An optional ``executor`` (the fleet's durable backbone from
    ``register_workers``) makes ``trigger`` actually enqueue a run; without one,
    ``trigger`` returns a plain descriptor (offline-safe, P9).

    An optional ``kernel`` enables ``execute`` (Round Seven): the generic
    interpreter that walks a stored definition's steps and dispatches each
    through the chokepoint. ``trigger`` stays the enqueue seam; the enqueued
    run's body (``run_workflow_body``) combines the per-step executor boundary
    with checkpoint-resume, while ``execute`` stays the single-shot route path
    (executor boundary, no store)."""

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
            if wf.id == id and not _is_draft(wf) and _visible_in_workspace(wf, active_workspace_id):
                return cast(WorkflowDefinition, wf)
        return None

    async def match(
        self,
        tenant: str,
        intent_tags: list[str],
        *,
        active_workspace_id: str | None = None,
    ) -> WorkflowDefinition | None:
        """Best workflow by intent-tag overlap (US-WFL-01).

        Picks the definition sharing the most ``intent_tags`` with the request;
        workflow id is the deterministic tiebreak among equal overlaps. Returns
        ``None`` when no workflow overlaps at all (a generated workflow is the
        fallback path).

        NOT REACHABLE FROM PRODUCTION. ``match``'s only caller is
        ``select_or_generate_workflow``, which no production entry point calls:
        production selects a workflow by explicit id, never by intent. It survives
        under the waiver in [2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001,
        against the Principal question of whether the pump's routing path should
        consult the library by intent (D8), and retires on expiry without an answer.

        A second, reuse-weight sort key used to sit between overlap and id. It is
        gone with the rest of the promotion subsystem (that order, D3): the value it
        ranked by was written by nothing a production path ran.

        Workspace-scoped ([2026] VJS-COUNTY 8, D2): a candidate must be visible to
        the caller - org-wide (``workspace_id`` None) OR the caller's active
        workspace - so ``match`` never surfaces a workflow scoped to a DIFFERENT
        workspace. With no active workspace only org-wide workflows match (the pre-
        workspace set, byte-for-byte backward-compat). Scoping only narrows which
        workflows are reusable, never what any workflow may do (COUNTY 5).
        """
        wanted = set(intent_tags or [])
        if not wanted:
            return None
        candidates = [
            wf
            for wf in await self._store.list_workflows(tenant)
            if (
                wanted & set(wf.intent_tags)
                and not _is_draft(wf)
                and _visible_in_workspace(wf, active_workspace_id)
                and not _archived(wf)
            )
        ]
        if not candidates:
            return None
        # Deterministic order: highest overlap, then the smallest id. The negation
        # makes ``min`` prefer larger overlap while ascending id still breaks the tie.
        return cast(
            WorkflowDefinition,
            min(
                candidates,
                key=lambda wf: (-len(wanted & set(wf.intent_tags)), wf.id),
            ),
        )

    async def trigger(
        self,
        tenant: str,
        wf_id: str,
        inputs: dict[str, Any],
        *,
        active_workspace_id: str | None = None,
        context: InvocationContext | None = None,
        run_id: str | None = None,
        expected_workflow_sha256: str | None = None,
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
        if _archived(wf):
            raise PermissionError("workflow_archived")
        durable = bool(self._executor and getattr(self._executor, "durable", False))
        run_id = _run_id(self._executor, run_id)
        snapshot = _snapshot(wf, expected_workflow_sha256)
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
            # into the registered workflow task. The engine (Hatchet, or the
            # local executor inline) owns the run as ONE durable task, and the
            # task body wires BOTH durability seams: each step dispatches
            # inside an executor.run_step boundary AND checkpoint-resume is
            # active (with per-step idempotency keys closing the
            # completed-but-uncheckpointed crash window). What the boundary
            # itself guarantees depends on the executor - see
            # HatchetExecutor.run_step's honest docstring. A bare library
            # caller without a context retains the legacy descriptor-only seam
            # below rather than inventing authority.
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
        walks the steps in dependency order and dispatches each via
        ``kernel.invoke`` - inside its own ``executor.run_step`` durable
        boundary when an executor is wired here, inline when it is not (Round
        Seven, control-plane gap 3). This path passes no ``store``, so the walk
        is single-shot: no checkpoint/resume (that seam is the trigger path's,
        via the registered workflow task body). Raises ``LookupError`` if the
        workflow is unknown (fail-closed). Requires a ``kernel`` (wired at
        construction); without one this is a config error.
        """
        if self._kernel is None:
            raise RuntimeError("WorkflowLibrary.execute requires a kernel")
        # Scope resolution to the caller's active workspace ([2026] VJS-COUNTY 8, D2):
        # the InvocationContext already carries it (re-authorized every request), so a
        # workflow scoped to a different workspace is unknown here (LookupError).
        wf = await self.get(tenant, wf_id, active_workspace_id=context.workspace_id)
        if wf is None:
            raise LookupError(f"unknown workflow '{wf_id}' for tenant '{tenant}'")
        if _archived(wf):
            raise PermissionError("workflow_archived")
        return await run_workflow_definition(
            self._kernel, wf, inputs, context, executor=self._executor
        )
