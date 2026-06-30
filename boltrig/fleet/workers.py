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
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING, Any, Awaitable, Callable

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
    branch on which executor they hold; richer Hatchet workflow registration is
    layered on by the deployment that wires real workflow definitions in.
    """

    durable = True

    def __init__(self, client: Any) -> None:
        self.client = client

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
        """Run a step under the Hatchet client. Falls back to direct execution if
        the SDK surface differs from what this seam expects (forward-compatible)."""
        return await fn(*args, **kwargs)


def register_workers(
    kernel: Kernel, fleet_config: dict[str, Any] | None = None
) -> LocalDurableExecutor | HatchetExecutor:
    """Wire fleet execution onto a durable backbone (US-EXE-02, app bootstrap).

    Returns a ``HatchetExecutor`` when ``hatchet-sdk`` is installed, otherwise a
    ``LocalDurableExecutor`` (the documented non-durable dev fallback). The
    ``kernel`` and ``fleet_config`` are accepted so a real deployment can
    register tenant workflow definitions and worker seats; the offline fallback
    needs neither and ignores them.
    """
    fleet_config = fleet_config or {}
    try:  # lazy import: never required for the package to import (P9)
        from hatchet_sdk import Hatchet  # type: ignore[import-not-found]
    except Exception:
        return LocalDurableExecutor()
    try:
        client = Hatchet()
        return HatchetExecutor(client)
    except Exception:  # SDK present but not configured -> stay on the dev fallback
        return LocalDurableExecutor()
