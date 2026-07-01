"""The registered durable tasks: pure-data inputs, governed bodies (Beat 5).

Three tasks replace the P1-1 demos (ping / hitl_demo) as the production
durability backbone:

  * ``boltrig-invoke`` - one governed verb call as a durable unit. The input is
    pure data (noun, verb, params, a context envelope); the body reconstructs
    the :class:`InvocationContext` and re-enters ``kernel.invoke`` - the single
    chokepoint - so an enqueued call is validated, grant-checked, HITL-gated and
    audited exactly like a direct one (FR-EXE-06).
  * ``boltrig-work-item`` - the pump's claimed-item body by id. The worker
    process owns a kernel + org pump (mirroring api/worker.py); the engine
    re-runs the body on a crash (US-EXE-02).
  * ``boltrig-workflow-run`` - the workflow interpreter with checkpoint-resume
    (NFR-REL-02). A HITL pause durable-waits for the scoped approval event and
    re-enters the interpreter, which replays checkpointed steps and hands the
    paused step its approval id, so the kernel CAS executes the gated verb
    exactly once (NFR-REL-03, SEC-14).

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
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from boltrig.models import GrantSet, InvocationContext, TenantIsolation

log = logging.getLogger("boltrig.fleet.hatchet_app")

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
    inputs: dict[str, Any] = Field(default_factory=dict)
    ctx_envelope: dict[str, Any]
    run_id: str


try:  # module-level so the task decorators' get_type_hints can resolve annotations
    from hatchet_sdk import Context, DurableContext
except Exception:  # offline / no [durable] extra: keep the module import-safe
    Context = Any  # type: ignore[assignment,misc]
    DurableContext = Any  # type: ignore[assignment,misc]


# --- the context envelope (pure data across the queue) -------------------------
def context_to_envelope(ctx: InvocationContext) -> dict[str, Any]:
    """Serialise an :class:`InvocationContext` to a JSON-safe dict. A task input
    carries this envelope instead of the object so the queue holds pure data."""
    return {
        "tenant_id": ctx.tenant_id,
        "run_id": ctx.run_id,
        "parent_run_id": ctx.parent_run_id,
        "depth": ctx.depth,
        "on_behalf_of": ctx.on_behalf_of,
        "grants": {"allow": list(ctx.grants.allow), "deny": list(ctx.grants.deny)},
        "actor": ctx.actor,
        "actor_tier": ctx.actor_tier,
        "skills_loaded": list(ctx.skills_loaded),
        "extra": dict(ctx.extra),
    }


def context_from_envelope(env: dict[str, Any]) -> InvocationContext:
    """Reconstruct the :class:`InvocationContext` a task body re-enters the
    chokepoint with. The envelope only ever narrows to what it carries; missing
    fields take the fail-closed defaults (empty grants, ephemeral tier)."""
    grants = env.get("grants") or {}
    return InvocationContext(
        tenant_id=env["tenant_id"],
        run_id=env.get("run_id"),
        parent_run_id=env.get("parent_run_id"),
        depth=int(env.get("depth", 0)),
        on_behalf_of=env.get("on_behalf_of"),
        grants=GrantSet.of(list(grants.get("allow") or []), list(grants.get("deny") or [])),
        actor=env.get("actor", "unknown"),
        actor_tier=env.get("actor_tier", "ephemeral"),
        skills_loaded=tuple(env.get("skills_loaded") or ()),
        extra=dict(env.get("extra") or {}),
    )


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


async def run_workflow_body(kernel: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run a stored workflow through the interpreter with the checkpoint seam
    (NFR-REL-02): completed steps replay from checkpoints, a HITL pause is
    checkpointed with its request id, and a resume re-invokes the paused step
    with that approval id (the CAS makes execution exactly-once, NFR-REL-03)."""
    from boltrig.workflows.interpreter import run_workflow_definition

    ctx = context_from_envelope(payload["ctx_envelope"])
    tenant = payload["tenant"]
    _fence(tenant, ctx)
    wf = next(
        (w for w in await kernel.store.list_workflows(tenant) if w.id == payload["workflow_id"]),
        None,
    )
    if wf is None:  # fail-closed (K-13)
        raise LookupError(f"unknown workflow '{payload['workflow_id']}' for tenant '{tenant}'")
    return await run_workflow_definition(
        kernel, wf, dict(payload.get("inputs") or {}), ctx,
        run_id=payload.get("run_id"), store=kernel.store,
    )


