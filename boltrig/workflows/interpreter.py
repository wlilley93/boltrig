"""The generic workflow interpreter (Round Seven, control-plane gap 3).

Before this, a stored ``WorkflowDefinition`` was authored, persisted, matched and
"triggered" as an opaque blob: nothing walked its ``definition["steps"]`` and
ran them. ``WorkflowLibrary.trigger`` recorded one boundary for the whole run.
That meant new behaviour still needed code (a hand-registered Hatchet workflow),
not data.

This interpreter closes that gap. It walks a definition's steps in dependency
order (honouring each step's ``parents``) and dispatches each step's ``action``
through the kernel chokepoint. Two properties are load-bearing:

* **One governed path (P2).** Every step is dispatched via ``kernel.invoke`` -
  the single chokepoint that already routes a verb to an adapter OR an agent by
  ``binding.target_type``. So a step inherits validation, grant-check, the
  consequence/HITL gate, idempotency, and audit for free; a step can neither
  escalate nor bypass governance (SEC-50). There is no second dispatch path.

* **Per-step durability AND checkpoint-resume - the trigger/engine path
  combines both.** With an ``executor`` wired each step runs inside its own
  ``executor.run_step("workflow:<wf>:<step>", ...)`` boundary (FR-CTL-02); with
  the ``store`` seam wired the same walk checkpoints and replays (below). The
  trigger path (``run_workflow_body``) wires BOTH: what that guarantees depends
  honestly on the executor. On ``LocalDurableExecutor`` the boundary is
  recorded bookkeeping (non-durable; the checkpoint seam carries recovery). On
  ``HatchetExecutor`` ``run_step`` is NOT a durable engine step - the installed
  SDK (1.33.x) exposes no public durable child-step API on ``DurableContext`` -
  so on live Hatchet per-step recovery is: the engine retries the whole durable
  TASK, checkpoints replay completed steps, and the per-step idempotency key
  (below) covers the completed-but-uncheckpointed window. Only a genuinely
  in-flight step re-executes. The ``execute`` path stays single-shot (executor
  boundary, no store).

A step that fails (an ungranted verb, an unbound action, a backend error) is
recorded and its descendants are skipped; the run never crashes the fleet (P9).
A high-consequence step that the HITL gate holds is recorded as ``paused``.

* **Checkpoint-resume (Beat 5).** With an optional ``store`` seam, each
  completed step is checkpointed ``ok`` with its output; a re-run of the same
  ``run_id`` replays checkpointed steps instead of re-dispatching them
  (NFR-REL-02). A HITL pause is checkpointed ``paused`` with its request id and
  the walk stops; the resumed run re-invokes that step with the approval id, so
  the kernel's consume-if-approved CAS executes the gated verb exactly once
  (NFR-REL-03, SEC-14). Checkpoint keys are workflow-scoped (``<wf_id>:<step>``)
  because a ``run_id`` may be shared by runs of different workflows.

* **Per-step idempotency keys (the checkpoint seam's other half).** A
  checkpointed step also dispatches with a deterministic key
  ``workflow:<wf_id>:<run_id>:<step>``. If the worker dies AFTER the step's
  verb completed but BEFORE the checkpoint write landed, the resumed run
  re-dispatches the step and the kernel's idempotency layer replays the
  recorded result (SEC-15) instead of re-executing side effects. If the worker
  died genuinely mid-execution the prior claim is parked (IN_PROGRESS, then
  UNCERTAIN after its lease): the re-dispatch then falls back to a keyless
  invoke - standard engine-retry semantics, at-least-once for the interrupted
  step, exactly what an unkeyed dispatch already accepted. A verb declared
  idempotency-disabled keeps no key - its one-time secret result must never be
  replay-cached.

The interpreter is generic: a step's ``action`` is a fully-qualified verb id
(``"<noun>.<verb>"``); what it resolves to (adapter or agent) is the registry's
business, not the interpreter's. Imports only models; severable from the kernel.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.models import InvocationContext, BoltrigError, IdempotencyConflict
from . import control_flow, run_events


def _topological_order(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Order steps so every parent precedes its children (Kahn's algorithm).

    Returns ``(ordered, unrunnable)``. Independent steps keep their definition
    order (stable). Steps in a cycle or naming a missing parent are unrunnable
    and returned separately so the caller can record them as skipped (fail-closed,
    never silently dropped)."""
    by_id = {s["id"]: s for s in steps}
    indegree = {s["id"]: 0 for s in steps}
    children: dict[str, list[str]] = {s["id"]: [] for s in steps}
    for s in steps:
        for parent in s.get("parents", []) or []:
            if parent in by_id:
                indegree[s["id"]] += 1
                children[parent].append(s["id"])
            else:
                indegree[s["id"]] += 1  # missing parent => never satisfiable
    ready = [s for s in steps if indegree[s["id"]] == 0]
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    while ready:
        step = ready.pop(0)
        ordered.append(step)
        seen.add(step["id"])
        for child_id in children[step["id"]]:
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(by_id[child_id])
    unrunnable = [s for s in steps if s["id"] not in seen]
    return ordered, unrunnable


