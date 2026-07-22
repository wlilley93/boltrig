"""The Hatchet integration seam (P6, US-EXE-02).

Permanent (tier-1/tier-2) and ephemeral execution run as *durable steps*: each
step is a recoverable unit with a run id and recorded boundaries, so a crash or
a HITL pause can resume without losing or repeating work. Hatchet is the
production backbone for this durability.

This module keeps that backbone behind a seam. ``hatchet-sdk`` is imported
lazily; when it is not installed (dev / tests / offline) ``register_workers``
returns a ``LocalDurableExecutor`` - an in-process, NON-durable fallback that
still assigns run ids and records step boundaries so the rest of the fleet runs
unchanged. It is explicitly NOT a durability guarantee; production must install
Hatchet.

Executor selection is honest and optionally fail-closed (US-EXE-05): the
selection is logged with the executor's ``durable`` flag, and setting
``BOLTRIG_REQUIRE_DURABLE=1`` turns any durable-engine failure into a boot
refusal instead of a silent fallback.

Both executors share one surface: ``new_run_id`` / ``run_step`` plus the queue
seam ``enqueue(task_name, payload)`` and ``push_event(key, payload, scope)``
so callers never branch on which executor they hold.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING, Any, Awaitable, Callable

log = logging.getLogger("boltrig.fleet.workers")

if TYPE_CHECKING:  # type-only seam (no runtime import cost / no cycle)
    from boltrig.kernel import Kernel


@dataclass
class StepRecord:
    """One recorded durable-step boundary (dev-fallback bookkeeping)."""

    run_id: str
    name: str
    status: str  # running | ok | error
    started_at: float
    ended_at: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class LocalDurableExecutor:
    """In-process, NON-durable dev fallback for the Hatchet backbone (US-EXE-02).

    It assigns run ids and records step start/end boundaries in memory so the
    fleet's "everything is a durable step" shape holds in dev and tests. It does
    NOT persist, retry, or resume across a process restart - that is Hatchet's
    job in production. The fallback is deliberately loud about this in its name.
    """

    durable = False

    def __init__(self) -> None:
        self.steps: list[StepRecord] = []
        self.events: list[dict[str, Any]] = []
        self._tasks: dict[str, Callable[..., Awaitable[Any]]] = {}

    def register_task(self, name: str, fn: Callable[..., Awaitable[Any]]) -> None:
        """Register a named task body for ``enqueue`` (offline queue seam)."""
        self._tasks[name] = fn

    async def enqueue(self, task_name: str, payload: dict) -> str | None:
        """Run the registered task body INLINE (awaited here, US-EXE-05).

        There is no queue in the local fallback: the pump/interpreter paths of
        later beats are exercised offline by executing the body immediately as
        a recorded step. Raises ``KeyError`` for an unregistered task
        (fail-closed, K-13). Returns the run id."""
        fn = self._tasks[task_name]  # KeyError = unregistered task, fail-closed
        rid = self.new_run_id()
        await self.run_step(f"task:{task_name}", fn, payload, run_id=rid)
        return rid

    async def push_event(
        self, key: str, payload: dict, scope: str | None = None
    ) -> None:
        """Record an event in memory (assertable in tests; no engine offline)."""
        self.events.append({"key": key, "payload": payload, "scope": scope})

    def new_run_id(self) -> str:
        """Allocate a run id for a workflow/agent run."""
        return uuid.uuid4().hex

    async def run_step(
        self,
        name: str,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute ``fn`` as a recorded step; capture its boundary + outcome."""
        rid = run_id or self.new_run_id()
        record = StepRecord(run_id=rid, name=name, status="running", started_at=monotonic())
        self.steps.append(record)
        try:
            result = await fn(*args, **kwargs)
            record.status = "ok"
            return result
        except Exception as exc:  # record the boundary even on failure
            record.status = "error"
            record.detail = {"error": type(exc).__name__}
            raise
        finally:
            record.ended_at = monotonic()


