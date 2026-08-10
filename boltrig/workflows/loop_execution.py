"""Runtime bookkeeping for validated ``flow.loop`` steps.

The generic interpreter owns the topological walk.  This helper owns only loop
preflight receipts, deterministic expansion/replay and result aggregation, so
the interpreter does not grow a second workflow engine inside itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import control_flow, run_events, step_execution
from .loop_contract import selected_params, validate_loop_contract

StepEmitter = Callable[[dict[str, Any]], None]
Expansion = tuple[list[str], int, dict[str, str], str]


def invalid_loop_run_record(
    definition: dict[str, Any],
    *,
    steps: list[dict[str, Any]],
    wf: Any,
    inputs: dict[str, Any],
    run_id: str | None,
    relay: Any,
    emit_step: StepEmitter,
) -> dict[str, Any] | None:
    """Build and emit a value-free failure receipt, or return ``None``."""
    issue = validate_loop_contract(definition)
    if issue is None:
        return None
    invalid_steps: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        step_id = str(step.get("id", ""))
        is_cause = step_id == issue.step_id if issue.step_id else index == 0
        status = "failed" if is_cause else "skipped"
        reason = issue.reason if is_cause else "invalid_loop_contract"
        invalid_steps.append(
            {
                "id": step_id,
                "action": step.get("action"),
                "status": status,
                "reason": reason,
            }
        )
        emit_step(
            {
                "step_id": step_id,
                "action": step.get("action"),
                "status": status,
                "reason": reason,
            }
        )
    run_events.emit_terminal(relay, wf.tenant_id, run_id, wf.id, "failed")
    return {
        "run_id": run_id,
        "workflow_id": wf.id,
        "tenant_id": wf.tenant_id,
        "version": wf.version,
        "status": "failed",
        "steps": invalid_steps,
        "inputs": dict(inputs or {}),
    }


@dataclass
class LoopWalk:
    """Mutable loop-only state for one interpreter walk."""

    expanded: list[Expansion] = field(default_factory=list)
    original_body_ids: set[str] = field(default_factory=set)

    def expand_outcome(
        self,
        ordered: list[dict[str, Any]],
        step_id: str,
        outcome: dict[str, Any],
        *,
        on_item_error: str = "fail",
    ) -> list[dict[str, Any]]:
        items = outcome.get("_items") if outcome.get("status") == "ok" else None
        if items is None:
            return ordered
        actions = {step["id"]: step.get("action", "") for step in ordered}
        expanded_order, body_ids = control_flow.expand_loop(ordered, step_id, items)
        if body_ids:
            self.expanded.append(
                (
                    body_ids,
                    len(items),
                    {body_id: actions.get(body_id, "") for body_id in body_ids},
                    on_item_error,
                )
            )
            self.original_body_ids.update(body_ids)
        return expanded_order

    def replay_completed(
        self,
        ordered: list[dict[str, Any]],
        *,
        step_id: str,
        action: str,
        params: dict[str, Any],
        results: dict[str, dict[str, Any]],
        inputs: dict[str, Any],
        recorded_output: Any,
        failed_or_skipped: set[str],
        failed: set[str],
        emit_step: StepEmitter,
    ) -> list[dict[str, Any]]:
        """Re-resolve a checkpointed loop and expand only if its digest matches."""
        outcome = control_flow.run_control_step(action, params, results, inputs)
        if outcome["status"] == "ok" and outcome.get("output") == recorded_output:
            return self.expand_outcome(
                ordered, step_id, outcome,
                on_item_error=loop_item_error_mode(params),
            )
        results[step_id] = {
            "action": action,
            "status": "failed",
            "reason": "loop_replay_mismatch",
        }
        failed_or_skipped.add(step_id)
        failed.add(step_id)
        emit_step(
            {
                "step_id": step_id,
                "action": action,
                "status": "failed",
                "reason": "loop_replay_mismatch",
            }
        )
        return ordered

    def aggregate(
        self, results: dict[str, dict[str, Any]], *, failed: set[str] | None = None
    ) -> int:
        """Collapse clone results; returns the count of absorbed item errors."""
        absorbed = 0
        for body_ids, item_count, actions, on_item_error in reversed(self.expanded):
            absorbed += control_flow.aggregate_loop_results(
                results,
                body_ids,
                item_count,
                actions=actions,
                on_item_error=on_item_error,
                failed=failed,
            )
        return absorbed


def loop_item_error_mode(params: dict[str, Any]) -> str:
    """The loop's declared item-error mode; unknown values fail closed to ``fail``."""
    mode = params.get("on_item_error", "fail")
    return mode if mode in control_flow.LOOP_ITEM_ERROR_MODES else "fail"


# Windowed parallel iteration (graphon parity: parallel_nums). Bounded like
# graphon's default so a single loop cannot fan an unbounded number of
# concurrent dispatches at the kernel.
WORKFLOW_LOOP_MAX_PARALLEL = 10


def loop_parallel_window(params: dict[str, Any]) -> int:
    """The loop's declared parallel window, clamped; invalid fails closed to 1."""
    raw = params.get("parallel", 1)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 1
    return min(max(raw, 1), WORKFLOW_LOOP_MAX_PARALLEL)


