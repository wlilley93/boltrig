"""The registered durable tasks: pure-data inputs, governed bodies (Beat 5).

Four tasks replace the P1-1 demos (ping / hitl_demo) as the production
durability backbone:

  * ``boltrig-invoke`` - one governed verb call as a durable unit. The input is
    pure data (noun, verb, params, a context envelope); the body reconstructs
    the :class:`InvocationContext` and re-enters ``kernel.invoke`` - the single
    chokepoint - so an enqueued call is validated, grant-checked, HITL-gated and
    audited exactly like a direct one (FR-EXE-06).
  * ``boltrig-work-item`` - the pump's claimed-item body by id. The worker
    process owns a kernel + org pump (mirroring api/worker.py); the engine
    re-runs the body on a crash (US-EXE-02).
  * ``boltrig-workflow-run`` - the workflow interpreter with BOTH durability
    seams wired: each step dispatches inside an ``executor.run_step`` boundary
    AND checkpoint-resume is active (NFR-REL-02), with a deterministic per-step
    idempotency key closing the completed-but-uncheckpointed crash window
    (SEC-15). A HITL pause durable-waits for the scoped approval event and
    re-enters the interpreter, which replays checkpointed steps and hands the
    paused step its approval id, so the kernel CAS executes the gated verb
    exactly once (NFR-REL-03, SEC-14).
  * ``boltrig-ultracode-run`` / ``boltrig-ultracode-agent`` - a phased Boltrig
    v2/OpenCode workflow from pure data. The parent validates the workflow
    contract and fans out phase-agent bodies through a separate task seam; each
    agent still runs through the fleet spawner so cost, audit, and degraded
    honesty stay on the standard runtime path.
  * ``boltrig-memory-projection`` - one Mem0/Cognee projection catch-up write or
    delete after the canonical ledger has already committed.

Correlation of an approval to a run is by SCOPE (the run id), not by baking the
id into the event key - that is how Hatchet routes a user event to one durable
wait. ``hatchet_sdk`` is imported defensively so importing this module is safe
without the optional [durable] extra; the input models and context types are
module-level so the SDK can resolve task annotations (py3.14). The task bodies
are plain module functions, also registered on the LocalDurableExecutor via
:func:`register_boltrig_tasks` - one body, two carriages (US-EXE-05). This
module is in the fleet layer; the kernel and models import nothing from it.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from boltrig.models import (
    InvocationContext,
    TenantIsolation,
    context_from_envelope,
    context_to_envelope,
)

from .hatchet_memory import (
    TASK_MEMORY_PROJECTION,
    register_hatchet_memory_projection_task,
    register_local_memory_projection_task,
)
from .hatchet_ultracode import (
    TASK_ULTRACODE_AGENT,
    TASK_ULTRACODE_RUN,
    register_hatchet_ultracode_tasks,
    register_local_ultracode_tasks,
)
from .hatchet_bootstrap import _default_bootstrap
from .workers import HatchetExecutor

__all__ = [
    "APPROVAL_EVENT_KEY",
    "TASK_INVOKE",
    "TASK_WORK_ITEM",
    "TASK_WORKFLOW_RUN",
    "TASK_ULTRACODE_RUN",
    "TASK_ULTRACODE_AGENT",
    "TASK_MEMORY_PROJECTION",
    "approve",
    "build_hatchet_app",
    "context_from_envelope",
    "context_to_envelope",
    "invoke_task_body",
    "register_boltrig_tasks",
    "run_workflow_body",
    "work_item_task_body",
]

# The HITL approval event key. Correlation to a specific run is by SCOPE
# (the run id), not by baking the id into the event name.
APPROVAL_EVENT_KEY = "boltrig:approval"

# The registered task names (the queue seam's vocabulary, US-EXE-02).
TASK_INVOKE = "boltrig-invoke"
TASK_WORK_ITEM = "boltrig-work-item"  # matches pump.WORK_ITEM_TASK (read-only there)
TASK_WORKFLOW_RUN = "boltrig-workflow-run"


class InvokeInput(BaseModel):
    """Pure-data input for one governed verb call (FR-EXE-06)."""

    tenant: str
    noun: str
    verb: str
    params: dict[str, Any] = Field(default_factory=dict)
    ctx_envelope: dict[str, Any]
    run_id: str | None = None
    step: str | None = None  # observability label; carried, never trusted


class WorkItemInput(BaseModel):
    """Pure-data input for the pump's claimed-item body. Field names match the
    payload the pump enqueues ({tenant_id, item_id}; pump.py is read-only)."""

    tenant_id: str
    item_id: str


class WorkflowRunInput(BaseModel):
    """Pure-data input for an interpreted workflow run (NFR-REL-02)."""

    tenant: str
    workflow_id: str
    workflow_snapshot: dict[str, Any]
    inputs: dict[str, Any] = Field(default_factory=dict)
    ctx_envelope: dict[str, Any]
    run_id: str


try:  # module-level so the task decorators' get_type_hints can resolve annotations
    from hatchet_sdk import Context, DurableContext
except Exception:  # offline / no [durable] extra: keep the module import-safe
    Context = Any  # type: ignore[assignment,misc]
    DurableContext = Any  # type: ignore[assignment,misc]


# --- the context envelope (pure data across the queue) -------------------------
# Re-exported from boltrig.models (this module's public names are unchanged): the
# codec moved beside the model when a THIRD lane began replaying a context it did
# not build (the held-write resume, decision 0018). Three private copies is how one
# lane silently drops an authority-bearing field the approval fingerprint binds.


def _fence(payload_tenant: str, ctx: InvocationContext) -> None:
    """A task payload naming one tenant with an envelope for another is a
    cross-tenant confusion: refuse before any dispatch (SEC-08, K-22)."""
    if payload_tenant != ctx.tenant_id:
        raise TenantIsolation(
            f"task payload tenant '{payload_tenant}' != envelope tenant '{ctx.tenant_id}'"
        )


# --- the task bodies (one body, two carriages) ----------------------------------
async def invoke_task_body(kernel: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one governed verb call from pure data (FR-EXE-06): rebuild the
    context and re-enter ``kernel.invoke``. Governance is not bypassable from
    inside a durable task - an ungranted verb is denied and audited here exactly
    as it would be on the direct path."""
    ctx = context_from_envelope(payload["ctx_envelope"])
    _fence(payload["tenant"], ctx)
    if payload.get("run_id"):
        ctx = replace(ctx, run_id=payload["run_id"])
    return await kernel.invoke(
        payload["noun"], payload["verb"], dict(payload.get("params") or {}), ctx
    )


