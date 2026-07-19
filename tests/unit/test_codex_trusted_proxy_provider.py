"""Tests for the trusted read-only Codex proxy provider ([2026] VJS-CC-VJS 1/2/3).

Security-critical: a fail-open in issuance or an upstream-key leak is the
catastrophic failure. These pin the load-bearing directives without running the
live Codex turn (the in-container re-proof runs that on the real box):

  * D1 - the dev/prod wall fails closed BEFORE any admit or issuance.
  * D2 - the supervisor is constructed with auth=None (the child env never carries
    the upstream key).
  * a bearer minted through the ingress issuer verifies via the store verifier, and
    teardown revokes the grant, closes the proxy, and closes the ingress.
  * the rendered config.toml points the cell at the loopback proxy + socket helper.

Option-B delivery (VJS-CC-VJS 3): there is NO bearer file at rest. The per-cell
socket ingress + issuer lifecycle is covered in test_codex_trusted_proxy_ingress.py
and test_codex_trusted_ingress_live.py; the auth.command helper in
test_codex_trusted_proxy_helper.py.
"""

from __future__ import annotations

import hashlib
import os
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
)
from boltrig.fleet.infrastructure.codex_runtime_config import CodexReasoningEffort
from boltrig.fleet.infrastructure.codex_trusted_proxy_ingress import (
    CodexTrustedIngress,
    build_ingress_bearer_issuer,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
    TrustedProxyCodexPhaseCellProvider,
    TrustedProxyProvisionError,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    GenerationHolder,
    build_cell_scope,
    read_only_budget,
    render_trusted_config,
    tracking_bearer_verifier,
)
from boltrig.fleet.infrastructure.memory_model_proxy_grants import (
    MemoryModelProxyGrantStore,
)
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistry,
)
from boltrig.models.execution_scope import OrganisationUserRef

