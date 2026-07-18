"""Bounded liveness contract for /healthz (FR-OPS-05).

/healthz backs the Compose healthcheck: it must answer from process state and
the cached adapter posture so a slow or unreachable adapter backend can never
make the probe slow or non-200 and flap a live kernel. Posture freshness moves
to a bounded background refresh; deep dependency readiness stays on the
fail-closed /readyz (FR-OPS-03)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.base import Credential, Result, VerbSpec
from boltrig.adapters.loader import AdapterLoader
from boltrig.api.readiness import ReadinessService
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import InvocationContext
from boltrig.store import InMemoryStore

pytestmark = pytest.mark.unit


class _ProbeAdapter:
    """A minimal adapter whose health probe is scripted by the test."""

    version = "1.0.0"
    runtime = "http"

    def __init__(self, *, status: str = "ok", hang_s: float = 0.0) -> None:
        self.id = "probe"
        self.status = status
        self.hang_s = hang_s
        self.health_calls = 0

    def describe(self) -> list[VerbSpec]:
        return []

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        return Result.success({})

    async def health(self) -> str:
        self.health_calls += 1
        if self.hang_s:
            await asyncio.sleep(self.hang_s)
        return self.status


class _NoToolsStatus:
    """A stack-tool status provider reporting no components (posture fails)."""

    async def snapshot(self, *, tenant_id: str, workspace_id: str | None) -> dict[str, Any]:
        del tenant_id, workspace_id
        return {"components": [], "runtimes": []}


@pytest.mark.invariant("FR-OPS-05")
def test_healthz_returns_200_for_a_live_app() -> None:
    client = TestClient(create_app(Kernel(InMemoryStore())))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "adapters": {}}


@pytest.mark.invariant("FR-OPS-05")
def test_healthz_stays_prompt_and_200_when_an_adapter_health_hangs() -> None:
    kernel = Kernel(InMemoryStore())
    # Prime the posture cache so the snapshot is fresh: the request under test
    # must then perform NO adapter I/O at all, neither inline nor background.
    asyncio.run(kernel.loader.refresh_health())
    adapter = _ProbeAdapter(status="down", hang_s=300.0)
    kernel.loader.register("acme", adapter)
    client = TestClient(create_app(kernel))

    started = time.perf_counter()
    response = client.get("/healthz")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 1.0, f"liveness took {elapsed:.2f}s; it must not await adapter I/O"
    assert response.json() == {"status": "ok", "adapters": {"acme/probe": "unknown"}}
    assert adapter.health_calls == 0


@pytest.mark.invariant("FR-OPS-05")
def test_healthz_serves_cached_posture_without_reprobing() -> None:
    kernel = Kernel(InMemoryStore())
    adapter = _ProbeAdapter(status="ok")
    kernel.loader.register("acme", adapter)
    asyncio.run(kernel.loader.refresh_health())
    client = TestClient(create_app(kernel))

    first = client.get("/healthz")
    second = client.get("/healthz")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"status": "ok", "adapters": {"acme/probe": "ok"}}
    assert adapter.health_calls == 1  # the explicit refresh; /healthz added none


@pytest.mark.invariant("FR-OPS-05")
async def test_health_snapshot_kicks_a_background_refresh_when_stale() -> None:
    loader = AdapterLoader()
    adapter = _ProbeAdapter(status="ok")
    loader.register("acme", adapter)

    # The snapshot itself is immediate and cached; staleness only schedules a
    # refresh on the running loop, off the caller's path.
    assert loader.health_snapshot() == {("acme", "probe"): "unknown"}
    for _ in range(100):
        await asyncio.sleep(0.01)
        if loader.health_snapshot() == {("acme", "probe"): "ok"}:
            break
    assert loader.health_snapshot() == {("acme", "probe"): "ok"}
    assert adapter.health_calls == 1  # one background probe; a fresh cache is not re-probed


@pytest.mark.invariant("FR-OPS-05")
async def test_refresh_health_bounds_a_hung_probe() -> None:
    loader = AdapterLoader()
    loader.register("acme", _ProbeAdapter(status="ok", hang_s=300.0))

    started = time.perf_counter()
    health = await loader.refresh_health(probe_timeout_s=0.05)
    elapsed = time.perf_counter() - started

    assert health == {("acme", "probe"): "down"}
    assert elapsed < 1.0


@pytest.mark.invariant("FR-OPS-05")
def test_readyz_stays_bounded_and_fail_closed_with_a_hung_adapter() -> None:
    kernel = Kernel(InMemoryStore())
    adapter = _ProbeAdapter(status="down", hang_s=300.0)
    kernel.loader.register("acme", adapter)
    readiness = ReadinessService(
        kernel,
        tenant_id="acme",
        status_provider=_NoToolsStatus(),
        env={},
    )
    client = TestClient(create_app(kernel, platform={"readiness": readiness}))

    started = time.perf_counter()
    response = client.get("/readyz")
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert elapsed < 5.0  # readiness never fans out to loader adapters
    assert adapter.health_calls == 0
