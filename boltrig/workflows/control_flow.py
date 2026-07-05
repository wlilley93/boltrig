"""Control-plane step handling for the generic workflow interpreter.

The interpreter's default path dispatches each step's ``action`` as a
``<noun>.<verb>`` capability through ``kernel.invoke`` (the single chokepoint).
A handful of nouns are NOT capabilities, though - they are control-plane
routing the interpreter owns itself:

* ``trigger.start`` - the workflow entry point (a no-op passthrough of inputs).
* ``flow.end``      - a terminal marker (no-op).
* ``flow.branch``   - a conditional: evaluates a declarative predicate against
                      parent outputs and records a ``branch`` label; descendant
                      steps that declare a matching ``branch`` run, the rest skip.
* ``flow.loop``     - recognises an iteration source and records the item count
                      (full per-item body expansion is a later enhancement).
* ``code.run``      - recognised but NOT executed: arbitrary script execution is
                      unsafe without a sandbox, so it records its intent only.

Handling these here (rather than via ``kernel.invoke``) is consistent with the
one-chokepoint doctrine: that doctrine governs EXTERNAL actions and capability
dispatch, not internal control routing (the topological walk itself is the
precedent). No control step can reach the network, the DB, or a credential.

Predicates are declarative (``left``/``op``/``right``) so there is no ``eval``
and no injection surface. References are ``$<step_id>.<dotted.path>`` strings
resolved against a parent step's recorded output.
"""

from __future__ import annotations

from typing import Any

# Nouns the interpreter resolves locally instead of dispatching as capabilities.
CONTROL_NOUNS = frozenset({"trigger", "flow", "code"})

_MISSING = object()


def split_action(action: str) -> tuple[str, str]:
    """``"<noun>.<verb>"`` -> ``("<noun>", "<verb>")``; empty action -> ``("", "")``."""
    if not action:
        return "", ""
    noun, _, verb = action.partition(".")
    return noun, verb


def is_control_step(action: str) -> bool:
    """True when the action's noun is a control-plane noun the interpreter owns."""
    noun, _ = split_action(action)
    return noun in CONTROL_NOUNS


def resolve_ref(value: Any, results: dict[str, dict[str, Any]]) -> Any:
    """Resolve a ``$<step_id>.<path>`` reference against parent outputs.

    A non-string or a string not starting with ``$`` is returned unchanged (a
    literal). An unresolvable reference yields ``None`` (fail-open: a branch on
    a missing field treats the field as null rather than crashing the run).
    """
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    path = value[1:].split(".")
    step_id = path[0]
    record = results.get(step_id)
    if record is None:
        return None
    node: Any = record
    for part in path[1:]:
        if isinstance(node, dict):
            node = node.get(part, _MISSING)
        elif isinstance(node, list) and part.isdigit():
            idx = int(part)
            node = node[idx] if 0 <= idx < len(node) else _MISSING
        else:
            return None
        if node is _MISSING:
            return None
    return node


def _compare(left: Any, op: str, right: Any) -> bool:
    """Evaluate a declarative comparison. Unknown ops are false (fail-closed)."""
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "exists":
        return left is not None
    try:
        if op == "gt":
            return left > right
        if op == "lt":
            return left < right
        if op == "gte":
            return left >= right
        if op == "lte":
            return left <= right
        if op == "in":
            return left in (right or [])
        if op == "contains":
            return right in (left or [])
    except TypeError:
        return False
    return False


def eval_predicate(params: dict[str, Any], results: dict[str, dict[str, Any]]) -> bool:
    """Evaluate a branch predicate ``{left, op, right}`` to a boolean.

    Defaults to True when no predicate is declared (an unconditional branch),
    so a ``flow.branch`` with no params still partitions cleanly.
    """
    if not params:
        return True
    if "op" not in params:
        # A bare truthy/value form: {value: <ref>} branches on truthiness.
        if "value" in params:
            return bool(resolve_ref(params["value"], results))
        return True
    left = resolve_ref(params.get("left"), results)
    op = str(params.get("op", "eq"))
    right = resolve_ref(params.get("right"), results)
    return _compare(left, op, right)


def resolve_items(params: dict[str, Any], results: dict[str, dict[str, Any]]) -> list[Any]:
    """Resolve the iteration source for a loop: a literal list or a $ref."""
    items = params.get("items", _MISSING)
    if items is _MISSING:
        items = params.get("items_from", _MISSING)
        if items is not _MISSING:
            items = resolve_ref(items, results)
    if isinstance(items, list):
        return items
    return []


