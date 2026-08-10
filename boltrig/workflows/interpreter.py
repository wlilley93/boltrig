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
resolved by the registry, not by the interpreter.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.models import InvocationContext
from . import control_flow, run_events
from .loop_contract import selected_params
from .loop_execution import LoopWalk, invalid_loop_run_record, loop_item_error_mode
from .step_execution import run_capability_step


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

    invalid = invalid_loop_run_record(
        definition, steps=steps, wf=wf, inputs=inputs, run_id=rid,
        relay=relay, emit_step=_emit_step)
    if invalid is not None:
        return invalid

    ordered, unrunnable = _topological_order(steps)
    results: dict[str, dict[str, Any]] = {}
    # Two skip lineages with different join semantics (graphon-parity OR-join):
    # * ``failed_or_skipped`` is FAILURE lineage - a failed/errored/paused step
    #   and everything skipped because of it. Any failure-lineage parent blocks
    #   a child (fail-closed: its data genuinely never arrived).
    # * ``benign_skipped`` is BRANCH lineage - a step skipped because a branch
    #   arm was not taken, and descendants skipped only for that reason. A
    #   child with at least one delivered parent still RUNS (the merge node
    #   after an if/else); only a child whose EVERY parent is benign-skipped
    #   skips too. This is what makes branch+merge graphs compose.
    failed_or_skipped: set[str] = {s["id"] for s in unrunnable}
    benign_skipped: set[str] = set()
    # Genuine failures (errored / unrunnable) that fail the run's overall status.
    # Conditional skips (branch_mismatch) and propagation skips (parent_failed) do
    # NOT count: a branch that omits an arm is a normal completed run.
    failed: set[str] = set(failed_or_skipped)
    # Steps whose failure was absorbed by an error strategy (graphon-parity
    # partial success): the run completes, the count stays observable.
    exceptions: list[str] = []
    for s in unrunnable:
        results[s["id"]] = {"action": s.get("action"), "status": "skipped",
                            "reason": "missing_parent_or_cycle"}
        _emit_step({"step_id": s["id"], "action": s.get("action"),
                    "status": "skipped", "reason": "missing_parent_or_cycle"})

    paused = False
    loops = LoopWalk()
    idx = 0
    while idx < len(ordered):
        step = ordered[idx]
        step_id = step["id"]
        action = step.get("action", "")
        _, step_params = selected_params(step)
        params = step_params or {}
        done = prior.get(_ck(step_id))
        if done is not None and done.status == "ok":
            # NFR-REL-02: a completed step replays its recorded output on a
            # resumed run; it is never re-dispatched.
            results[step_id] = {"action": step.get("action"), "status": "ok",
                                "output": done.output, "replayed": True}
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "ok", "replayed": True})
            if action == "flow.loop":
                ordered = loops.replay_completed(
                    ordered,
                    step_id=step_id,
                    action=action,
                    params=params,
                    results=results,
                    inputs=inputs,
                    recorded_output=done.output,
                    failed_or_skipped=failed_or_skipped,
                    failed=failed,
                    emit_step=_emit_step,
                )
            idx += 1
            continue
        parents = step.get("parents", []) or []
        # A step with a failure-lineage parent cannot run (fail-closed).
        if any(p in failed_or_skipped for p in parents):
            results[step_id] = {"action": step.get("action"), "status": "skipped",
                                "reason": "parent_failed"}
            failed_or_skipped.add(step_id)
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "skipped", "reason": "parent_failed"})
            idx += 1
            continue
        # OR-join: a step runs when at least one parent delivered. Only when
        # EVERY parent was benign-skipped (all upstream arms not taken) does
        # the skip propagate - the merge node after a branch runs exactly once.
        if parents and all(p in benign_skipped for p in parents):
            results[step_id] = {"action": step.get("action"), "status": "skipped",
                                "reason": "parents_skipped"}
            benign_skipped.add(step_id)
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "skipped", "reason": "parents_skipped"})
            idx += 1
            continue
        # A step that mixes a loop-body parent with a parent outside the loop
        # falls OUTSIDE the expanded body (control_flow.loop_body_ids): its body
        # parent was replaced by per-item clones, so its refs to that parent
        # cannot resolve. Skip it rather than dispatch with null refs.
        if any(p in loops.original_body_ids for p in step.get("parents", []) or []):
            results[step_id] = {"action": step.get("action"), "status": "skipped",
                                "reason": "mixed_loop_parent"}
            failed_or_skipped.add(step_id)
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "skipped", "reason": "mixed_loop_parent"})
            idx += 1
            continue
        # A branched step only runs when its declared branch matches every
        # parent that produced a branch label (conditional execution). An
        # unmatched arm is a BENIGN skip: downstream merge nodes with another
        # delivered parent still run (OR-join above).
        branch_ok, branch_reason = control_flow.branch_matches(step, results)
        if not branch_ok:
            results[step_id] = {"action": step.get("action"), "status": "skipped",
                                "reason": branch_reason}
            benign_skipped.add(step_id)
            _emit_step({"step_id": step_id, "action": step.get("action"),
                        "status": "skipped", "reason": branch_reason})
            idx += 1
            continue

        noun, verb = _split_action(action)

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
                failed.add(step_id)
            elif checkpointing:
                await store.upsert_checkpoint(
                    wf.tenant_id, rid, _ck(step_id), "ok", output=coutcome.get("output")
                )
            _emit_step({"step_id": step_id, "action": action, "status": coutcome["status"]})
            # Loop body iteration: a flow.loop with a non-empty items list
            # expands its body into the walk so each item runs the body once.
            # The body is the loop's self-contained descendant sub-graph.
            ordered = loops.expand_outcome(
                ordered, step_id, coutcome,
                on_item_error=loop_item_error_mode(params),
            )
            idx += 1
            continue

        _emit_step({"step_id": step_id, "action": action, "status": "running"})

        # A resumed paused step re-invokes with its approval id: the kernel's
        # consume-if-approved CAS makes the gated execution exactly-once
        # (NFR-REL-03, SEC-14); a second resume finds the approval spent.
        approval_id = done.hitl_request_id if done is not None and done.status == "paused" else None

        # Retry, error strategies, checkpointing and the per-step idempotency
        # key all live in step_execution.run_capability_step - one governed
        # dispatch, many ways to record the outcome (never a second path).
        step_paused, stop_walk = await run_capability_step(
            kernel=kernel, executor=executor,
            store=store if checkpointing else None,
            wf=wf, rid=rid, run_ctx=run_ctx,
            step=step, step_id=step_id, action=action, noun=noun, verb=verb,
            params=params, approval_id=approval_id,
            results=results, failed_or_skipped=failed_or_skipped,
            failed=failed, exceptions=exceptions,
            emit_step=_emit_step, ck=_ck,
        )
        if step_paused:
            paused = True
        if stop_walk:
            break
        idx += 1

    # Collapse per-item loop-clone results back onto each original body step so
    # the run record (keyed by original step id) reflects the iteration. Under
    # ``on_item_error: continue|drop`` absorbed item errors are removed from
    # ``failed`` here (they no longer fail the run) and surface as exceptions.
    absorbed_item_errors = loops.aggregate(results, failed=failed)

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
        # Absorbed failures (error strategies + loop item-error modes): the run
        # status stays projection-compatible, the partial success stays visible.
        "exceptions_count": len(exceptions) + absorbed_item_errors,
        "steps": [{"id": s["id"], **results.get(s["id"], {"status": "skipped"})} for s in steps],
        "inputs": dict(inputs or {}),
    }
