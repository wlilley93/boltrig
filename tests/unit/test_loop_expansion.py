"""Pure unit tests for flow.loop body expansion (no kernel/store).

The expansion is a pure list transform: it clones a loop's body once per item,
rewires parents to the same iteration's clones, and the aggregation collapses
clone results back onto the original body step ids. Tested in isolation so the
interpreter integration can rely on these guarantees.
"""

from __future__ import annotations

from boltrig.workflows.control_flow import (
    aggregate_loop_results,
    expand_loop,
    loop_body_ids,
)


def _step(sid, parents=None, action="ticket.create", **extra):
    s = {"id": sid, "parents": parents or [], "action": action}
    s.update(extra)
    return s


def test_loop_body_is_self_contained_descendants():
    steps = [
        _step("loop", [], "flow.loop"),
        _step("a", ["loop"]),
        _step("b", ["a"]),
        _step("c", ["b"]),
        _step("after", ["c"]),
    ]
    # a, b, c, after all have parents only inside {loop} u body -> all iterate.
    # A flow.loop iterates its full downstream sub-graph; a step that should run
    # once after the loop must sit outside the loop's dependency chain.
    assert loop_body_ids(steps, "loop") == ["a", "b", "c", "after"]


def test_loop_body_excludes_mixed_parent_steps():
    steps = [
        _step("loop", [], "flow.loop"),
        _step("ext", [], action="ticket.create"),
        _step("a", ["loop"]),
        _step("mixed", ["a", "ext"]),  # depends on body + external -> NOT body
    ]
    assert loop_body_ids(steps, "loop") == ["a"]


def test_expand_clones_body_once_per_item_and_rewires_parents():
    steps = [
        _step("loop", [], "flow.loop"),
        _step("a", ["loop"], action="ticket.create"),
        _step("b", ["a"], action="ticket.update"),
    ]
    new, body = expand_loop(steps, "loop", ["x", "y", "z"])
    assert body == ["a", "b"]
    ids = [s["id"] for s in new]
    # loop kept, body originals removed, 6 clones inserted after the loop
    assert ids[0] == "loop"
    assert "a" not in ids and "b" not in ids
    assert "a__0" in ids and "b__2" in ids
    by = {s["id"]: s for s in new}
    # parent rewiring: a__1's parent is the loop; b__1's parent is a__1 (same iter)
    assert by["a__1"]["parents"] == ["loop"]
    assert by["b__1"]["parents"] == ["a__1"]
    # item injection
    assert by["a__2"]["params"]["__loop_item"] == "z"
    assert by["a__2"]["params"]["__loop_index"] == 2


def test_expand_no_items_returns_unchanged():
    steps = [_step("loop", [], "flow.loop"), _step("a", ["loop"])]
    new, body = expand_loop(steps, "loop", [])
    assert new is steps and body == []


def test_aggregate_collapses_clones_onto_originals():
    results = {
        "loop": {"status": "ok", "output": {"count": 2}},
        "a__0": {"status": "ok", "output": {"id": "t0"}},
        "a__1": {"status": "ok", "output": {"id": "t1"}},
    }
    aggregate_loop_results(results, ["a"], 2)
    assert "a__0" not in results and "a__1" not in results
    assert results["a"]["status"] == "ok"
    assert results["a"]["output"]["count"] == 2
    assert results["a"]["output"]["iterations"] == [{"id": "t0"}, {"id": "t1"}]


def test_aggregate_marks_failed_if_any_clone_failed():
    results = {
        "a__0": {"status": "ok", "output": 1},
        "a__1": {"status": "failed", "reason": "x"},
    }
    aggregate_loop_results(results, ["a"], 2)
    assert results["a"]["status"] == "failed"
