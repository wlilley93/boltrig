"""Runtime bookkeeping for validated ``flow.loop`` steps.

The generic interpreter owns the topological walk.  This helper owns only loop
preflight receipts, deterministic expansion/replay and result aggregation, so
the interpreter does not grow a second workflow engine inside itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import control_flow, run_events
from .loop_contract import validate_loop_contract

StepEmitter = Callable[[dict[str, Any]], None]
Expansion = tuple[list[str], int, dict[str, str]]


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
            return self.expand_outcome(ordered, step_id, outcome)
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

    def aggregate(self, results: dict[str, dict[str, Any]]) -> None:
        for body_ids, item_count, actions in reversed(self.expanded):
            control_flow.aggregate_loop_results(
                results,
                body_ids,
                item_count,
                actions=actions,
            )
