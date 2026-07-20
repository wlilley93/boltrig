"""Unit tests for the trusted Codex socket ingress (Track 3, beat 3a).

Pins the two silent-until-live findings (canonical-vs-raw cgroup digest; the short
AF_UNIX socket path) and the per-connection bearer issuer, all without a real
Codex App Server.
"""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass
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
    build_ingress_bearer_issuer,
    capture_cell_identity,
    select_ingress_socket_name,
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
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_listener import (
    MAX_UNIX_SOCKET_PATH_BYTES,
    PeerAttestationListenerError,
    PeerAttestationUnixListener,
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
def test_select_ingress_socket_name_is_abstract_unguessable_and_within_bound() -> None:
    """FINDING #2: no filesystem presence to squat, and no predictable name.

    The old name was a path under the uid-10001 tmpfs derived from the cell id, so
    a sibling cell could pre-create the exact file and be handed another cell's
    bearer. Determinism was the vulnerability, which is why this asserts the
    opposite of what the old test asserted.
    """

    name = select_ingress_socket_name()
    assert name.startswith("@boltrig-mp-")
    assert "/" not in name and "\x00" not in name  # survives TOML and execve argv
    # The kernel bound applies to abstract names too, counted with the NUL.
    assert len(os.fsencode("\0" + name[1:])) <= MAX_UNIX_SOCKET_PATH_BYTES
    # Unguessable: a fresh name every time, so the bind race cannot be won by
    # deriving the name from anything the other cell knows.
    assert select_ingress_socket_name() != name


@pytest.mark.unit
def test_a_squatted_abstract_name_fails_closed_rather_than_being_replaced() -> None:
    """An abstract name already held cannot be silently taken over.

    A filesystem socket can be unlinked and re-bound by anyone who can write the
    directory; an abstract one cannot. A second bind is EADDRINUSE, so the ingress
    refuses to start instead of serving on a socket a squatter also holds.
    """

    name = select_ingress_socket_name()
    squatter = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        squatter.bind("\0" + name[1:])
        squatter.listen(1)
        attestor = LinuxModelProxyPeerAttestor(ModelProxyProcessRegistry())
        with pytest.raises(PeerAttestationListenerError):
            PeerAttestationUnixListener.bind(name, attestor)
    finally:
        squatter.close()


@pytest.mark.unit
def test_the_listener_refuses_a_name_that_is_not_in_the_at_form() -> None:
    attestor = LinuxModelProxyPeerAttestor(ModelProxyProcessRegistry())
    for bad in ("", "@", "boltrig-mp-abc", "/tmp/attacker.sock"):
        with pytest.raises(PeerAttestationListenerError):
            PeerAttestationUnixListener.bind(bad, attestor)


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
