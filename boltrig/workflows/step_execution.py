"""Capability-step execution for the workflow interpreter (DAG parity).

The interpreter owns the topological walk; this module owns how ONE capability
step dispatches through ``kernel.invoke`` and how its outcome resolves:

* **Bounded retry** (``retry: {max, interval_ms}``, clamped by policy): a
  failed dispatch re-invokes up to ``max`` more times. Retries happen inside
  one walk; a HITL pause is never retried - the human's answer, not another
  attempt, decides the step.
* **Error strategies** (``on_error``): an exhausted failure either poisons
  descendants (``fail``, the unchanged default), converts into a routable
  ``branch: "fail"`` label with success arms stamped ``branch: "success"``
  (``branch``), or substitutes the step's declared ``default_output``
  (``default``). Absorbed failures record step status ``exception`` - honest
  partial success, surfaced as the run's ``exceptions_count`` - and are
  checkpointed ``ok`` so a resumed run replays the absorption.
* **Checkpoint + idempotency wiring** unchanged from the interpreter's
  original semantics (NFR-REL-02/03): success checkpoints ``ok``; a pause
  checkpoints ``paused`` with its approval id and stops the walk; a keyed
  ``IdempotencyConflict`` falls back to one keyless invoke.

Everything here runs INSIDE the one governed dispatch path: strategies and
retries change how an outcome is recorded, never what a step may do (SEC-50).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from boltrig.models import BoltrigError, IdempotencyConflict

# Per-step retry bounds (graphon-parity error handling, bounded by policy):
# retries happen inside one interpreter walk, so both are capped to keep a
# misauthored step from stalling the run for minutes.
MAX_STEP_RETRIES = 5
MAX_RETRY_INTERVAL_MS = 60_000
# Step-level error strategies: how a failed capability step resolves.
ERROR_STRATEGIES = frozenset({"fail", "branch", "default"})
# Kernel reasons that mean "held for a human", not "failed".
PAUSE_REASONS = frozenset({"pending_human", "approval_required"})
# Mirrors the kernel's approving-decision vocabulary (kernel/hitl.py). Used
# READ-ONLY here to classify an answered request; the consume-if-approved CAS
# remains the sole authority for executing a gated verb (SEC-14 untouched).
_APPROVING = frozenset({"approve", "approved", "yes", "ok", "allow"})


async def resolve_pause_disposition(
    store: Any | None, tenant_id: str, hitl_request_id: str | None
) -> str:
    """How a resumed paused step should proceed: ``resume`` | ``rejected`` | ``timed_out``.

    A read-only pre-check on the checkpointed HITL request (graphon-parity
    branch handles: a human's rejection or a timeout become ROUTABLE outcomes
    instead of re-asking forever). Fail-closed: anything unreadable, pending,
    consumed, or approvingly answered resolves ``resume`` - the kernel's gate
    then decides exactly as before. This function never writes and never
    bypasses the consume CAS; it only stops the interpreter from re-dispatching
    a verb whose authorisation a human explicitly declined or let lapse.
    """
    if store is None or not hitl_request_id:
        return "resume"
    get_req = getattr(store, "get_hitl_request", None)
    if get_req is None:
        return "resume"
    try:
        req = await get_req(tenant_id, hitl_request_id)
    except Exception:
        return "resume"
    if req is None:
        return "resume"
    status = getattr(getattr(req, "status", None), "value", None) or str(
        getattr(req, "status", "") or ""
    )
    if status == "timed_out":
        return "timed_out"
    if status == "answered":
        get_resp = getattr(store, "get_hitl_response", None)
        if get_resp is None:
            return "resume"
        try:
            resp = await get_resp(tenant_id, hitl_request_id)
        except Exception:
            return "resume"
        decision = str(getattr(resp, "decision", "") or "").strip().lower()
        if resp is not None and decision and decision not in _APPROVING:
            return "rejected"
    return "resume"

StepEmitter = Callable[[dict[str, Any]], None]


def step_retry(step: dict[str, Any]) -> tuple[int, float]:
    """A step's ``retry: {max, interval_ms}``, clamped to policy bounds."""
    retry = step.get("retry")
    if not isinstance(retry, dict):
        return 0, 0.0
    try:
        max_retries = min(max(int(retry.get("max", 0)), 0), MAX_STEP_RETRIES)
        interval_ms = min(max(int(retry.get("interval_ms", 0)), 0), MAX_RETRY_INTERVAL_MS)
    except (TypeError, ValueError):
        return 0, 0.0
    return max_retries, interval_ms / 1000.0


def error_strategy(step: dict[str, Any]) -> str:
    """The step's declared error strategy; unknown values fail closed to ``fail``."""
    strategy = step.get("on_error", "fail")
    return strategy if strategy in ERROR_STRATEGIES else "fail"


