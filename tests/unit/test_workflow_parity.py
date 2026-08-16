"""Graphon-parity control-flow semantics for the workflow interpreter.

Covers the DAG-parity additions (feat/workflow-dag-parity):

* OR-join: a merge node after a two-arm branch runs exactly once when one arm
  was taken and the other benignly skipped; it skips only when EVERY parent
  arm was skipped. Failure lineage still poisons descendants (fail-closed).
* Multi-case ``flow.branch`` with first-match-wins labels and the expanded
  declarative operator set.
* Per-step error strategies (``on_error: branch | default``) and bounded
  per-step retry, with ``exceptions_count`` partial-success reporting.
* ``flow.loop`` item error modes (``on_item_error: continue | drop``).

The interpreter tests use a stub kernel (the interpreter only needs
``kernel.invoke``); the control_flow tests are pure.
"""

from __future__ import annotations


from boltrig.models import (
    BoltrigError,
    GrantSet,
    InvocationContext,
    WorkflowDefinition,
    WorkflowSource,
)
from boltrig.workflows.control_flow import (
    _compare,
    aggregate_loop_results,
    select_branch_label,
)
from boltrig.workflows.interpreter import run_workflow_definition

T = "acme"


class _StubError(BoltrigError):
    reason = "backend_unavailable"


class StubKernel:
    """Minimal kernel: scripted per-verb outcomes, call counting, no relay."""

    def __init__(self, script=None):
        # script: verb -> list of outcomes; an Exception instance raises, else returns.
        self.script = script or {}
        self.calls: list[str] = []

    async def invoke(self, noun, verb, params, context, *, idempotency_key=None, approval_id=None):
        self.calls.append(verb)
        outcomes = self.script.get(verb)
        if outcomes:
            outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
            if isinstance(outcome, Exception):
                raise outcome
            return dict(outcome)
        return {"done": verb}


def _wf(steps):
    return WorkflowDefinition(
        id="wf-parity",
        tenant_id=T,
        version="1.0.0",
        source=WorkflowSource.PRECREATED,
        definition={"name": "parity", "version": "1", "steps": steps},
        intent_tags=[],
    )


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="u", run_id="run-parity")


async def _run(kernel, steps, inputs=None):
    return await run_workflow_definition(kernel, _wf(steps), inputs or {}, _ctx())


def _by_id(record):
    return {s["id"]: s for s in record["steps"]}


# --- operators ----------------------------------------------------------------


def test_expanded_operators():
    assert _compare("abcdef", "starts_with", "abc")
    assert not _compare("abcdef", "starts_with", "def")
    assert _compare("abcdef", "ends_with", "def")
    assert _compare("b", "not_in", ["a", "c"])
    assert not _compare("a", "not_in", ["a", "c"])
    assert _compare(["a", "c"], "not_contains", "b")
    assert _compare([], "empty", None)
    assert _compare("", "empty", None)
    assert _compare([1], "not_empty", None)
    assert _compare(None, "is_null", None)
    assert _compare(1, "not_null", None)
    assert _compare(None, "not_exists", None)
    # Unknown ops stay fail-closed.
    assert not _compare(1, "definitely_not_an_op", 1)


# --- multi-case branch --------------------------------------------------------


def test_multi_case_branch_first_match_wins():
    results = {"gate": {"status": "ok", "output": {"tier": "gold", "n": 5}}}
    params = {
        "cases": [
            {"label": "vip", "conditions": [{"left": "$gate.output.tier", "op": "eq", "right": "platinum"}]},
            {
                "label": "solid",
                "logical_operator": "or",
                "conditions": [
                    {"left": "$gate.output.tier", "op": "eq", "right": "gold"},
                    {"left": "$gate.output.n", "op": "gt", "right": 100},
                ],
            },
            {"label": "everyone"},  # no conditions -> unconditional arm
        ]
    }
    assert select_branch_label(params, results) == "solid"


def test_multi_case_branch_default_label_when_no_match():
    results = {"gate": {"status": "ok", "output": {"tier": "tin"}}}
    cases = [{"label": "vip", "conditions": [{"left": "$gate.output.tier", "op": "eq", "right": "platinum"}]}]
    assert select_branch_label({"cases": cases}, results) == "false"
    assert select_branch_label({"cases": cases, "default_label": "fallback"}, results) == "fallback"