async def run_workflow_body(
    kernel: Any, payload: dict[str, Any], *, executor: Any | None = None
) -> dict[str, Any]:
    """Run a stored workflow through the interpreter with BOTH durability
    seams wired (NFR-REL-02): each step dispatches inside its own
    ``executor.run_step`` boundary AND the checkpoint seam replays completed
    steps, so a re-run never re-dispatches them. A HITL pause is checkpointed
    with its request id, and a resume re-invokes the paused step with that
    approval id (the CAS makes execution exactly-once, NFR-REL-03). What the
    per-step boundary itself guarantees depends on the executor: recorded
    bookkeeping on the local fallback, an honest pass-through on
    ``HatchetExecutor`` today (the SDK exposes no durable child-step API) -
    there the engine's whole-task retry plus checkpoints plus the per-step
    idempotency keys are the recovery story. ``executor=None`` keeps the
    legacy inline shape for direct callers."""
    from boltrig.workflows.interpreter import run_workflow_definition
    from boltrig.workflows.snapshot import workflow_from_snapshot

    ctx = context_from_envelope(payload["ctx_envelope"])
    tenant = payload["tenant"]
    _fence(tenant, ctx)
    wf = workflow_from_snapshot(
        payload.get("workflow_snapshot"),
        tenant_id=tenant,
        workflow_id=payload["workflow_id"],
        workspace_id=ctx.workspace_id,
    )
    run_id = payload.get("run_id")
    try:
        record = await run_workflow_definition(
            kernel,
            wf,
            dict(payload.get("inputs") or {}),
            ctx,
            executor=executor,
            run_id=run_id,
            store=kernel.store,
        )
    except Exception:
        # An infrastructure/task exception is not a terminal workflow verdict:
        # Hatchet may retry it. Leave the logical occurrence in flight so the
        # engine retry/checkpoint path can settle a real returned outcome later.
        raise
    if run_id and record.get("status") in {"completed", "failed"}:
        succeeded = record["status"] == "completed"
        finish_outcome = getattr(
            kernel.store, "finish_workflow_schedule_outcome", None
        )
        if finish_outcome is not None:
            await finish_outcome(
                tenant,
                run_id,
                status="succeeded" if succeeded else "failed",
                reason=None if succeeded else "workflow_execution_failed",
            )
    return record