_CODEX_BIN = Path("/opt/boltrig/codex/codex")
_CELL_ID = "cell-abc1234567890ab"
_MODEL_ID = "gpt-5.2-codex"
_POLICY_DIGEST = "sha256:" + "b" * 64
# /bin/sh stands in for the baked image helper: root-owned, executable, on a
# directory chain this account cannot write ([2026] VJS-CC-VJS 5 G2).
_TEST_SHARED_HELPER = os.path.realpath("/bin/sh")
_TRUSTED_ENV = {
    "BOLTRIG_DEV_AUTH": "1",
    "BOLTRIG_CODEX_TRUSTED": "1",
    "BOLTRIG_CODEX_AUTH_HELPER": _TEST_SHARED_HELPER,
}


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
    registry: ModelProxyProcessRegistry | None = None,
    attestor: LinuxModelProxyPeerAttestor | None = None,
) -> TrustedProxyCodexPhaseCellProvider:
    reg = registry if registry is not None else ModelProxyProcessRegistry()
    att = attestor if attestor is not None else LinuxModelProxyPeerAttestor(reg)
    return TrustedProxyCodexPhaseCellProvider(
        source=source or _FakeSource(),
        supervisor=supervisor or _supervisor(),
        probe=_FakeProbe(),
        broker=broker,
        grant_store=store,
        registry=reg,
        attestor=att,
        stack_root=Path("/tmp"),
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


# --- D1: the wall fails closed before any provisioning or issuance -----------


async def test_acquire_refuses_before_admit_without_trusted_posture() -> None:
    store, broker = _store_broker()
    source = _FakeSource()
    async with httpx.AsyncClient() as client:
        provider = _provider(
            broker=broker,
            store=store,
            client=client,
            source=source,
            env={"BOLTRIG_CODEX_AUTH_HELPER": _TEST_SHARED_HELPER},
        )
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


async def test_provider_requires_an_absolute_stack_root() -> None:
    store, broker = _store_broker()
    reg = ModelProxyProcessRegistry()
    async with httpx.AsyncClient() as client:
        with pytest.raises(TrustedProxyProvisionError, match="stack_root"):
            TrustedProxyCodexPhaseCellProvider(
                source=_FakeSource(),
                supervisor=_supervisor(),
                probe=_FakeProbe(),
                broker=broker,
                grant_store=store,
                registry=reg,
                attestor=LinuxModelProxyPeerAttestor(reg),
                stack_root=Path("relative/root"),
                upstream_base_url="http://gateway/v1",
                upstream_key="KERNEL-ONLY-KEY",
                http_client=client,
            )


# --- issuance + teardown: no bearer file, grant revoked, proxy + ingress closed --


@pytest.mark.skipif(sys.platform != "linux", reason="build_cell_scope reads /proc")
async def test_teardown_revokes_grant_and_closes_proxy_and_ingress(
    tmp_path: Path, running_child: int
) -> None:
    store, broker = _store_broker()
    registry = ModelProxyProcessRegistry()
    attestor = LinuxModelProxyPeerAttestor(registry)
    async with httpx.AsyncClient() as client:
        provider = _provider(
            broker=broker, store=store, client=client, registry=registry, attestor=attestor
        )
        proxy = PerCellModelProxyServer(
            verify_bearer=tracking_bearer_verifier(store, GenerationHolder(1)),
            upstream_base_url="http://gateway/v1",
            upstream_key="KERNEL-ONLY-KEY",
            client=client,
        )
        await proxy.start()

        scope = build_cell_scope(_assignment(), _CELL_ID, running_child)
        # The issuer mints only under a LIVE registration (the issuance TOCTOU),
        # so the scope must be registered before a bearer can exist.
        await registry.register(scope, expected_uid=os.getuid(), expected_gid=os.getgid())
        issuer = build_ingress_bearer_issuer(
            broker=broker,
            registry=registry,
            model_id=_MODEL_ID,
            policy_digest=_POLICY_DIGEST,
            budget=read_only_budget(),
            ttl_seconds=60,
            holder=GenerationHolder(1),
        )
        # The issuer mints a fresh single-cell bearer per attested connection; the
        # first mint bumps the holder to generation 2. No file is ever written.
        bearer = await issuer(scope)
        assert isinstance(bearer, bytes) and bearer
        digest = hashlib.sha256(bearer).hexdigest()
        assert await store.find_active_by_bearer_digest(digest, generation=2) is not None
        assert not any((tmp_path).iterdir())  # nothing at rest under the cell dir

        ingress = CodexTrustedIngress(  # unstarted: aclose is a safe no-op
            registry,
            attestor,
            stack_root=Path("/tmp"),
            boundary=provider._boundary,
        )
        await provider._teardown(proxy, scope, ingress)

        assert proxy._server is None
        assert await store.find_active_by_bearer_digest(digest, generation=2) is None


# --- config: the cell is pointed at the loopback proxy + socket helper --------


def test_config_points_the_cell_at_the_loopback_proxy(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    # G2: the helper is the SHARED root-owned program, never a per-cell file.
    helper = Path(_TEST_SHARED_HELPER)
    config_toml = render_trusted_config(
        cell_id="cell-001",
        cell_root=tmp_path,
        codex_home=codex_home,
        helper_path=helper,
        helper_sha256="sha256:" + "a" * 64,
        socket_path=tmp_path / "mp-deadbeef.sock",
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
    assert provider["auth"]["args"] == [
        "--cell-id",
        "cell-001",
        "--socket",
        (tmp_path / "mp-deadbeef.sock").as_posix(),
    ]
    assert document["sandbox_mode"] == "read-only"


async def test_write_cell_config_writes_no_executable_into_the_cell_root(
    tmp_path: Path,
) -> None:
    store, broker = _store_broker()
    async with httpx.AsyncClient() as client:
        provider = _provider(broker=broker, store=store, client=client)
        codex_home = tmp_path / "codex-home"
        codex_home.mkdir()
        socket_path = tmp_path / "mp-deadbeef.sock"
        provider._write_cell_config(
            cell_id="cell-002",
            cell_root=tmp_path,
            codex_home=codex_home,
            model_id=_MODEL_ID,
            proxy_port=44001,
            socket_path=socket_path,
        )
    # G2: nothing executable is written into the mutable cell root any more; the
    # helper is the one root-owned program on the read-only image mount.
    assert not (tmp_path / "model_auth_helper").exists()
    assert [entry.name for entry in tmp_path.iterdir()] == ["codex-home"]
    document = tomllib.loads((codex_home / "config.toml").read_text())
    provider_block = document["model_providers"]["boltrig_model_proxy"]  # type: ignore[index]
    assert provider_block["base_url"] == "http://127.0.0.1:44001/v1"
