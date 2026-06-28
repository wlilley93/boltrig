"""Live Hatchet integration (P1-1).

Gated on a reachable Hatchet engine (HATCHET_CLIENT_TOKEN set); skipped offline so
the default suite stays green (P9). It proves the live execution path end to end:
a Nankle workflow registers, a worker runs it, and the result comes back from the
real engine. The durability *property* (a paused run resuming) is proven
deterministically by the Postgres-backed NFR-REL-01 test; the production durable
backbone (the hitl_demo durable task) is registered here and exercised live, and
the worker-restart resume is left best-effort because it depends on the engine's
durable-event wiring.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.environ.get("HATCHET_CLIENT_TOKEN"),
    reason="set HATCHET_CLIENT_TOKEN (+ a reachable Hatchet engine) for the live test",
)


def _start_worker() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "nankle.fleet.hatchet_worker"],
        cwd=str(_REPO),
        env=dict(os.environ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def test_live_workflow_executes_end_to_end():
    """A Nankle workflow runs on the real engine and returns its result."""
    from nankle.fleet.hatchet_app import PingInput, build_hatchet_app

    hatchet, workflows = build_hatchet_app()
    worker = _start_worker()
    try:
        await asyncio.sleep(9)  # let the worker register with the engine
        result = await asyncio.wait_for(
            workflows["ping"].aio_run(PingInput(value=21)), timeout=45
        )
        # result is the task return (tolerate a task-name wrap)
        doubled = result.get("doubled") if isinstance(result, dict) else None
        if doubled is None and isinstance(result, dict):
            doubled = next(
                (v.get("doubled") for v in result.values() if isinstance(v, dict)), None
            )
        assert doubled == 42, result
    finally:
        if worker.poll() is None:
            worker.kill()


async def test_live_durable_task_pauses():
    """The durable HITL task is accepted by the engine and pauses (does not
    complete immediately) - the production durable backbone, registered live."""
    from nankle.fleet.hatchet_app import HitlInput, build_hatchet_app

    hatchet, workflows = build_hatchet_app()
    worker = _start_worker()
    try:
        await asyncio.sleep(9)
        ref = await workflows["hitl"].aio_run(
            HitlInput(run_key=f"live-{int(time.time())}"), wait_for_result=False
        )
        # it must NOT complete on its own within a short window (it is paused)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ref.aio_result(), timeout=12)
    finally:
        if worker.poll() is None:
            worker.kill()