def test_multi_case_branch_malformed_cases_fail_closed():
    results = {}
    # Non-dict case and label-less case never match; non-list cases falls back
    # to the legacy predicate (empty params -> true).
    assert select_branch_label({"cases": ["junk", {"conditions": []}]}, results) == "false"
    assert select_branch_label({"cases": "junk"}, results) == "true"


# --- OR-join / skip lineage ---------------------------------------------------


async def test_merge_node_runs_when_one_arm_taken():
    k = StubKernel()
    record = await _run(k, [
        {"id": "cond", "parents": [], "action": "flow.branch",
         "params": {"left": 1, "op": "eq", "right": 1}},
        {"id": "yes", "parents": ["cond"], "branch": "true", "action": "a.yes", "params": {}},
        {"id": "no", "parents": ["cond"], "branch": "false", "action": "a.no", "params": {}},
        {"id": "merge", "parents": ["yes", "no"], "action": "a.merge", "params": {}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert by["yes"]["status"] == "ok"
    assert by["no"]["status"] == "skipped" and by["no"]["reason"] == "branch_mismatch"
    # The load-bearing parity change: the merge node RUNS (OR-join), once.
    assert by["merge"]["status"] == "ok"
    assert k.calls.count("a.merge") == 1


async def test_merge_node_skips_when_every_arm_skipped():
    k = StubKernel()
    record = await _run(k, [
        {"id": "cond", "parents": [], "action": "flow.branch",
         "params": {"left": 1, "op": "eq", "right": 2}},
        {"id": "yes", "parents": ["cond"], "branch": "true", "action": "a.yes", "params": {}},
        {"id": "after_yes", "parents": ["yes"], "action": "a.after", "params": {}},
        {"id": "merge", "parents": ["yes", "after_yes"], "action": "a.merge", "params": {}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert by["yes"]["reason"] == "branch_mismatch"
    # Benign-skip lineage propagates: all parents skipped -> merge skips too.
    assert by["after_yes"]["status"] == "skipped" and by["after_yes"]["reason"] == "parents_skipped"
    assert by["merge"]["status"] == "skipped" and by["merge"]["reason"] == "parents_skipped"
    assert "a.merge" not in k.calls


async def test_failure_lineage_still_poisons_merge():
    k = StubKernel({"a.boom": [_StubError("boom")]})
    record = await _run(k, [
        {"id": "okstep", "parents": [], "action": "a.fine", "params": {}},
        {"id": "boom", "parents": [], "action": "a.boom", "params": {}},
        {"id": "merge", "parents": ["okstep", "boom"], "action": "a.merge", "params": {}},
    ])
    by = _by_id(record)
    # Fail-closed posture is unchanged for genuine failure: the merge skips.
    assert record["status"] == "failed"
    assert by["boom"]["status"] == "failed"
    assert by["merge"]["status"] == "skipped" and by["merge"]["reason"] == "parent_failed"


# --- error strategies and retry -----------------------------------------------


async def test_on_error_branch_routes_fail_arm():
    k = StubKernel({"a.boom": [_StubError("boom")]})
    record = await _run(k, [
        {"id": "boom", "parents": [], "action": "a.boom", "params": {}, "on_error": "branch"},
        {"id": "recover", "parents": ["boom"], "branch": "fail", "action": "a.recover", "params": {}},
        {"id": "happy", "parents": ["boom"], "branch": "success", "action": "a.happy", "params": {}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert record["exceptions_count"] == 1
    assert by["boom"]["status"] == "exception"
    assert by["boom"]["output"]["branch"] == "fail"
    assert by["boom"]["output"]["error_message"] == "backend_unavailable"
    assert by["recover"]["status"] == "ok"
    assert by["happy"]["status"] == "skipped" and by["happy"]["reason"] == "branch_mismatch"


async def test_on_error_branch_routes_success_arm_on_success():
    k = StubKernel()
    record = await _run(k, [
        {"id": "works", "parents": [], "action": "a.fine", "params": {}, "on_error": "branch"},
        {"id": "recover", "parents": ["works"], "branch": "fail", "action": "a.recover", "params": {}},
        {"id": "happy", "parents": ["works"], "branch": "success", "action": "a.happy", "params": {}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert record["exceptions_count"] == 0
    assert by["works"]["status"] == "ok"
    assert by["works"]["output"]["branch"] == "success"
    assert by["recover"]["status"] == "skipped"
    assert by["happy"]["status"] == "ok"


async def test_on_error_default_substitutes_output_and_run_completes():
    k = StubKernel({"a.boom": [_StubError("boom")]})
    record = await _run(k, [
        {"id": "boom", "parents": [], "action": "a.boom", "params": {},
         "on_error": "default", "default_output": {"value": 42, "error_message": "shadowed"}},
        {"id": "after", "parents": ["boom"], "action": "a.after", "params": {}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert record["exceptions_count"] == 1
    assert by["boom"]["status"] == "exception"
    # Declared default carried; error keys override same-named defaults.
    assert by["boom"]["output"]["value"] == 42
    assert by["boom"]["output"]["error_message"] == "backend_unavailable"
    assert by["after"]["status"] == "ok"


async def test_retry_retries_then_succeeds():
    k = StubKernel({"a.flaky": [_StubError("boom"), _StubError("boom"), {"won": True}]})
    record = await _run(k, [
        {"id": "flaky", "parents": [], "action": "a.flaky", "params": {},
         "retry": {"max": 3, "interval_ms": 0}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert by["flaky"]["status"] == "ok"
    assert by["flaky"]["output"] == {"won": True}
    assert k.calls.count("a.flaky") == 3


async def test_retry_exhausted_applies_strategy():
    k = StubKernel({"a.flaky": [_StubError("boom")]})
    record = await _run(k, [
        {"id": "flaky", "parents": [], "action": "a.flaky", "params": {},
         "retry": {"max": 2, "interval_ms": 0}, "on_error": "default",
         "default_output": {"value": "fallback"}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert by["flaky"]["status"] == "exception"
    assert by["flaky"]["output"]["value"] == "fallback"
    assert k.calls.count("a.flaky") == 3  # 1 + 2 retries


async def test_unknown_strategy_and_retry_values_fail_closed():
    k = StubKernel({"a.boom": [_StubError("boom")]})
    record = await _run(k, [
        {"id": "boom", "parents": [], "action": "a.boom", "params": {},
         "on_error": "definitely_not_a_strategy", "retry": {"max": "junk"}},
    ])
    by = _by_id(record)
    assert record["status"] == "failed"
    assert by["boom"]["status"] == "failed"
    assert k.calls.count("a.boom") == 1


# --- loop item error modes ----------------------------------------------------


def _agg(mode, statuses):
    results = {}
    failed: set[str] = set()
    for k, status in enumerate(statuses):
        if status is None:
            continue  # missing clone
        results[f"a__{k}"] = {"status": status, "output": {"n": k}}
        if status not in {"ok", "exception"}:
            failed.add(f"a__{k}")
    absorbed = aggregate_loop_results(
        results, ["a"], len(statuses), actions={"a": "x.y"},
        on_item_error=mode, failed=failed,
    )
    return results["a"], failed, absorbed


def test_loop_continue_keeps_placeholders_and_clears_failed():
    agg, failed, absorbed = _agg("continue", ["ok", "failed", "ok"])
    assert agg["status"] == "ok"
    assert agg["output"]["iterations"] == [{"n": 0}, None, {"n": 2}]
    assert agg["output"]["errors"] == 1 and agg["output"]["errored_indexes"] == [1]
    assert not failed  # absorbed: no longer fails the run
    assert absorbed == 1


def test_loop_drop_omits_failed_items():
    agg, failed, absorbed = _agg("drop", ["ok", "failed", "ok"])
    assert agg["status"] == "ok"
    assert agg["output"]["iterations"] == [{"n": 0}, {"n": 2}]
    assert agg["output"]["errors"] == 1
    assert not failed
    assert absorbed == 1


def test_loop_fail_mode_unchanged():
    agg, failed, absorbed = _agg("fail", ["ok", "failed", "ok"])
    assert agg["status"] == "failed"
    assert "errors" not in agg["output"]
    assert failed == {"a__1"}
    assert absorbed == 0


async def test_loop_on_item_error_continue_completes_run():
    k = StubKernel({"a.item": [_StubError("boom"), {"ok": 1}]})
    # First item errors, second succeeds; continue -> run completes with one exception.
    record = await _run(k, [
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": [1, 2], "on_item_error": "continue"}},
        {"id": "body", "parents": ["loop"], "action": "a.item",
         "params": {"n": None}, "loop_bindings": {"n": "item"}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert record["exceptions_count"] == 1
    assert by["body"]["status"] == "ok"
    assert by["body"]["output"]["iterations"] == [None, {"ok": 1}]


async def test_loop_invalid_on_item_error_fails_at_run_start():
    k = StubKernel()
    record = await _run(k, [
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": [1], "on_item_error": "explode"}},
        {"id": "body", "parents": ["loop"], "action": "a.item", "params": {}},
    ])
    by = _by_id(record)
    assert record["status"] == "failed"
    assert by["loop"]["reason"] == "loop_on_item_error_invalid"
    assert not k.calls


# --- $inputs reference sugar --------------------------------------------------


async def test_inputs_are_referenceable_without_a_start_step():
    k = StubKernel()
    record = await _run(k, [
        {"id": "cond", "parents": [], "action": "flow.branch",
         "params": {"left": "$inputs.tier", "op": "eq", "right": "gold"}},
        {"id": "yes", "parents": ["cond"], "branch": "true", "action": "a.yes", "params": {}},
    ], inputs={"tier": "gold"})
    by = _by_id(record)
    assert by["cond"]["output"]["branch"] == "true"
    assert by["yes"]["status"] == "ok"


async def test_a_real_step_named_inputs_wins_over_the_sugar():
    k = StubKernel({"a.emit": [{"tier": "silver"}]})
    record = await _run(k, [
        {"id": "inputs", "parents": [], "action": "a.emit", "params": {}},
        {"id": "cond", "parents": ["inputs"], "action": "flow.branch",
         "params": {"left": "$inputs.output.tier", "op": "eq", "right": "silver"}},
        {"id": "yes", "parents": ["cond"], "branch": "true", "action": "a.yes", "params": {}},
    ], inputs={"tier": "gold"})
    by = _by_id(record)
    # The authored step's record is what "$inputs" resolves against, not the
    # run inputs - the sugar never shadows a real step.
    assert by["cond"]["output"]["branch"] == "true"
    assert by["yes"]["status"] == "ok"


# --- parallel loop iterations -------------------------------------------------


class ConcurrencyKernel(StubKernel):
    """Tracks peak in-flight invokes; each call yields so iterations interleave."""

    def __init__(self, script=None):
        super().__init__(script)
        self.in_flight = 0
        self.peak = 0

    async def invoke(self, noun, verb, params, context, *, idempotency_key=None, approval_id=None):
        import asyncio

        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(0)
            return await super().invoke(
                noun, verb, params, context,
                idempotency_key=idempotency_key, approval_id=approval_id,
            )
        finally:
            self.in_flight -= 1


async def test_parallel_loop_runs_iterations_concurrently():
    k = ConcurrencyKernel()
    record = await _run(k, [
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": [1, 2, 3, 4], "parallel": 4}},
        {"id": "body", "parents": ["loop"], "action": "a.item",
         "params": {"n": None}, "loop_bindings": {"n": "item"}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert by["body"]["status"] == "ok"
    assert by["body"]["output"]["count"] == 4
    assert len(by["body"]["output"]["iterations"]) == 4
    # The window genuinely interleaved dispatches.
    assert k.peak > 1


async def test_parallel_loop_window_caps_concurrency():
    k = ConcurrencyKernel()
    record = await _run(k, [
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": [1, 2, 3, 4, 5, 6], "parallel": 2}},
        {"id": "body", "parents": ["loop"], "action": "a.item",
         "params": {"n": None}, "loop_bindings": {"n": "item"}},
    ])
    assert record["status"] == "completed"
    assert k.peak <= 2


async def test_parallel_loop_item_error_continue_absorbs():
    k = StubKernel({"a.item": [_StubError("boom"), {"ok": True}]})
    record = await _run(k, [
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": [1, 2], "parallel": 2, "on_item_error": "continue"}},
        {"id": "body", "parents": ["loop"], "action": "a.item",
         "params": {"n": None}, "loop_bindings": {"n": "item"}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert record["exceptions_count"] == 1
    assert by["body"]["status"] == "ok"


async def test_parallel_loop_with_control_body_falls_back_sequential():
    k = StubKernel()
    # A branch step in the body -> control clone -> sequential walk (safe path).
    record = await _run(k, [
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": ["x"], "parallel": 4}},
        {"id": "gate", "parents": ["loop"], "action": "flow.branch", "params": {}},
        {"id": "act", "parents": ["gate"], "branch": "true", "action": "a.item", "params": {}},
    ])
    by = _by_id(record)
    assert record["status"] == "completed"
    assert by["act"]["status"] == "ok"


async def test_invalid_parallel_fails_at_run_start():
    k = StubKernel()
    record = await _run(k, [
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": [1], "parallel": 99}},
        {"id": "body", "parents": ["loop"], "action": "a.item", "params": {}},
    ])
    by = _by_id(record)
    assert record["status"] == "failed"
    assert by["loop"]["reason"] == "loop_parallel_invalid"
    assert not k.calls


# --- approval rejection / timeout routing -------------------------------------


class _Req:
    def __init__(self, status):
        self.status = status


class _Resp:
    def __init__(self, decision):
        self.decision = decision


class HitlStore:
    """Checkpoint store + readable HITL state for resume-disposition tests."""

    def __init__(self, checkpoints, req_status=None, decision=None):
        self._checkpoints = checkpoints
        self._req_status = req_status
        self._decision = decision
        self.upserts = []

    async def list_checkpoints(self, tenant_id, run_id):
        return list(self._checkpoints)

    async def upsert_checkpoint(self, tenant_id, run_id, step, status, output=None,
                                hitl_request_id=None):
        self.upserts.append((step, status))

    async def get_hitl_request(self, tenant_id, req_id):
        return _Req(self._req_status) if self._req_status else None

    async def get_hitl_response(self, tenant_id, req_id):
        return _Resp(self._decision) if self._decision is not None else None


class _Ck:
    def __init__(self, step, status, hitl_request_id=None, output=None):
        self.step = step
        self.status = status
        self.hitl_request_id = hitl_request_id
        self.output = output


async def _run_resumed(kernel, steps, store):
    from boltrig.workflows.interpreter import run_workflow_definition

    return await run_workflow_definition(
        kernel, _wf(steps), {}, _ctx(), run_id="run-parity", store=store,
    )


async def test_rejected_approval_routes_the_fail_arm():
    store = HitlStore(
        [_Ck("wf-parity:held", "paused", hitl_request_id="h1")],
        req_status="answered", decision="reject",
    )
    k = StubKernel()
    record = await _run_resumed(k, [
        {"id": "held", "parents": [], "action": "a.gated", "params": {},
         "on_error": "branch"},
        {"id": "recover", "parents": ["held"], "branch": "fail", "action": "a.recover", "params": {}},
    ], store)
    by = _by_id(record)
    assert record["status"] == "completed"
    assert by["held"]["status"] == "exception"
    assert by["held"]["output"]["error_message"] == "approval_rejected"
    assert by["recover"]["status"] == "ok"
    # The gated verb was NEVER dispatched - a declined authorisation cannot run.
    assert "a.gated" not in k.calls


async def test_timed_out_approval_fails_without_strategy():
    store = HitlStore(
        [_Ck("wf-parity:held", "paused", hitl_request_id="h1")],
        req_status="timed_out",
    )
    k = StubKernel()
    record = await _run_resumed(k, [
        {"id": "held", "parents": [], "action": "a.gated", "params": {}},
    ], store)
    by = _by_id(record)
    assert record["status"] == "failed"
    assert by["held"]["reason"] == "approval_timeout"
    assert "a.gated" not in k.calls


async def test_approved_pause_still_dispatches_with_the_approval():
    store = HitlStore(
        [_Ck("wf-parity:held", "paused", hitl_request_id="h1")],
        req_status="answered", decision="approve",
    )
    k = StubKernel()
    record = await _run_resumed(k, [
        {"id": "held", "parents": [], "action": "a.gated", "params": {}},
    ], store)
    by = _by_id(record)
    # Approving answers fall through to the normal dispatch + consume CAS.
    assert by["held"]["status"] == "ok"
    assert k.calls.count("a.gated") == 1