async def compute_idempotency_key(
    store: Any | None, wf: Any, rid: str | None, step_id: str, verb: str
) -> str | None:
    """The deterministic per-step idempotency key, or ``None``.

    Minted only when checkpointing is active, the verb resolves through the
    store, and the verb is not idempotency-disabled (a one-time secret result
    must never be replay-cached).
    """
    if store is None:
        return None
    get_verb = getattr(store, "get_verb", None)
    verb_def = await get_verb(wf.tenant_id, verb) if get_verb is not None else None
    mode = getattr(getattr(verb_def, "idempotency_mode", None), "value", None)
    if verb_def is not None and mode != "disabled":
        return f"workflow:{wf.id}:{rid}:{step_id}"
    return None


def resolve_step_failure(
    results: dict[str, dict[str, Any]],
    failed_or_skipped: set[str],
    failed: set[str],
    exceptions: list[str],
    *,
    step: dict[str, Any],
    step_id: str,
    action: str,
    status: str,
    reason: str,
    strategy: str,
    emit_step: StepEmitter,
) -> None:
    """Apply the step's error strategy to an exhausted failure.

    ``fail`` records the failure and poisons descendants (unchanged posture).
    ``branch``/``default`` absorb it (see module docstring). The emitted event
    stays in the validated status vocabulary (``ok`` + reason) so bounded
    projections and the web SDK are unaffected.
    """
    if strategy == "fail":
        failed_or_skipped.add(step_id)
        failed.add(step_id)
        results[step_id] = {"action": action, "status": status, "reason": reason}
        emit_step({"step_id": step_id, "action": action, "status": status, "reason": reason})
        return
    error_keys = {"error_message": reason, "error_type": status}
    if strategy == "branch":
        output: dict[str, Any] = {**error_keys, "branch": "fail"}
    else:  # "default"
        default_output = step.get("default_output")
        base = default_output if isinstance(default_output, dict) else {}
        # Error keys override same-named defaults (graphon precedence) so the
        # failure stays observable even under a defaulted output.
        output = {**base, **error_keys}
    exceptions.append(step_id)
    results[step_id] = {"action": action, "status": "exception", "output": output}
    emit_step({"step_id": step_id, "action": action, "status": "ok",
               "reason": f"error_strategy_{strategy}"})


async def _retry_or_resolve(
    ctx: "StepRun", *, status: str, reason: str, attempt: int
) -> bool:
    """One more retry (True) or resolve the exhausted failure (False)."""
    if attempt < ctx.max_retries:
        ctx.emit_step({"step_id": ctx.step_id, "action": ctx.action,
                       "status": "running", "reason": f"retry_{attempt + 1}"})
        if ctx.retry_interval:
            await asyncio.sleep(ctx.retry_interval)
        return True
    resolve_step_failure(
        ctx.results, ctx.failed_or_skipped, ctx.failed, ctx.exceptions,
        step=ctx.step, step_id=ctx.step_id, action=ctx.action, status=status,
        reason=reason, strategy=ctx.strategy, emit_step=ctx.emit_step,
    )
    return False


async def _record_pause(ctx: "StepRun", exc: BoltrigError, reason: str) -> tuple[bool, bool]:
    """A held HITL gate is a pause, not a failure - the run can resume.

    For dependency purposes it is treated like one: descendants must never
    dispatch with the paused parent's (missing) output. With the checkpoint
    seam wired the pause is durable (NFR-REL-03) - the request id is the
    approval id the resumed run re-invokes with - and the walk stops.
    """
    hitl_id = getattr(exc, "hitl_request_id", None)
    ctx.failed_or_skipped.add(ctx.step_id)
    ctx.results[ctx.step_id] = {"action": ctx.action, "status": "paused", "reason": reason}
    if hitl_id:
        ctx.results[ctx.step_id]["hitl_request_id"] = hitl_id
    ctx.emit_step({"step_id": ctx.step_id, "action": ctx.action,
                   "status": "paused", "reason": reason})
    if ctx.store is not None:
        await ctx.store.upsert_checkpoint(
            ctx.wf.tenant_id, ctx.rid, ctx.ck(ctx.step_id), "paused", hitl_request_id=hitl_id
        )
        return True, True
    return True, False


async def _record_success(ctx: "StepRun", output: Any) -> None:
    if ctx.strategy == "branch" and isinstance(output, dict) and "branch" not in output:
        # A branch-strategy step routes success/fail arms: stamp the success
        # label so fail-arm children skip on the happy path. (An
        # author-produced ``branch`` key is left alone.)
        output = {**output, "branch": "success"}
    ctx.results[ctx.step_id] = {"action": ctx.action, "status": "ok", "output": output}
    if ctx.store is not None:
        await ctx.store.upsert_checkpoint(
            ctx.wf.tenant_id, ctx.rid, ctx.ck(ctx.step_id), "ok", output=output
        )
    ctx.emit_step({"step_id": ctx.step_id, "action": ctx.action, "status": "ok"})


