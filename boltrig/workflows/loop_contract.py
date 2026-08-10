"""Closed declarative contract for bounded ``flow.loop`` expansion.

A loop body step may bind the current item or zero-based index into an existing
top-level capability parameter:

```
{"params": {"title": null}, "loop_bindings": {"title": "item"}}
```

Bindings replace whole JSON values, never interpolate strings or evaluate
expressions.  The resulting params still enter the ordinary dispatcher schema
validator, grant check, HITL gate, idempotency layer and audit path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from boltrig.models.libraries import (
    WORKFLOW_LOOP_BINDING_KEY_PATTERN,
    WORKFLOW_LOOP_BINDING_SOURCES,
    WORKFLOW_LOOP_MAX_BINDINGS,
    WORKFLOW_LOOP_MAX_BOUND_BYTES,
    WORKFLOW_LOOP_MAX_ITEMS,
)

_BINDING_KEY = re.compile(WORKFLOW_LOOP_BINDING_KEY_PATTERN)
_CLONE_ID = re.compile(r".+__[0-9]+$")
_MISSING = object()


@dataclass(frozen=True)
class LoopContractIssue:
    """Value-free validation finding safe to expose in a run receipt."""

    step_id: str
    reason: str


class LoopItemsError(ValueError):
    """Resolved iteration values could not satisfy the bounded JSON contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ResolvedLoopItems:
    items: list[Any]
    overflow: int
    digest: str