class HatchetExecutor:
    """Thin wrapper over a live Hatchet client (production backbone, US-EXE-02).

    Constructed only when ``hatchet-sdk`` is importable. It keeps the same
    ``new_run_id`` / ``run_step`` surface as the local fallback so callers do not
    branch on which executor they hold. ``workflows`` maps registered task names
    (hatchet_app.py) to the SDK workflow objects ``enqueue`` starts.
    """

    durable = True

    def __init__(self, client: Any, workflows: dict[str, Any] | None = None) -> None:
        self.client = client
        self.workflows: dict[str, Any] = dict(workflows or {})

    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    async def run_step(
        self,
        name: str,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Await ``fn`` directly. This is NOT a durable engine step: the
        installed hatchet-sdk (1.33.x) exposes no public durable child-step API
        on ``DurableContext`` (only durable waits/sleeps and a private memo),
        so nothing here is independently recorded or resumable by the engine.
        On the workflow-run path (hatchet_app.run_workflow_body) the honest
        guarantee is therefore: the engine retries the whole durable TASK on a
        crash, checkpoints replay every COMPLETED step (they are never
        re-dispatched), and the interpreter's per-step idempotency key replays
        the recorded kernel result for a step that completed but whose
        checkpoint write was lost. Only a genuinely in-flight step re-executes,
        after its idempotency claim lease expires. If a future SDK adds durable
        child steps, this method is the single seam to upgrade."""
        return await fn(*args, **kwargs)

    async def enqueue(self, task_name: str, payload: dict) -> str | None:
        """Start the registered task on the engine without waiting (US-EXE-02).

        Raises ``KeyError`` for an unregistered task name (fail-closed, K-13,
        mirroring the local executor). Returns the engine's run id."""
        wf = self.workflows[task_name]  # KeyError = unregistered task, fail-closed
        ref = await wf.aio_run_no_wait(payload)
        return getattr(ref, "workflow_run_id", None) or str(ref)

    async def push_event(
        self, key: str, payload: dict, scope: str | None = None
    ) -> None:
        """Push a user event, scope-correlated so the engine routes it to the
        one durable wait registered for that scope (NFR-REL-03)."""
        from hatchet_sdk import PushEventOptions

        await self.client.event.aio_push(
            key, payload, options=PushEventOptions(scope=scope)
        )


def _require_durable() -> bool:
    """True when BOLTRIG_REQUIRE_DURABLE demands fail-closed selection (US-EXE-05)."""
    from boltrig.config.environment import is_truthy

    return is_truthy(os.environ.get("BOLTRIG_REQUIRE_DURABLE"))


def register_workers(
    kernel: Kernel, fleet_config: dict[str, Any] | None = None
) -> LocalDurableExecutor | HatchetExecutor:
    """Wire fleet execution onto a durable backbone (US-EXE-02, US-EXE-05).

    Returns a ``HatchetExecutor`` when ``hatchet-sdk`` is installed and
    configured, otherwise a ``LocalDurableExecutor`` (the documented non-durable
    dev fallback). Selection is honest: the choice and its ``durable`` flag are
    logged, and with ``BOLTRIG_REQUIRE_DURABLE=1`` a durable-engine failure
    RAISES instead of silently falling back (US-EXE-05). The ``kernel`` and
    ``fleet_config`` are accepted so a real deployment can register tenant
    workflow definitions and worker seats; the offline fallback needs neither
    and ignores them.
    """
    fleet_config = fleet_config or {}
    try:  # lazy import: never required for the package to import (P9)
        from hatchet_sdk import Hatchet  # type: ignore[import-not-found]
    except Exception as exc:
        return _fallback_or_raise(f"hatchet-sdk import failed: {exc}", exc)
    try:
        client = Hatchet()
    except Exception as exc:  # SDK present but not configured (e.g. no token)
        return _fallback_or_raise(f"Hatchet client config failed: {exc}", exc)
    # Register the Boltrig task definitions on this client so ``enqueue`` can
    # start them by name (the bodies only run in the worker process; here the
    # workflow objects are the client-side handles). Fail-safe: a registration
    # fault leaves enqueue fail-closed (KeyError), never breaks boot (P9).
    try:
        from .hatchet_app import build_hatchet_app

        _, workflows = build_hatchet_app(hatchet=client)
    except Exception as exc:
        log.warning("hatchet task registration failed: %s", exc)
        workflows = {}
    log.info("executor selected: HatchetExecutor (durable=True)")
    return HatchetExecutor(client, workflows=workflows)


def _fallback_or_raise(reason: str, exc: Exception) -> LocalDurableExecutor:
    """The honest fallback seam (US-EXE-05): refuse when durability is required,
    else return the local executor with the reason on the record."""
    if _require_durable():
        raise RuntimeError(
            f"BOLTRIG_REQUIRE_DURABLE is set but the durable engine is "
            f"unavailable ({reason}); refusing to boot on the non-durable "
            f"fallback (US-EXE-05)"
        ) from exc
    log.warning(
        "executor selected: LocalDurableExecutor (durable=False, NON-durable "
        "fallback; %s)", reason,
    )
    return LocalDurableExecutor()