async def _resolve_decided_pause(
    *,
    store: Any | None,
    wf: Any,
    rid: str | None,
    step: dict[str, Any],
    step_id: str,
    action: str,
    approval_id: str,
    results: dict[str, dict[str, Any]],
    failed_or_skipped: set[str],
    failed: set[str],
    exceptions: list[str],
    emit_step: StepEmitter,
    ck: Callable[[str], str],
) -> bool:
    """Branch handles for human decisions (graphon parity, SEC-14 preserved).

    An explicitly rejected or timed-out approval resolves through the step's
    error strategy (``on_error: branch`` routes the "fail" arm) instead of
    re-dispatching into a gate that would re-ask forever. Approved, pending,
    consumed, or unreadable states return ``False`` - the normal dispatch and
    the consume CAS decide exactly as before. Returns ``True`` when the step
    was resolved here.
    """
    disposition = await resolve_pause_disposition(store, wf.tenant_id, approval_id)
    if disposition == "resume":
        return False
    reason = "approval_rejected" if disposition == "rejected" else "approval_timeout"
    strategy = error_strategy(step)
    resolve_step_failure(
        results, failed_or_skipped, failed, exceptions,
        step=step, step_id=step_id, action=action, status="failed",
        reason=reason, strategy=strategy, emit_step=emit_step,
    )
    if strategy != "fail" and store is not None:
        await store.upsert_checkpoint(
            wf.tenant_id, rid, ck(step_id), "ok",
            output=results[step_id].get("output"),
        )
    return True


class StepRun:
    """One capability step's dispatch context (plain attribute bag)."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _make_dispatch(
    kernel: Any, run_ctx: Any, noun: str, verb: str, params: dict[str, Any],
    approval_id: str | None, idempotency_key: str | None,
) -> Callable[[], Any]:
    async def _dispatch() -> dict[str, Any]:
        try:
            return await kernel.invoke(
                noun, verb, params, run_ctx,
                idempotency_key=idempotency_key, approval_id=approval_id,
            )
        except IdempotencyConflict:
            if idempotency_key is None:
                raise
            # A prior attempt parked the key (worker died mid-execution; a
            # COMPLETED prior record replays inside the kernel and never
            # reaches here). Fall back to a keyless invoke: standard
            # engine-retry, at-least-once semantics (NFR-REL-02).
            return await kernel.invoke(noun, verb, params, run_ctx, approval_id=approval_id)

    return _dispatch


async def run_capability_step(
    *,
    kernel: Any,
    executor: Any | None,
    store: Any | None,
    wf: Any,
    rid: str | None,
    run_ctx: Any,
    step: dict[str, Any],
    step_id: str,
    action: str,
    noun: str,
    verb: str,
    params: dict[str, Any],
    approval_id: str | None,
    results: dict[str, dict[str, Any]],
    failed_or_skipped: set[str],
    failed: set[str],
    exceptions: list[str],
    emit_step: StepEmitter,
    ck: Callable[[str], str],
) -> tuple[bool, bool]:
    """Dispatch one capability step to completion. Returns ``(paused, stop_walk)``.

    ``store`` is the checkpoint seam - ``None`` when checkpointing is off.
    """
    if approval_id is not None and await _resolve_decided_pause(
        store=store, wf=wf, rid=rid, step=step, step_id=step_id, action=action,
        approval_id=approval_id, results=results,
        failed_or_skipped=failed_or_skipped, failed=failed, exceptions=exceptions,
        emit_step=emit_step, ck=ck,
    ):
        return False, False

    idempotency_key = await compute_idempotency_key(store, wf, rid, step_id, verb)
    _dispatch = _make_dispatch(kernel, run_ctx, noun, verb, params, approval_id, idempotency_key)
    max_retries, retry_interval = step_retry(step)
    ctx = StepRun(
        store=store, wf=wf, rid=rid, step=step, step_id=step_id, action=action,
        results=results, failed_or_skipped=failed_or_skipped, failed=failed,
        exceptions=exceptions, emit_step=emit_step, ck=ck,
        max_retries=max_retries, retry_interval=retry_interval,
        strategy=error_strategy(step),
    )
    boundary = f"workflow:{wf.id}:{step_id}"
    attempt = 0
    while True:
        try:
            if executor is not None:
                output = await executor.run_step(boundary, _dispatch, run_id=rid)
            else:
                output = await _dispatch()
            await _record_success(ctx, output)
            return False, False
        except BoltrigError as exc:
            reason = getattr(exc, "reason", type(exc).__name__)
            if reason in PAUSE_REASONS:
                # Pauses are never retried and never strategy-absorbed: the
                # human's answer, not a default, decides the step.
                return await _record_pause(ctx, exc, reason)
            retrying = await _retry_or_resolve(ctx, status="failed", reason=reason, attempt=attempt)
        except Exception as exc:  # an adapter bug must not crash the fleet (P9)
            retrying = await _retry_or_resolve(
                ctx, status="error", reason=type(exc).__name__, attempt=attempt
            )
        if retrying:
            attempt += 1
            continue
        if ctx.strategy != "fail" and store is not None:
            # An absorbed failure has a defined output (graphon-parity
            # continue-on-error): checkpoint it so a resumed run replays the
            # absorption instead of re-failing.
            await store.upsert_checkpoint(
                wf.tenant_id, rid, ck(step_id), "ok",
                output=results[step_id].get("output"),
            )
        return False, False
