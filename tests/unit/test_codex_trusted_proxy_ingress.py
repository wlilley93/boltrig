"""Unit tests for the trusted Codex socket ingress (Track 3, beat 3a).

Pins the two silent-until-live findings (canonical-vs-raw cgroup digest; the short
AF_UNIX socket path) and the per-connection bearer issuer, all without a real
Codex App Server.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from boltrig.fleet.domain.execution import (
    OrganisationUserRef,
    PhaseAssignmentRef,
    PhaseRef,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyCellScope,
    ModelProxyGrantBinding,
)
from boltrig.fleet.application.model_proxy_grants import PhaseScopedModelProxyGrantBroker
from boltrig.fleet.infrastructure.codex_trusted_proxy_ingress import (
    CodexTrustedIngressError,
    build_ingress_bearer_issuer,
    capture_cell_identity,
    select_ingress_socket_path,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    GenerationHolder,
    build_cell_scope,
    read_only_budget,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyPeerRegistryError,
    ModelProxyProcessRegistry,
)
from boltrig.fleet.infrastructure.linux_peer_identity import (
    LinuxProcReader,
    capture_linux_process,
    read_boot_id,
)
from boltrig.fleet.infrastructure.model_proxy_peer_listener import (
    MAX_UNIX_SOCKET_PATH_BYTES,
)


def _assignment() -> PhaseAssignmentRef:
    return PhaseAssignmentRef(
        PhaseRef(
            root_run_id="run-ingress",
            phase_id="phase-ingress",
            principal=OrganisationUserRef("org-1", "user-1"),
            workspace_id="workspace-1",
        ),
        "assignment-ingress",
    )


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "linux", reason="captures this Linux process /proc identity")
def test_capture_cell_identity_uses_the_canonical_digest_not_the_raw_hash() -> None:
    """FINDING #1: the registered scope must match what attestation derives.

    capture_cell_identity sources identity from capture_linux_process (canonical
    cgroup digest), so its digest equals canonical_cgroup_digest and does NOT equal
    build_cell_scope's raw-bytes hash - which is exactly why attestation would fail
    if the observed build_cell_scope were registered instead.
    """

    assignment = _assignment()
    reader = LinuxProcReader()
    identity = capture_cell_identity(assignment, "cell-x", os.getpid(), reader=reader)
    observed = build_cell_scope(assignment, "cell-x", os.getpid())

    # Equals the canonical digest attestation itself derives via capture_linux_process.
    captured = capture_linux_process(reader, os.getpid(), expected_boot_id=read_boot_id(reader))
    assert identity.scope.cgroup_identity_digest == captured.cgroup_identity_digest
    # The whole point: the two digests differ, so registering the observed scope
    # would break every ancestry attestation.
    assert identity.scope.cgroup_identity_digest != observed.cgroup_identity_digest
    # The assignment identity mapping is otherwise identical.
    assert identity.scope.assignment == observed.assignment
    assert identity.scope.cell_id == observed.cell_id == "cell-x"
    assert identity.scope.pid == observed.pid == os.getpid()
    assert identity.uid == os.getuid()
    assert identity.gid == os.getgid()


@pytest.mark.unit
def test_select_ingress_socket_path_is_short_and_at_the_stack_root_base() -> None:
    """FINDING #2: bind at the short stack-root base, never the deep cell_root."""

    stack_root = Path("/var/lib/boltrig/codex-cells")
    path = select_ingress_socket_path(stack_root, "some-long-cell-id-abc123")
    assert path.parent == stack_root
    assert path.name.startswith("mp-") and path.suffix == ".sock"
    assert len(os.fsencode(os.fspath(path))) <= MAX_UNIX_SOCKET_PATH_BYTES
    # Deterministic in the cell id.
    assert select_ingress_socket_path(stack_root, "some-long-cell-id-abc123") == path
    assert select_ingress_socket_path(stack_root, "other-cell") != path


@pytest.mark.unit
def test_select_ingress_socket_path_rejects_a_relative_stack_root() -> None:
    with pytest.raises(CodexTrustedIngressError):
        select_ingress_socket_path(Path("relative/root"), "cell")


@dataclass
class _RevealBearer:
    _value: str

    def reveal(self) -> str:
        return self._value


@dataclass
class _Issued:
    bearer: _RevealBearer


class _FakeBroker:
    def __init__(self) -> None:
        self.generations: list[int] = []
        self.cells: list[str] = []

    async def issue(
        self, request_id: str, binding: ModelProxyGrantBinding, *, ttl_seconds: int, generation: int
    ) -> _Issued:
        self.generations.append(generation)
        self.cells.append(binding.cell.cell_id)
        return _Issued(_RevealBearer(f"bearer-gen-{generation}"))


def _cell_scope(cell_id: str) -> ModelProxyCellScope:
    return build_cell_scope(_assignment(), cell_id, os.getpid())


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "linux", reason="build_cell_scope reads this process /proc")
async def test_bearer_issuer_mints_per_attested_scope_at_rising_generation() -> None:
    broker = _FakeBroker()
    holder = GenerationHolder(1)
    registry = ModelProxyProcessRegistry()
    scope = _cell_scope("cell-issuer")
    await registry.register(scope, expected_uid=os.getuid(), expected_gid=os.getgid())
    issuer = build_ingress_bearer_issuer(
        broker=cast(PhaseScopedModelProxyGrantBroker, broker),
        registry=registry,
        model_id="glm-4.6",
        policy_digest="sha256:" + "a" * 64,
        budget=read_only_budget(),
        ttl_seconds=30,
        holder=holder,
    )

    first = await issuer(scope)
    second = await issuer(scope)

    assert first == b"bearer-gen-2"  # holder starts at 1, bumped before mint
    assert second == b"bearer-gen-3"
    assert broker.generations == [2, 3]  # strictly increasing per connection
    assert broker.cells == ["cell-issuer", "cell-issuer"]  # bound to the attested cell


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "linux", reason="build_cell_scope reads this process /proc")
async def test_a_revoked_cell_is_refused_a_bearer_at_issuance() -> None:
    """A cell revoked between attestation and mint must get nothing."""

    broker = _FakeBroker()
    registry = ModelProxyProcessRegistry()
    scope = _cell_scope("cell-revoked")
    await registry.register(scope, expected_uid=os.getuid(), expected_gid=os.getgid())
    issuer = build_ingress_bearer_issuer(
        broker=cast(PhaseScopedModelProxyGrantBroker, broker),
        registry=registry,
        model_id="glm-4.6",
        policy_digest="sha256:" + "a" * 64,
        budget=read_only_budget(),
        ttl_seconds=30,
        holder=GenerationHolder(1),
    )

    await registry.revoke(scope)

    with pytest.raises(ModelProxyPeerRegistryError):
        await issuer(scope)
    assert broker.generations == []  # nothing was minted
