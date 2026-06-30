"""The generic workflow interpreter (Round Seven, control-plane gap 3).

Before this, a stored ``WorkflowDefinition`` was authored, persisted, matched and
"triggered" as an opaque blob: nothing walked its ``definition["steps"]`` and
ran them. ``WorkflowLibrary.trigger`` recorded one boundary for the whole run.
That meant new behaviour still needed code (a hand-registered Hatchet workflow),
not data.

This interpreter closes that gap. It walks a definition's steps in dependency
order (honouring each step's ``parents``) and dispatches each step's ``action``
as its OWN durable boundary through the kernel chokepoint. Two properties are
load-bearing:

* **One governed path (P2).** Every step is dispatched via ``kernel.invoke`` -
  the single chokepoint that already routes a verb to an adapter OR an agent by
  ``binding.target_type``. So a step inherits validation, grant-check, the
  consequence/HITL gate, idempotency, and audit for free; a step can neither
  escalate nor bypass governance (SEC-50). There is no second dispatch path.

* **Per-step durability.** Each step runs inside its own
  ``executor.run_step("workflow:<wf>:<step>", ...)`` boundary, so under Hatchet
  each step individually gets retry/resume, not one opaque enqueue (FR-CTL-02).

A step that fails (an ungranted verb, an unbound action, a backend error) is
recorded and its descendants are skipped; the run never crashes the fleet (P9).
A high-consequence step that the HITL gate holds is recorded as ``paused``.

The interpreter is generic: a step's ``action`` is a fully-qualified verb id
(``"<noun>.<verb>"``); what it resolves to (adapter or agent) is the registry's
business, not the interpreter's. Imports only models; severable from the kernel.
"""

from __future__ import annotations

from typing import Any

from nankle.models import InvocationContext, NankleError


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
) -> dict[str, Any]:
    """Execute a ``WorkflowDefinition``'s steps and return a run record.

    Each step is dispatched through ``kernel.invoke`` inside its own durable
    boundary. The returned record carries per-step status/output so the run is
    observable; the overall ``status`` is ``completed`` (all ok), ``paused`` (a
    HITL gate held a step), or ``failed`` (a step errored / was skipped).
    """
    definition = wf.definition or {}
    steps = list(definition.get("steps", []) or [])
    rid = run_id or (executor.new_run_id() if executor is not None else context.run_id)

    ordered, unrunnable = _topological_order(steps)
    results: dict[str, dict[str, Any]] = {}
    failed_or_skipped: set[str] = {s["id"] for s in unrunnable}
    for s in unrunnable:
        results[s["id"]] = {"action": s.get("action"), "status": "skipped",
                            "reason": "missing_parent_or_cycle"}

    paused = False
    for step in ordered:
        step_id = step["id"]
        # A step whose parent failed/was skipped cannot run (fail-closed).
        if any(p in failed_or_skipped for p in step.get("parents", []) or []):
            results[step_id] = {"action": step.get("action"), "status": "skipped",
                                "reason": "parent_failed"}
            failed_or_skipped.add(step_id)
            continue

        action = step.get("action", "")
        noun, verb = _split_action(action)
        params = step.get("params") or step.get("with") or {}

        async def _dispatch(noun=noun, verb=verb, params=params) -> dict[str, Any]:
            return await kernel.invoke(noun, verb, params, context)

        boundary = f"workflow:{wf.id}:{step_id}"
        try:
            if executor is not None:
                output = await executor.run_step(boundary, _dispatch, run_id=rid)
            else:
                output = await _dispatch()
            results[step_id] = {"action": action, "status": "ok", "output": output}
        except NankleError as exc:
            reason = getattr(exc, "reason", type(exc).__name__)
            # A held HITL gate is a pause, not a failure - the run can resume.
            status = "paused" if reason in {"pending_human", "approval_required"} else "failed"
            if status == "paused":
                paused = True
            else:
                failed_or_skipped.add(step_id)
            results[step_id] = {"action": action, "status": status, "reason": reason}
        except Exception as exc:  # an adapter bug must not crash the fleet (P9)
            failed_or_skipped.add(step_id)
            results[step_id] = {"action": action, "status": "error",
                                "reason": type(exc).__name__}

    if paused:
        overall = "paused"
    elif failed_or_skipped:
        overall = "failed"
    else:
        overall = "completed"
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