async def work_item_task_body(pump: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the pump's one claimed-item body by id (US-FLT-06). The pump path
    itself dispatches through the chokepoint, so governance holds (FR-EXE-06).

    The payload is forwarded WHOLE. It used to be rebuilt from tenant_id and
    item_id, which silently discarded every other key: anything the enqueuing side
    put on it reached the local lane and vanished on the durable one, with no error
    and no log, so the two lanes quietly disagreed about what the body was given.

    That is not hypothetical. It is the carriage
    [2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001 D2 needs for the claim-time
    lease token, and a court clerk found the drop by reading this line rather than
    by anything failing. Forward the payload and let the body choose what it reads.
    """
    await pump._run_item_payload(dict(payload))
    return {"handled": True, "item_id": payload["item_id"]}


def register_boltrig_tasks(
    executor: Any,
    kernel: Any,
    pump: Any | None = None,
    *,
    spawner: Any | None = None,
) -> None:
    """Register the task bodies on an executor with a ``register_task`` seam
    (the LocalDurableExecutor): the offline carriage of the same bodies the
    Hatchet worker serves (US-EXE-05). The pump registers its own work-item body
    at construction; it is only added here when a pump is handed in. A serving
    composition passes its one process-owned spawner through to Ultracode;
    omission stays fail-closed rather than constructing a configless side path.
    """
    register = getattr(executor, "register_task", None)
    if register is None:
        return

    async def _invoke(payload: dict[str, Any]) -> dict[str, Any]:
        return await invoke_task_body(kernel, payload)

    async def _workflow_run(payload: dict[str, Any]) -> dict[str, Any]:
        # The combined path: per-step run_step boundaries AND checkpoints.
        return await run_workflow_body(kernel, payload, executor=executor)

    register(TASK_INVOKE, _invoke)
    register(TASK_WORKFLOW_RUN, _workflow_run)
    register_local_memory_projection_task(executor, kernel)
    register_local_ultracode_tasks(executor, kernel, spawner=spawner)
    if pump is not None:

        async def _work_item(payload: dict[str, Any]) -> dict[str, Any]:
            return await work_item_task_body(pump, payload)

        register(TASK_WORK_ITEM, _work_item)


def build_hatchet_app(
    bootstrap: Any | None = None, hatchet: Any | None = None
) -> tuple[Any, dict[str, Any]]:
    """Build the Hatchet client + the three registered Boltrig tasks.

    ``bootstrap`` is an async callable returning ``{"kernel": ..., "pump": ...,
    "spawner": ...}``; it runs lazily on the worker loop. A custom bootstrap that
    omits ``spawner`` can serve non-agent tasks, but Ultracode fails closed.
    ``hatchet`` may reuse an existing client. The returned workflow map is keyed
    by registered task name.
    """
    from hatchet_sdk import Hatchet, UserEventCondition

    hatchet = hatchet if hatchet is not None else Hatchet()
    boot = bootstrap if bootstrap is not None else _default_bootstrap
    state: dict[str, Any] = {}
    lock = asyncio.Lock()

    async def _resources() -> dict[str, Any]:
        async with lock:  # build once, on the worker's loop
            if not state:
                state.update(await boot())
        return state

    @hatchet.task(name=TASK_INVOKE, input_validator=InvokeInput)
    async def invoke(inp: InvokeInput, ctx: Context) -> dict:
        res = await _resources()
        return await invoke_task_body(res["kernel"], inp.model_dump())

    @hatchet.task(name=TASK_WORK_ITEM, input_validator=WorkItemInput)
    async def work_item(inp: WorkItemInput, ctx: Context) -> dict:
        res = await _resources()
        if res.get("pump") is None:  # fail-closed: no org, no silent drop (K-13)
            raise RuntimeError("no pump wired for boltrig-work-item")
        return await work_item_task_body(res["pump"], inp.model_dump())

    @hatchet.durable_task(
        name=TASK_WORKFLOW_RUN,
        input_validator=WorkflowRunInput,
        # a HITL pause can last arbitrarily long; the durable wait must not be
        # killed by the default 60s execution timeout (NFR-REL-01).
        execution_timeout=timedelta(hours=24),
        schedule_timeout=timedelta(hours=24),
    )
    async def workflow_run(inp: WorkflowRunInput, ctx: DurableContext) -> dict:
        res = await _resources()
        # run_step is an honest pass-through today (its docstring says why).
        executor = HatchetExecutor(hatchet)
        record = await run_workflow_body(res["kernel"], inp.model_dump(), executor=executor)
        waits = 0
        while record.get("status") == "paused":
            # Durable pause: block until the approval event for THIS run arrives
            # (fixed key + per-run scope; the engine persists the wait, so a
            # worker restart resumes the same run, NFR-REL-01). The signal key is
            # unique per wait so repeated pauses in one run each register.
            waits += 1
            await ctx.aio_wait_for(
                f"approval-{inp.run_id}-{waits}",
                UserEventCondition(
                    event_key=APPROVAL_EVENT_KEY,
                    scope=inp.run_id,
                    expression="true",
                    consider_events_since=datetime.now(timezone.utc) - timedelta(minutes=10),
                ),
            )
            # Re-enter the interpreter: checkpointed steps replay, the paused
            # step re-invokes with its approval id (CAS exactly-once, NFR-REL-03).
            record = await run_workflow_body(res["kernel"], inp.model_dump(), executor=executor)
        return record

    memory_workflows = register_hatchet_memory_projection_task(hatchet, _resources)
    ultracode_workflows = register_hatchet_ultracode_tasks(hatchet, _resources)

    return hatchet, {
        TASK_INVOKE: invoke,
        TASK_WORK_ITEM: work_item,
        TASK_WORKFLOW_RUN: workflow_run,
        **memory_workflows,
        **ultracode_workflows,
    }


async def approve(hatchet: Any, run_id: str, decision: str = "approve") -> None:
    """Push the scoped approval event that resumes a paused durable run. In
    production this is fired by the HITL answer bridge (wire_hitl_resume ->
    executor.push_event); this helper is the same push for live tests/tools."""
    from hatchet_sdk import PushEventOptions

    await hatchet.event.aio_push(
        APPROVAL_EVENT_KEY,
        {"decision": decision, "run_id": run_id},
        options=PushEventOptions(scope=run_id),
    )
