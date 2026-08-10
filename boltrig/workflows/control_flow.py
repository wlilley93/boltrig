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
* ``flow.loop``     - expands a bounded self-contained body for each item and
                      applies closed item/index bindings to capability params.
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

from .loop_contract import (
    LoopItemsError,
    bind_loop_params,
    loop_body_ids,
    resolve_bounded_items,
)

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
    if op in {"not_exists", "is_null"}:
        return left is None
    if op == "not_null":
        return left is not None
    if op == "empty":
        return not left
    if op == "not_empty":
        return bool(left)
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
        if op == "not_in":
            return left not in (right or [])
        if op == "contains":
            return right in (left or [])
        if op == "not_contains":
            return right not in (left or [])
        if op == "starts_with":
            return isinstance(left, str) and isinstance(right, str) and left.startswith(right)
        if op == "ends_with":
            return isinstance(left, str) and isinstance(right, str) and left.endswith(right)
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


def _eval_case(case: dict[str, Any], results: dict[str, dict[str, Any]]) -> bool:
    """Evaluate one multi-case branch case: a condition list joined and/or.

    A case with no (or an empty) ``conditions`` list matches unconditionally -
    the authored "else"/"always" arm. Malformed conditions evaluate false
    through ``_compare``'s fail-closed default; a malformed case never matches.
    """
    conditions = case.get("conditions")
    if not conditions:
        return True
    if not isinstance(conditions, list):
        return False
    verdicts: list[bool] = []
    for cond in conditions:
        if not isinstance(cond, dict):
            return False
        left = resolve_ref(cond.get("left"), results)
        op = str(cond.get("op", "eq"))
        right = resolve_ref(cond.get("right"), results)
        verdicts.append(_compare(left, op, right))
    joiner = str(case.get("logical_operator", "and"))
    return any(verdicts) if joiner == "or" else all(verdicts)


def select_branch_label(params: dict[str, Any], results: dict[str, dict[str, Any]]) -> str:
    """Pick the branch label a ``flow.branch`` step records.

    Two authored shapes:
    * legacy single predicate (``left``/``op``/``right`` or ``value``) ->
      ``"true"``/``"false"``;
    * multi-case (``cases: [{label, logical_operator, conditions}]``) ->
      first matching case's label, in declaration order, else
      ``default_label`` (``"false"`` when unset - the legacy no-match label,
      so a two-case migration keeps its else-arm wiring).
    A ``cases`` value that is not a list falls back to the legacy predicate;
    a case without a usable string label never matches (fail-closed).
    """
    cases = params.get("cases")
    if isinstance(cases, list):
        for case in cases:
            if not isinstance(case, dict):
                continue
            label = case.get("label")
            if not isinstance(label, str) or not label:
                continue
            if _eval_case(case, results):
                return label
        default = params.get("default_label")
        return default if isinstance(default, str) and default else "false"
    return "true" if eval_predicate(params, results) else "false"


def resolve_items(params: dict[str, Any], results: dict[str, dict[str, Any]]) -> list[Any] | None:
    """Resolve a validated literal list or ancestor-output reference."""
    items = params.get("items", _MISSING)
    if items is _MISSING:
        items = params.get("items_from", _MISSING)
        if items is not _MISSING:
            items = resolve_ref(items, results)
    if isinstance(items, list):
        return items
    return None