def run_control_step(
    action: str,
    params: dict[str, Any],
    results: dict[str, dict[str, Any]],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Execute a control-plane step locally. Returns ``{status, output}``.

    ``status`` is ``"ok"`` for every recognised control kind (they cannot fail
    a run); an unrecognised control action records ``skipped`` so the caller
    can treat it uniformly. ``output`` carries the step's record (a branch
    label, a loop item count, the passthrough inputs, etc.).
    """
    noun, verb = split_action(action)
    if noun == "trigger" and verb == "start":
        return {"status": "ok", "output": {"entry": True, "inputs": dict(inputs or {})}}
    if noun == "flow" and verb == "end":
        return {"status": "ok", "output": {"terminal": True}}
    if noun == "flow" and verb == "branch":
        outcome = "true" if eval_predicate(params, results) else "false"
        return {"status": "ok", "output": {"branch": outcome}}
    if noun == "flow" and verb == "loop":
        items = resolve_items(params, results)
        return {
            "status": "ok",
            "output": {"items": len(items), "count": len(items)},
            "_items": items,
        }
    if noun == "code" and verb == "run":
        # Arbitrary script execution is unsafe without a sandbox; record intent.
        script = params.get("script") or params.get("code") or ""
        return {
            "status": "ok",
            "output": {
                "executed": False,
                "reason": "code execution disabled (no sandbox configured)",
                "script_len": len(str(script)),
            },
        }
    # A control noun with an unknown verb: recognised as control but unsupported.
    return {"status": "skipped", "output": {"reason": f"unknown control action {action}"}}


def branch_matches(
    step: dict[str, Any], results: dict[str, dict[str, Any]]
) -> tuple[bool, str | None]:
    """Whether a step's declared ``branch`` is satisfied by its parents' outputs.

    Returns ``(ok, reason)``. A step with no ``branch`` declaration always
    satisfies (ok=True). A branched step must match the branch label of EVERY
    parent that produced one; a mismatch yields ok=False with a reason.
    """
    declared = step.get("branch")
    if declared is None:
        return True, None
    for parent in step.get("parents", []) or []:
        pout = (results.get(parent) or {}).get("output") or {}
        produced = pout.get("branch")
        if produced is not None and produced != declared:
            return False, "branch_mismatch"
    return True, None


# --- Loop body iteration (flow.loop) -----------------------------------------
# A flow.loop step with a resolved items list iterates its body: the maximal
# descendant sub-graph whose every step has ALL its parents inside {loop} u body.
# The body is cloned once per item; clones carry __loop_item/__loop_index and
# parents rewired to the same iteration's clones. A step that mixes a body parent
# with an external parent falls outside the body (it would be ambiguous to
# iterate) and is skipped with a clear reason. Self-contained bodies iterate
# fully; this covers the common map/for-each pattern.


def loop_body_ids(steps: list[dict[str, Any]], loop_id: str) -> list[str]:
    """The iterable body of ``loop_id``: descendant step ids (topo order) whose
    parents are all inside {loop_id} u the body itself."""
    by_id = {s["id"]: s for s in steps}
    if loop_id not in by_id:
        return []
    children: dict[str, list[str]] = {sid: [] for sid in by_id}
    for s in steps:
        for p in s.get("parents", []) or []:
            if p in children:
                children[p].append(s["id"])
    body: list[str] = []
    frontier = list(children.get(loop_id, []))
    while frontier:
        sid = frontier.pop(0)
        if sid in body:
            continue
        parents = by_id[sid].get("parents", []) or []
        if all(p == loop_id or p in body for p in parents):
            body.append(sid)
            frontier.extend(children.get(sid, []))
    return body


def expand_loop(
    ordered: list[dict[str, Any]], loop_id: str, items: list[Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(new_ordered, body_ids)`` with ``loop_id``'s body cloned once per
    item. Body originals are removed and replaced by per-item clones placed right
    after the loop step. When items is empty or there is no body, returns the
    list unchanged with an empty body.
    """
    body = loop_body_ids(ordered, loop_id)
    if not body or not items:
        return ordered, []
    by_id = {s["id"]: s for s in ordered}
    clones: list[dict[str, Any]] = []
    for k, item in enumerate(items):
        for sid in body:
            orig = by_id[sid]
            parents = [
                p if (p == loop_id or p not in body) else f"{p}__{k}"
                for p in (orig.get("parents") or [])
            ]
            clone = dict(orig)
            clone["id"] = f"{sid}__{k}"
            clone["parents"] = parents
            params = dict(orig.get("params") or {})
            params["__loop_item"] = item
            params["__loop_index"] = k
            clone["params"] = params
            clones.append(clone)
    new_ordered: list[dict[str, Any]] = []
    for s in ordered:
        if s["id"] == loop_id:
            new_ordered.append(s)
            new_ordered.extend(clones)
        elif s["id"] in body:
            continue
        else:
            new_ordered.append(s)
    return new_ordered, body


def aggregate_loop_results(
    results: dict[str, dict[str, Any]],
    body_ids: list[str],
    item_count: int,
) -> None:
    """Collapse per-item clone results back onto each original body step id so the
    run record (keyed by original step id) reflects the iteration. Sets
    ``results[id] = {status, output: {iterations, count}}`` from its clones."""
    for sid in body_ids:
        iterations: list[Any] = []
        all_ok = True
        for k in range(item_count):
            clone = results.pop(f"{sid}__{k}", None)
            if clone is None:
                all_ok = False
                continue
            if clone.get("status") != "ok":
                all_ok = False
            iterations.append(clone.get("output"))
        results[sid] = {
            "status": "ok" if all_ok else "failed",
            "output": {"iterations": iterations, "count": item_count},
        }