async def work_item_task_body(pump: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the pump's one claimed-item body by id (US-FLT-06). The pump path
    itself dispatches through the chokepoint, so governance holds (FR-EXE-06)."""
    await pump._run_item_payload(
        {"tenant_id": payload["tenant_id"], "item_id": payload["item_id"]}
    )
    return {"handled": True, "item_id": payload["item_id"]}


def register_boltrig_tasks(executor: Any, kernel: Any, pump: Any | None = None) -> None:
    """Register the task bodies on an executor with a ``register_task`` seam
    (the LocalDurableExecutor): the offline carriage of the same bodies the
    Hatchet worker serves (US-EXE-05). The pump registers its own work-item body
    at construction; it is only added here when a pump is handed in."""
    register = getattr(executor, "register_task", None)
    if register is None:
        return

    async def _invoke(payload: dict[str, Any]) -> dict[str, Any]:
        return await invoke_task_body(kernel, payload)

    async def _workflow_run(payload: dict[str, Any]) -> dict[str, Any]:
        return await run_workflow_body(kernel, payload)

    register(TASK_INVOKE, _invoke)
    register(TASK_WORKFLOW_RUN, _workflow_run)
    if pump is not None:
        async def _work_item(payload: dict[str, Any]) -> dict[str, Any]:
            return await work_item_task_body(pump, payload)

        register(TASK_WORK_ITEM, _work_item)


# --- the worker-process resources ------------------------------------------------
async def _default_bootstrap() -> dict[str, Any]:
    """Build the worker-owned kernel + org pump, mirroring api/worker.py, ON THE
    WORKER'S RUNNING LOOP (loop-bound resources like an asyncpg pool must attach
    to the loop the tasks run on). The api import is function-local process
    wiring, not a module-scope fleet -> api dependency. HITL answers recorded
    through this kernel requeue parked work items (NFR-REL-03)."""
    from boltrig.api.bootstrap import _find_manifest, build_kernel_async, wire_hitl_resume
    from boltrig.config import load_manifest

    from .pump import build_org
    from .spawn import build_spawner

    kernel = await build_kernel_async()
    manifest = None
    manifest_path = _find_manifest()
    if manifest_path:
        try:
            manifest = load_manifest(manifest_path)
        except Exception as exc:  # a broken manifest degrades to the default org (P9)
            log.warning("manifest load failed (%s); using the default org", exc)
    pump = build_org(kernel, build_spawner(kernel), manifest)
    wire_hitl_resume(kernel, pump=pump)
    return {"kernel": kernel, "pump": pump}


def build_hatchet_app(
    bootstrap: Any | None = None, hatchet: Any | None = None
) -> tuple[Any, dict[str, Any]]:
    """Build the Hatchet client + the three registered Boltrig tasks.

    ``bootstrap`` is an async callable returning ``{"kernel": ..., "pump": ...}``;
    it runs lazily inside the first task body (on the worker's loop), defaulting
    to :func:`_default_bootstrap`. ``hatchet`` reuses an existing client (the
    executor seam) instead of constructing one from HATCHET_CLIENT_* env.
    Returns ``(hatchet, {task_name: workflow})`` keyed by registered task name.
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
        record = await run_workflow_body(res["kernel"], inp.model_dump())
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
            record = await run_workflow_body(res["kernel"], inp.model_dump())
        return record

    return hatchet, {
        TASK_INVOKE: invoke,
        TASK_WORK_ITEM: work_item,
        TASK_WORKFLOW_RUN: workflow_run,
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