def selected_params(step: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Mirror interpreter precedence: non-empty params, otherwise with, then params."""
    params = step.get("params")
    with_params = step.get("with")
    if isinstance(params, dict) and params:
        return "params", params
    if isinstance(with_params, dict):
        return "with", with_params
    if isinstance(params, dict):
        return "params", params
    return "params", None


def loop_body_ids(steps: list[dict[str, Any]], loop_id: str) -> list[str]:
    """Return the self-contained descendant body of a loop in stable DAG order."""
    by_id = {step.get("id"): step for step in steps}
    if loop_id not in by_id:
        return []
    children: dict[str, list[str]] = {step_id: [] for step_id in by_id if isinstance(step_id, str)}
    for step in steps:
        step_id = step.get("id")
        if not isinstance(step_id, str):
            continue
        for parent in step.get("parents", []) or []:
            if parent in children:
                children[parent].append(step_id)
    body: list[str] = []
    frontier = list(children.get(loop_id, []))
    while frontier:
        step_id = frontier.pop(0)
        if step_id in body:
            continue
        parents = by_id[step_id].get("parents", []) or []
        if all(parent == loop_id or parent in body for parent in parents):
            body.append(step_id)
            frontier.extend(children.get(step_id, []))
    return body


def _ancestors(
    step_id: str,
    by_id: dict[str, dict[str, Any]],
    *,
    visiting: frozenset[str] = frozenset(),
) -> set[str]:
    if step_id in visiting:
        return set()
    parents = by_id[step_id].get("parents", []) or []
    result: set[str] = set()
    for parent in parents:
        if parent not in by_id:
            continue
        result.add(parent)
        result.update(_ancestors(parent, by_id, visiting=visiting | {step_id}))
    return result


def _items_ref_step(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("$"):
        return None
    path = value[1:].split(".")
    if len(path) < 2 or not path[0] or path[1] != "output":
        return None
    if any(not part for part in path):
        return None
    return path[0]


def resolve_bounded_items(items: list[Any]) -> ResolvedLoopItems:
    """Cap, size-check and digest the exact ordered values used for expansion."""
    selected = copy.deepcopy(items[:WORKFLOW_LOOP_MAX_ITEMS])
    overflow = max(0, len(items) - len(selected))
    try:
        canonical = json.dumps(
            selected,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LoopItemsError("loop_items_not_json") from exc
    if len(canonical) > WORKFLOW_LOOP_MAX_BOUND_BYTES:
        raise LoopItemsError("loop_items_too_large")
    return ResolvedLoopItems(
        items=selected,
        overflow=overflow,
        digest=hashlib.sha256(canonical).hexdigest(),
    )


def _validated_steps(
    definition: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    LoopContractIssue | None,
]:
    raw_steps = definition.get("steps", [])
    if not isinstance(raw_steps, list):
        return [], {}, LoopContractIssue("", "loop_steps_must_be_array")
    steps: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for step in raw_steps:
        if not isinstance(step, dict):
            return [], {}, LoopContractIssue("", "loop_step_must_be_object")
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id or step_id in by_id:
            return [], {}, LoopContractIssue("", "loop_step_id_invalid")
        parents = step.get("parents", [])
        if not isinstance(parents, list) or any(not isinstance(parent, str) for parent in parents):
            return [], {}, LoopContractIssue(step_id, "loop_parents_invalid")
        steps.append(step)
        by_id[step_id] = step
    return steps, by_id, None


def validate_loop_contract(definition: dict[str, Any]) -> LoopContractIssue | None:
    """Return the first closed loop-contract violation, without reading values."""
    raw_steps = definition.get("steps", [])
    if not isinstance(raw_steps, list):
        return LoopContractIssue("", "loop_steps_must_be_array")
    if not any(
        isinstance(step, dict) and (step.get("action") == "flow.loop" or "loop_bindings" in step)
        for step in raw_steps
    ):
        return None
    steps, by_id, issue = _validated_steps(definition)
    if issue is not None:
        return issue
    if any(_CLONE_ID.fullmatch(step["id"]) is not None for step in steps):
        return LoopContractIssue("", "loop_step_id_reserved")

    loop_bodies: dict[str, list[str]] = {}
    for step in steps:
        if step.get("action") != "flow.loop":
            continue
        step_id = step["id"]
        ancestors = _ancestors(step_id, by_id)
        if any(by_id[parent].get("action") == "flow.loop" for parent in ancestors):
            return LoopContractIssue(step_id, "nested_loop_not_supported")
        _, params = selected_params(step)
        if params is None:
            return LoopContractIssue(step_id, "loop_params_must_be_object")
        has_items = "items" in params
        has_ref = "items_from" in params
        if has_items == has_ref:
            return LoopContractIssue(step_id, "loop_requires_one_item_source")
        # ``on_item_error`` (graphon-parity item error modes) fails loudly at
        # definition time rather than silently falling back at the next run.
        mode = params.get("on_item_error", "fail")
        if mode not in ("fail", "continue", "drop"):
            return LoopContractIssue(step_id, "loop_on_item_error_invalid")
        if has_items:
            if not isinstance(params.get("items"), list):
                return LoopContractIssue(step_id, "loop_items_must_be_array")
            try:
                resolve_bounded_items(params["items"])
            except LoopItemsError as exc:
                return LoopContractIssue(step_id, exc.reason)
        else:
            source_step = _items_ref_step(params.get("items_from"))
            if source_step is None:
                return LoopContractIssue(step_id, "loop_items_from_invalid")
            if source_step not in ancestors:
                return LoopContractIssue(step_id, "loop_items_from_must_reference_ancestor")
        body = loop_body_ids(steps, step_id)
        if any(by_id[body_id].get("action") == "flow.loop" for body_id in body):
            return LoopContractIssue(step_id, "nested_loop_not_supported")
        loop_bodies[step_id] = body

    for step in steps:
        if "loop_bindings" not in step:
            continue
        step_id = step["id"]
        bindings = step.get("loop_bindings")
        if not isinstance(bindings, dict):
            return LoopContractIssue(step_id, "loop_bindings_must_be_object")
        if not bindings:
            continue
        containing = [loop_id for loop_id, body in loop_bodies.items() if step_id in body]
        if len(containing) != 1:
            return LoopContractIssue(step_id, "loop_bindings_require_one_loop_body")
        if len(bindings) > WORKFLOW_LOOP_MAX_BINDINGS:
            return LoopContractIssue(step_id, "loop_binding_limit_exceeded")
        _, params = selected_params(step)
        if params is None:
            return LoopContractIssue(step_id, "loop_binding_params_must_be_object")
        for target, source in bindings.items():
            if not isinstance(target, str) or _BINDING_KEY.fullmatch(target) is None:
                return LoopContractIssue(step_id, "loop_binding_target_invalid")
            if source not in WORKFLOW_LOOP_BINDING_SOURCES:
                return LoopContractIssue(step_id, "loop_binding_source_invalid")
            if target not in params:
                return LoopContractIssue(step_id, "loop_binding_target_missing")
    return None


def require_valid_loop_contract(definition: dict[str, Any]) -> None:
    issue = validate_loop_contract(definition)
    if issue is not None:
        raise ValueError(f"invalid loop contract: {issue.reason}")


def bind_loop_params(
    step: dict[str, Any],
    *,
    item: Any,
    index: int,
) -> dict[str, Any]:
    """Deep-copy one body step and apply its already-validated bindings."""
    clone = copy.deepcopy(step)
    bindings = clone.get("loop_bindings")
    if not isinstance(bindings, dict) or not bindings:
        return clone
    field, params = selected_params(clone)
    if params is None:
        raise ValueError("invalid loop contract: loop_binding_params_must_be_object")
    bound = dict(params)
    for target, source in bindings.items():
        bound[target] = copy.deepcopy(item) if source == "item" else index
    clone[field] = bound
    return clone