def _split_action(action: str) -> tuple[str, str]:
    """A step action is a verb id ``"<noun>.<verb>"``; the noun is the prefix."""
    noun = action.split(".", 1)[0] if action else ""
    return noun, action


async def run_workflow_definition(
    kernel: Any,
    wf: Any,
    inputs: dict[str, Any],
    context: InvocationContext,
    *,
    executor: Any | None = None,
    run_id: str | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Execute a ``WorkflowDefinition``'s steps and return a run record.

    Each step is dispatched through ``kernel.invoke`` - inside its own
    ``executor.run_step`` durable boundary when an executor is wired, inline
    otherwise. The returned record carries per-step status/output so the run is
    observable; the overall ``status`` is ``completed`` (all ok), ``paused`` (a
    HITL gate held a step), or ``failed`` (a step errored / was skipped).

    ``store`` (upsert_checkpoint / list_checkpoints) activates checkpoint-resume
    for ``run_id`` (NFR-REL-02/NFR-REL-03); without it the walk is single-shot,
    unchanged from Round Seven.
    """
    definition = wf.definition or {}
    steps = list(definition.get("steps", []) or [])
    rid = run_id or context.run_id or (executor.new_run_id() if executor is not None else None)
    # Bind steps and emitted events to one id shared by the live canvas and audit.
    run_ctx = replace(context, run_id=rid) if rid else context
    relay = getattr(kernel, "events", None)

    def _emit_step(event: dict[str, Any]) -> None:
        # Fail-safe side-channel (Round Twelve): light the canvas node for this
        # step. Never affects the run (P9).
        if relay is None or not rid:
            return
        try:
            relay.publish(run_ctx.tenant_id, rid, {"type": "workflow_step", **event})
        except Exception:
            pass

    # Prior checkpoints for this run (empty without the seam, NFR-REL-02): an
    # ``ok`` step replays, a ``paused`` one carries the approval id to resume with.
    checkpointing = store is not None and bool(rid)
    prior: dict[str, Any] = {}
    if checkpointing:
        prior = {c.step: c for c in await store.list_checkpoints(wf.tenant_id, rid)}

    def _ck(step: str) -> str:
        # Checkpoint keys are workflow-scoped: rid may come from context.run_id,
        # which two runs of DIFFERENT workflows can share, and the store keys
        # checkpoints by (tenant, run_id, step) alone - an unscoped step key
        # would cross-replay one workflow's step outputs into the other.
        return f"{wf.id}:{step}"

    ordered, unrunnable = _topological_order(steps)
    results: dict[str, dict[str, Any]] = {}
    failed_or_skipped: set[str] = {s["id"] for s in unrunnable}
    # Genuine failures (errored / unrunnable) that fail the run's overall status.
    # Conditional skips (branch_mismatch) and propagation skips (parent_failed) do
    # NOT count: a branch that omits an arm is a normal completed run.
    failed: set[str] = set(failed_or_skipped)
    for s in unrunnable:
        results[s["id"]] = {"action": s.get("action"), "status": "skipped",
                            "reason": "missing_parent_or_cycle"}
        _emit_step({"step_id": s["id"], "action": s.get("action"),
                    "status": "skipped", "reason": "missing_parent_or_cycle"})

    paused = False
    expanded: list[tuple[list[str], int]] = []  # (body_ids, item_count) per loop
    loop_bodies: set[str] = set()  # original body ids replaced by per-item clones
    idx = 0
    while idx < len(ordered):
        step = ordered[idx]
        step_id = step["id"]
        done = prior.get(_ck(step_id))
        if done is not None and done.status == "ok":
            # NFR-REL-02: a completed step replays its recorded output on a
            # resumed run; it is never re-dispatched.
            results[step_id] = {"action": step.get("action"), "status": "ok",
                                "output": done.output, "replayed": True}
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "ok", "replayed": True})
            idx += 1
            continue
        # A step whose parent failed/was skipped cannot run (fail-closed).
        if any(p in failed_or_skipped for p in step.get("parents", []) or []):
            results[step_id] = {"action": step.get("action"), "status": "skipped",
                                "reason": "parent_failed"}
            failed_or_skipped.add(step_id)
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "skipped", "reason": "parent_failed"})
            idx += 1
            continue
        # A step that mixes a loop-body parent with a parent outside the loop
        # falls OUTSIDE the expanded body (control_flow.loop_body_ids): its body
        # parent was replaced by per-item clones, so its refs to that parent
        # cannot resolve. Skip it rather than dispatch with null refs.
        if any(p in loop_bodies for p in step.get("parents", []) or []):
            results[step_id] = {"action": step.get("action"), "status": "skipped",
                                "reason": "mixed_loop_parent"}
            failed_or_skipped.add(step_id)
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "skipped", "reason": "mixed_loop_parent"})
            idx += 1
            continue
        # A branched step only runs when its declared branch matches every
        # parent that produced a branch label (conditional execution).
        branch_ok, branch_reason = control_flow.branch_matches(step, results)
        if not branch_ok:
            results[step_id] = {"action": step.get("action"), "status": "skipped",
                                "reason": branch_reason}
            failed_or_skipped.add(step_id)
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "skipped", "reason": branch_reason})
            idx += 1
            continue

        action = step.get("action", "")
        noun, verb = _split_action(action)
        params = step.get("params") or step.get("with") or {}
        # Loop clones carry __loop_item/__loop_index metadata (see
        # control_flow.expand_loop). Nothing substitutes them into param values,
        # so they are dispatch metadata only: strip them before the params hit
        # schema validation (a verb with additionalProperties: false would
        # otherwise reject every clone).
        params = {k: v for k, v in params.items() if not k.startswith("__loop_")}

        # Control-plane steps (trigger/flow/code) are resolved locally by the
        # interpreter, NOT dispatched through kernel.invoke: they are internal
        # routing, not external capabilities (the one-chokepoint doctrine governs
        # capability dispatch, not control routing).
        if control_flow.is_control_step(action):
            _emit_step({"step_id": step_id, "action": action, "status": "running"})
            coutcome = control_flow.run_control_step(action, params, results, inputs)
            results[step_id] = {"action": action, "status": coutcome["status"],
                                "output": coutcome.get("output")}
            if coutcome["status"] != "ok":
                failed_or_skipped.add(step_id)
            elif checkpointing:
                await store.upsert_checkpoint(
                    wf.tenant_id, rid, _ck(step_id), "ok", output=coutcome.get("output")
                )
            _emit_step({"step_id": step_id, "action": action,
                        "status": coutcome["status"]})
            # Loop body iteration: a flow.loop with a non-empty items list
            # expands its body into the walk so each item runs the body once.
            # The body is the loop's self-contained descendant sub-graph.
            loop_items = coutcome.get("_items") if coutcome["status"] == "ok" else None
            if loop_items:
                ordered, body_ids = control_flow.expand_loop(ordered, step_id, loop_items)
                if body_ids:
                    expanded.append((body_ids, len(loop_items)))
                    loop_bodies.update(body_ids)
            idx += 1
            continue

        _emit_step({"step_id": step_id, "action": action, "status": "running"})

        # A resumed paused step re-invokes with its approval id: the kernel's
        # consume-if-approved CAS makes the gated execution exactly-once
        # (NFR-REL-03, SEC-14); a second resume finds the approval spent.
        approval_id = (
            done.hitl_request_id if done is not None and done.status == "paused" else None
        )

        # The checkpoint seam's other half (NFR-REL-02): a deterministic
        # per-step idempotency key, so a step whose verb COMPLETED but whose
        # checkpoint write was lost (worker died between the two) replays its
        # recorded kernel result on the resumed run instead of re-executing
        # side effects. An idempotency-disabled verb keeps no key: its
        # one-time secret result must never be replay-cached.
        idempotency_key: str | None = None
        if checkpointing:
            get_verb = getattr(store, "get_verb", None)
            verb_def = await get_verb(wf.tenant_id, verb) if get_verb is not None else None
            mode = getattr(getattr(verb_def, "idempotency_mode", None), "value", None)
            if verb_def is not None and mode != "disabled":
                idempotency_key = f"workflow:{wf.id}:{rid}:{step_id}"

        async def _dispatch(
            noun=noun, verb=verb, params=params, approval_id=approval_id,
            idempotency_key=idempotency_key,
        ) -> dict[str, Any]:
            try:
                return await kernel.invoke(
                    noun, verb, params, run_ctx,
                    idempotency_key=idempotency_key, approval_id=approval_id,
                )
            except IdempotencyConflict:
                if idempotency_key is None:
                    raise
                # A prior attempt parked the key (worker died between execution
                # start and claim completion; a COMPLETED prior record replays
                # above and never reaches here). Fall back to a keyless invoke:
                # standard engine-retry semantics, at-least-once for the
                # genuinely interrupted step (NFR-REL-02) - exactly what an
                # unkeyed dispatch already accepted.
                return await kernel.invoke(
                    noun, verb, params, run_ctx, approval_id=approval_id
                )

        boundary = f"workflow:{wf.id}:{step_id}"
        try:
            if executor is not None:
                output = await executor.run_step(boundary, _dispatch, run_id=rid)
            else:
                output = await _dispatch()
            results[step_id] = {"action": action, "status": "ok", "output": output}
            if checkpointing:
                await store.upsert_checkpoint(wf.tenant_id, rid, _ck(step_id), "ok", output=output)
            _emit_step({"step_id": step_id, "action": action, "status": "ok"})
        except BoltrigError as exc:
            reason = getattr(exc, "reason", type(exc).__name__)
            # A held HITL gate is a pause, not a failure - the run can resume.
            status = "paused" if reason in {"pending_human", "approval_required"} else "failed"
            hitl_id = getattr(exc, "hitl_request_id", None)
            failed_or_skipped.add(step_id)
            if status == "paused":
                # A pause is not a failure, but for dependency purposes it is
                # treated like one: without checkpointing the walk continues,
                # and descendants must never dispatch with the paused parent's
                # (missing) output.
                paused = True
            else:
                failed.add(step_id)
            results[step_id] = {"action": action, "status": status, "reason": reason}
            if hitl_id:
                results[step_id]["hitl_request_id"] = hitl_id
            _emit_step({"step_id": step_id, "action": action, "status": status,
                        "reason": reason})
            if status == "paused" and checkpointing:
                # NFR-REL-03: the pause is durable - the request id is the
                # approval id the resumed run re-invokes with; stop the walk.
                await store.upsert_checkpoint(
                    wf.tenant_id, rid, _ck(step_id), "paused", hitl_request_id=hitl_id
                )
                break
        except Exception as exc:  # an adapter bug must not crash the fleet (P9)
            failed_or_skipped.add(step_id)
            failed.add(step_id)
            results[step_id] = {"action": action, "status": "error",
                                "reason": type(exc).__name__}
            _emit_step({"step_id": step_id, "action": action, "status": "error",
                        "reason": type(exc).__name__})
        idx += 1

    # Collapse per-item loop-clone results back onto each original body step so
    # the run record (keyed by original step id) reflects the iteration.
    for body_ids, item_count in expanded:
        control_flow.aggregate_loop_results(results, body_ids, item_count)

    if paused:
        overall = "paused"
    elif failed:
        overall = "failed"
    else:
        overall = "completed"
    # A terminal marker lets live followers settle without waiting for an idle timeout.
    run_events.emit_terminal(relay, run_ctx.tenant_id, rid, wf.id, overall)
    return {
        "run_id": rid,
        "workflow_id": wf.id,
        "tenant_id": wf.tenant_id,
        "version": wf.version,
        "status": overall,
        "steps": [
            {"id": s["id"], **results.get(s["id"], {"status": "skipped"})}
            for s in steps
        ],
        "inputs": dict(inputs or {}),
    }