def take_parallel_groups(
    ordered: list[dict[str, Any]],
    loop_idx: int,
    body_ids: list[str],
    item_count: int,
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]] | None:
    """Extract per-iteration clone groups for parallel execution.

    Clones sit immediately after the loop step, item-major (expand_loop's
    contract). Returns ``(ordered_without_clones, groups)`` - one group per
    item, body order preserved within it - or ``None`` when any clone is a
    control step: control routing stays on the sequential walk (fail-closed
    to the existing behavior; capability-only bodies are the map/for-each
    case parallelism exists for).
    """
    n = len(body_ids) * item_count
    clones = ordered[loop_idx + 1 : loop_idx + 1 + n]
    if len(clones) != n:
        return None
    if any(control_flow.is_control_step(c.get("action", "")) for c in clones):
        return None
    groups: list[list[dict[str, Any]]] = [[] for _ in range(item_count)]
    for clone in clones:
        _, _, suffix = clone["id"].rpartition("__")
        groups[int(suffix)].append(clone)
    remaining = ordered[: loop_idx + 1] + ordered[loop_idx + 1 + n :]
    return remaining, groups


async def run_parallel_iterations(
    groups: list[list[dict[str, Any]]],
    window: int,
    run_clone: Any,
) -> tuple[bool, bool]:
    """Run iteration groups concurrently, ``window`` at a time.

    Each group runs its clones SEQUENTIALLY in body order (they form that
    iteration's dependency chain); iterations interleave. ``run_clone(clone)``
    is the interpreter's per-clone executor returning ``(paused, stop_walk)``.
    A failed clone inside a group stops that group's remainder (the
    interpreter's parent gate records the skips); other iterations drain to
    completion before a checkpointed pause stops the outer walk - graphon's
    drain-then-stop shape. Returns aggregate ``(paused, stop_walk)``.
    """
    import asyncio

    sem = asyncio.Semaphore(max(window, 1))
    outcomes: list[tuple[bool, bool]] = []

    async def _one(group: list[dict[str, Any]]) -> None:
        async with sem:
            paused = False
            stop = False
            for clone in group:
                clone_paused, clone_stop = await run_clone(clone)
                paused = paused or clone_paused
                stop = stop or clone_stop
                if clone_paused or clone_stop:
                    break
            outcomes.append((paused, stop))

    await asyncio.gather(*(_one(g) for g in groups))
    return any(p for p, _ in outcomes), any(s for _, s in outcomes)


async def run_loop_clone(clone: dict[str, Any], env: dict[str, Any]) -> tuple[bool, bool]:
    """One loop-body clone under the walk's gates, for parallel iteration.

    Mirrors the sequential walk exactly: checkpoint replay, parent-failure
    gate, branch gate, then the governed capability dispatch. Clones are
    capability-only by construction (take_parallel_groups refuses control
    steps), and a capability-only body cannot produce benign skips, so the
    all-parents-benign gate is unreachable here. Returns ``(paused, stop)``.
    """
    cid = clone["id"]
    action = clone.get("action", "")
    _, step_params = selected_params(clone)
    results = env["results"]
    failed_or_skipped = env["failed_or_skipped"]
    emit = env["emit_step"]
    done = env["prior"].get(env["ck"](cid))
    if done is not None and done.status == "ok":
        results[cid] = {"action": action, "status": "ok",
                        "output": done.output, "replayed": True}
        emit({"step_id": cid, "action": action, "status": "ok", "replayed": True})
        return False, False
    if any(p in failed_or_skipped for p in clone.get("parents", []) or []):
        results[cid] = {"action": action, "status": "skipped", "reason": "parent_failed"}
        failed_or_skipped.add(cid)
        emit({"step_id": cid, "action": action, "status": "skipped", "reason": "parent_failed"})
        return False, False
    branch_ok, branch_reason = control_flow.branch_matches(clone, results)
    if not branch_ok:
        results[cid] = {"action": action, "status": "skipped", "reason": branch_reason}
        env["benign_skipped"].add(cid)
        emit({"step_id": cid, "action": action, "status": "skipped", "reason": branch_reason})
        return False, False
    emit({"step_id": cid, "action": action, "status": "running"})
    approval_id = done.hitl_request_id if done is not None and done.status == "paused" else None
    noun = action.split(".", 1)[0] if action else ""
    verb = action
    return await step_execution.run_capability_step(
        kernel=env["kernel"], executor=env["executor"], store=env["store"],
        wf=env["wf"], rid=env["rid"], run_ctx=env["run_ctx"],
        step=clone, step_id=cid, action=action, noun=noun, verb=verb,
        params=step_params or {}, approval_id=approval_id,
        results=results, failed_or_skipped=failed_or_skipped,
        failed=env["failed"], exceptions=env["exceptions"],
        emit_step=emit, ck=env["ck"],
    )


async def run_parallel_block(
    ordered: list[dict[str, Any]],
    idx: int,
    params: dict[str, Any],
    loops: "LoopWalk",
    env: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Execute a just-expanded loop's clones in parallel when declared.

    ``params.parallel > 1`` (clamped) opts a capability-only body into
    windowed concurrent iteration - graphon's parallel_nums model. Returns
    ``(ordered, paused, stop)``; when parallelism does not apply the clones
    stay in ``ordered`` and the sequential walk proceeds unchanged.
    """
    window = loop_parallel_window(params)
    if window <= 1 or not loops.expanded:
        return ordered, False, False
    body_ids, item_count, _actions, _mode = loops.expanded[-1]
    taken = take_parallel_groups(ordered, idx, body_ids, item_count)
    if taken is None:
        return ordered, False, False
    remaining, groups = taken
    paused, stop = await run_parallel_iterations(
        groups, window, lambda clone: run_loop_clone(clone, env)
    )
    return remaining, paused, stop