def run_control_step(
    action: str,
    params: dict[str, Any],
    results: dict[str, dict[str, Any]],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Execute a control-plane step locally. Returns ``{status, output}``.

    ``status`` is ``"ok"`` for recognised control kinds except a dynamic loop
    whose runtime items violate the bounded contract; an unrecognised control
    action records ``skipped``. ``output`` carries the step's record (a branch
    label, a loop item count and digest, the passthrough inputs, etc.).
    """
    noun, verb = split_action(action)
    if noun == "trigger" and verb == "start":
        return {"status": "ok", "output": {"entry": True, "inputs": dict(inputs or {})}}
    if noun == "flow" and verb == "end":
        return {"status": "ok", "output": {"terminal": True}}
    if noun == "flow" and verb == "branch":
        return {"status": "ok", "output": {"branch": select_branch_label(params, results)}}
    if noun == "flow" and verb == "loop":
        items = resolve_items(params, results)
        if items is None:
            return {
                "status": "failed",
                "output": {"reason": "loop_items_unavailable"},
            }
        try:
            bounded = resolve_bounded_items(items)
        except LoopItemsError as exc:
            return {"status": "failed", "output": {"reason": exc.reason}}
        output: dict[str, Any] = {
            "items": len(bounded.items),
            "count": len(bounded.items),
            "items_digest": bounded.digest,
        }
        if bounded.overflow:
            # Excess items beyond the canonical cap are never dispatched: recorded
            # as skipped so the cap is observable in the run record.
            output["skipped_overflow"] = bounded.overflow
        return {"status": "ok", "output": output, "_items": bounded.items}
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
# The body is cloned once per item; closed ``loop_bindings`` replace whole
# top-level params with the typed item/index, and parents are rewired to the
# same iteration's clones. A step that mixes a body parent
# with an external parent falls outside the body (it would be ambiguous to
# iterate) and is skipped with a clear reason. Self-contained bodies iterate
# fully; this covers the common map/for-each pattern.

# Items come from prior step output (adapter/agent-influenced), so an unbounded
# list would fan out into an unbounded number of dispatches per run: cap the
# iterations a single flow.loop expands into and record the excess as skipped.


def expand_loop(
    ordered: list[dict[str, Any]], loop_id: str, items: list[Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(new_ordered, body_ids)`` with ``loop_id``'s body cloned once per
    item. Body originals are removed and replaced by per-item clones placed right
    after the loop step. An empty item list removes the body and aggregates zero
    iterations; only a loop with no body returns the list unchanged.
    """
    body = loop_body_ids(ordered, loop_id)
    if not body:
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
            clone = bind_loop_params(orig, item=item, index=k)
            clone["id"] = f"{sid}__{k}"
            clone["parents"] = parents
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


# How a flow.loop treats a failed body iteration (``params.on_item_error``):
# ``fail`` (default) fails the aggregate; ``continue`` keeps a ``None``
# placeholder at the item's index; ``drop`` omits the item from the output.
LOOP_ITEM_ERROR_MODES = frozenset({"fail", "continue", "drop"})


def aggregate_loop_results(
    results: dict[str, dict[str, Any]],
    body_ids: list[str],
    item_count: int,
    *,
    actions: dict[str, str] | None = None,
    on_item_error: str = "fail",
    failed: set[str] | None = None,
) -> int:
    """Collapse per-item clone results back onto each original body step id so the
    run record (keyed by original step id) reflects the iteration. Sets
    ``results[id] = {status, output: {iterations, count}}`` from its clones.

    Under ``continue``/``drop`` an errored iteration is absorbed: the aggregate
    stays ``ok``, the clone's failure is removed from ``failed`` (it no longer
    fails the run), and the absorbed-error count is returned so the run record
    can surface it as ``exceptions_count`` (partial success stays observable,
    never hidden). ``exception``-status clones (a step-level error strategy
    already absorbed the failure) count as delivered in every mode.
    """
    absorbed = 0
    for sid in body_ids:
        iterations: list[Any] = []
        errored: list[int] = []
        for k in range(item_count):
            clone = results.pop(f"{sid}__{k}", None)
            delivered = clone is not None and clone.get("status") in {"ok", "exception"}
            if not delivered:
                errored.append(k)
                if on_item_error != "fail" and failed is not None:
                    failed.discard(f"{sid}__{k}")
                if on_item_error == "drop":
                    continue
                if on_item_error == "continue":
                    iterations.append(None)
                elif clone is not None:
                    iterations.append(clone.get("output"))
                continue
            iterations.append(clone.get("output"))
        status = "ok" if (not errored or on_item_error != "fail") else "failed"
        output: dict[str, Any] = {"iterations": iterations, "count": item_count}
        if errored and on_item_error != "fail":
            # Honesty (US-FLT-07 posture): absorbed errors are visible in the
            # aggregate, not silently swallowed.
            output["errors"] = len(errored)
            output["errored_indexes"] = errored
            absorbed += len(errored)
        results[sid] = {
            "action": (actions or {}).get(sid),
            "status": status,
            "output": output,
        }
    return absorbed
