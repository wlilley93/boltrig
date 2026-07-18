"""Tests for the trusted read-only Codex proxy provider ([2026] VJS-CC-VJS 2).

Security-critical: a fail-open in the mint or an upstream-key leak is the
catastrophic failure. These pin the load-bearing directives without running the
live Codex turn (the parent runs that on the real box):

  * D1 - the dev/prod wall fails closed BEFORE any admit or mint.
  * D2 - the supervisor is constructed with auth=None (the child env never carries
    the upstream key); the cell holds only the short-TTL scoped bearer.
  * D3 - the cell scope is built from a child's REAL /proc identity.
  * a minted bearer verifies via the canonical store_bearer_verifier.
  * release cancels the refresh, revokes the grant, and closes the proxy.
  * the rendered config.toml points the cell at the loopback proxy.

The auth.command helper contract is pinned in test_codex_trusted_proxy_helper.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from boltrig.fleet.application.model_proxy_grants import PhaseScopedModelProxyGrantBroker
from boltrig.fleet.codex_trusted_wall import CodexTrustedPostureError
from boltrig.fleet.domain import PhaseAssignmentRef, PhaseRef
from boltrig.fleet.infrastructure.codex_cell_policy import CodexUpstreamAuth
from boltrig.fleet.infrastructure.codex_cell_supervisor import CodexCellSupervisor
from boltrig.fleet.infrastructure.codex_model_proxy_server import (
    PerCellModelProxyServer,
    store_bearer_verifier,
)
from boltrig.fleet.infrastructure.codex_runtime_config import CodexReasoningEffort
from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
    TrustedProxyCodexPhaseCellProvider,
    TrustedProxyProvisionError,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    BEARER_FILENAME,
    GenerationHolder,
    build_cell_scope,
    render_trusted_config,
    tracking_bearer_verifier,
)
from boltrig.fleet.infrastructure.memory_model_proxy_grants import (
    MemoryModelProxyGrantStore,
)
from boltrig.models.execution_scope import OrganisationUserRef

_CODEX_BIN = Path("/opt/boltrig/codex/codex")
_CELL_ID = "cell-abc1234567890ab"
_MODEL_ID = "gpt-5.2-codex"
_TRUSTED_ENV = {"BOLTRIG_DEV_AUTH": "1", "BOLTRIG_CODEX_TRUSTED": "1"}


def _assignment() -> PhaseAssignmentRef:
    principal = OrganisationUserRef(tenant_id="tenant-1", user_id="user-1")
    phase = PhaseRef(
        root_run_id="run-1",
        phase_id="run-1-codex",
        principal=principal,
        workspace_id="ws-1",
    )
    return PhaseAssignmentRef(phase=phase, assignment_id="run-1-codex-assignment")


class _FakeSource:
    def __init__(self) -> None:
        self.calls = 0

    async def admit(self, assignment: PhaseAssignmentRef) -> object:
        self.calls += 1
        raise AssertionError("admit must not run when the wall refuses")


class _FakeProbe:
    async def probe(self, client: object, plan: object) -> object:
        raise AssertionError("probe must not run in these tests")


@pytest.fixture
def running_child() -> Iterator[int]:
    """A short-lived real process whose /proc identity is read by the scope."""

    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        yield process.pid
    finally:
        process.kill()
        process.wait(timeout=5)


def _supervisor(auth: CodexUpstreamAuth | None = None) -> CodexCellSupervisor:
    return CodexCellSupervisor(binary=_CODEX_BIN, auth=auth)


def _provider(
    *,
    broker: PhaseScopedModelProxyGrantBroker,
    store: MemoryModelProxyGrantStore,
    client: httpx.AsyncClient,
    source: _FakeSource | None = None,
    supervisor: CodexCellSupervisor | None = None,
    env: dict[str, str] | None = None,
    generation: int = 1,
    ttl_seconds: int = 60,
) -> TrustedProxyCodexPhaseCellProvider:
    return TrustedProxyCodexPhaseCellProvider(
        source=source or _FakeSource(),
        supervisor=supervisor or _supervisor(),
        probe=_FakeProbe(),
        broker=broker,
        grant_store=store,
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        http_client=client,
        generation=generation,
        reasoning_effort=CodexReasoningEffort.HIGH,
        ttl_seconds=ttl_seconds,
        env=env if env is not None else dict(_TRUSTED_ENV),
    )


def _store_broker() -> tuple[MemoryModelProxyGrantStore, PhaseScopedModelProxyGrantBroker]:
    store = MemoryModelProxyGrantStore()
    return store, PhaseScopedModelProxyGrantBroker(store, max_ttl_seconds=120)


# --- D1: the wall fails closed before any provisioning or mint ---------------


async def test_acquire_refuses_before_admit_without_trusted_posture() -> None:
    store, broker = _store_broker()
    source = _FakeSource()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client, source=source, env={})
        with pytest.raises(CodexTrustedPostureError):
            await provider.acquire(_assignment())
    assert source.calls == 0
    assert store.snapshot() == ()


# --- D2: the supervisor must be constructed with auth=None -------------------


async def test_supervisor_with_upstream_auth_is_refused_at_construction() -> None:
    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        with pytest.raises(TrustedProxyProvisionError, match="auth=None"):
            _provider(
                broker=broker,
                store=store,
                client=client,
                supervisor=_supervisor(CodexUpstreamAuth("upstream-secret-token")),
            )


async def test_provider_holds_an_auth_none_supervisor() -> None:
    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
    assert provider._supervisor._auth is None


# --- D3 + mint: real /proc scope, bearer verifies via store_bearer_verifier --


async def test_mint_writes_bearer_that_verifies_via_store_verifier(
    tmp_path: Path, running_child: int
) -> None:
    store, broker = _store_broker()
    scope = build_cell_scope(_assignment(), _CELL_ID, running_child)
    assert scope.pid == running_child  # real /proc identity, not fabricated
    assert scope.boot_id and scope.cgroup_identity_digest.startswith("sha256:")
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
        await provider._mint_and_deliver(
            model_id=_MODEL_ID, cell_root=tmp_path, scope=scope, generation=1
        )
    bearer = (tmp_path / BEARER_FILENAME).read_text()
    assert bearer
    assert await store_bearer_verifier(store, generation=1)(bearer) is True
    # a foreign generation (a superseded/other rollout) does not verify
    assert await store_bearer_verifier(store, generation=2)(bearer) is False


# --- release: cancel refresh, revoke the grant, close the proxy --------------


async def test_teardown_cancels_refresh_revokes_grant_and_closes_proxy(
    tmp_path: Path, running_child: int
) -> None:
    store, broker = _store_broker()
    holder = GenerationHolder(1)
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
        proxy = PerCellModelProxyServer(
            verify_bearer=tracking_bearer_verifier(store, holder),
            upstream_base_url="http://gateway/v1",
            upstream_key="KERNEL-ONLY-KEY",
            client=client,
        )
        await proxy.start()
        scope = build_cell_scope(_assignment(), _CELL_ID, running_child)
        await provider._mint_and_deliver(
            model_id=_MODEL_ID, cell_root=tmp_path, scope=scope, generation=1
        )
        digest = hashlib.sha256(
            (tmp_path / BEARER_FILENAME).read_text().encode("ascii")
        ).hexdigest()
        assert await store.find_active_by_bearer_digest(digest, generation=1) is not None

        refresh: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))  # type: ignore[assignment]
        await provider._teardown(proxy, scope, refresh)

        assert refresh.cancelled()
        assert proxy._server is None
        assert await store.find_active_by_bearer_digest(digest, generation=1) is None


# --- config: the cell is pointed at the loopback proxy -----------------------


def test_config_points_the_cell_at_the_loopback_proxy(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    helper = tmp_path / "model_auth_helper"
    config_toml = render_trusted_config(
        cell_id="cell-001",
        cell_root=tmp_path,
        codex_home=codex_home,
        helper_path=helper,
        helper_sha256="sha256:" + "a" * 64,
        model_id=_MODEL_ID,
        policy_digest="sha256:" + "b" * 64,
        reasoning_effort=CodexReasoningEffort.HIGH,
        proxy_port=45123,
    )
    document = tomllib.loads(config_toml)
    provider = document["model_providers"]["boltrig_model_proxy"]  # type: ignore[index]
    assert provider["base_url"] == "http://127.0.0.1:45123/v1"
    assert provider["wire_api"] == "responses"
    assert provider["auth"]["command"] == helper.as_posix()
    assert provider["auth"]["args"] == ["--cell-id", "cell-001"]
    assert document["sandbox_mode"] == "read-only"


async def test_write_cell_config_materializes_helper_and_writes_config(
    tmp_path: Path,
) -> None:
    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
        codex_home = tmp_path / "codex-home"
        codex_home.mkdir()
        provider._write_cell_config(
            cell_id="cell-002",
            cell_root=tmp_path,
            codex_home=codex_home,
            model_id=_MODEL_ID,
            proxy_port=44001,
        )
    helper = tmp_path / "model_auth_helper"
    assert oct(helper.stat().st_mode & 0o777) == "0o700"
    document = tomllib.loads((codex_home / "config.toml").read_text())
    provider_block = document["model_providers"]["boltrig_model_proxy"]  # type: ignore[index]
    assert provider_block["base_url"] == "http://127.0.0.1:44001/v1"
