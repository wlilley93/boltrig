"""Unit tests for the trusted Codex socket ingress (Track 3, beat 3a).

Pins the three silent-until-live findings (canonical-vs-raw cgroup digest; the
squattable filesystem socket; the pre-drop capture that registered the spawner's
root credentials as a cell's expected identity) and the per-connection bearer
issuer, all without a real Codex App Server.
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
from boltrig.fleet.infrastructure.cell_privilege import PrivilegeError
from boltrig.fleet.infrastructure.codex_trusted_proxy_ingress import (
    CodexTrustedIngressError,
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

from .model_proxy_peer_fakes import ScriptedProcReader, install_process

# The two credentials the 2026-07-27 cv-boltrig-kernel-1 reject was between: the
# spawner's, which a freshly forked cell still carries, and slot-0's, which it holds
# for the rest of its life. _SIBLING_UID is a third, lawful nowhere.
_SPAWNER_UID = 0
_CELL_UID = 20001
_SIBLING_UID = 20004
_CELL_PID = 4242


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


def _cell_reader(*, uid: int, gid: int | None = None) -> ScriptedProcReader:
    """A /proc reporting one cell process at the given credentials.

    Scripted rather than real because the whole point is a reading this test
    process can never produce: a cell mid-drop, still at the spawner's uid.
    """

    reader = ScriptedProcReader()
    install_process(
        reader,
        pid=_CELL_PID,
        parent_pid=1,
        start_ticks=99_000,
        uid=uid,
        gid=uid if gid is None else gid,
    )
    return reader


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
    identity = capture_cell_identity(
        assignment,
        "cell-x",
        os.getpid(),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        reader=reader,
    )
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


# --- FINDING #3: what is REGISTERED is the allocation, not the snapshot ------


@pytest.mark.unit
def test_a_cell_captured_before_its_uid_drop_registers_its_allocated_uid() -> None:
    """The exact cv-boltrig-kernel-1 state (2026-07-27), and the fix.

    The spawner publishes a cell's pid from the fork PARENT, so the API can capture
    /proc while the child still carries the spawner's root credentials. Registering
    that snapshot was not a visible failure - it produced a registration that could
    never be attested, so the break surfaced later and elsewhere as "registered
    process present but uid/gid differs", with no bearer, no model call and no tool
    call. The identity registered must be the one the cell was ALLOCATED.
    """

    identity = capture_cell_identity(
        _assignment(),
        "cell-pre-drop",
        _CELL_PID,
        expected_uid=_CELL_UID,
        expected_gid=_CELL_UID,
        reader=_cell_reader(uid=_SPAWNER_UID),
    )

    assert identity.uid == _CELL_UID  # NOT the 0 that /proc reported
    assert identity.gid == _CELL_UID
    assert identity.scope.pid == _CELL_PID


@pytest.mark.unit
def test_a_cell_captured_mid_drop_registers_its_allocated_uid() -> None:
    """drop_privileges runs setgid before setuid, so (uid 0, gid 20001) is real.

    Pinned separately because a fix that demanded the pair move together would look
    correct against both settled readings and still refuse this lawful instant,
    replacing the original race with a second one.
    """

    identity = capture_cell_identity(
        _assignment(),
        "cell-mid-drop",
        _CELL_PID,
        expected_uid=_CELL_UID,
        expected_gid=_CELL_UID,
        reader=_cell_reader(uid=_SPAWNER_UID, gid=_CELL_UID),
    )

    assert (identity.uid, identity.gid) == (_CELL_UID, _CELL_UID)


@pytest.mark.unit
def test_a_settled_cell_registers_the_same_allocated_uid() -> None:
    """The post-drop reading registers identically, so the race has no effect left.

    Without this the two tests above could be satisfied by a function that ignored
    /proc entirely and always echoed its argument, which is not what shipped: the
    capture still has to agree with the allocation, as the next test shows.
    """

    identity = capture_cell_identity(
        _assignment(),
        "cell-settled",
        _CELL_PID,
        expected_uid=_CELL_UID,
        expected_gid=_CELL_UID,
        reader=_cell_reader(uid=_CELL_UID),
    )

    assert (identity.uid, identity.gid) == (_CELL_UID, _CELL_UID)


@pytest.mark.unit
def test_a_capture_that_is_neither_settled_nor_pre_drop_is_refused() -> None:
    """Fail closed: the capture is a cross-check, and it still has to pass.

    A process at a SIBLING slot's uid is neither the identity this cell was
    allocated nor the spawner's, so it is not this cell at all. Registering it would
    bind one cell's bearer path to another cell's process, which is the VJS-CC-VJS 5
    cross-tenant failure the per-cell uid band exists to end.
    """

    for reader in (
        _cell_reader(uid=_SIBLING_UID),
        _cell_reader(uid=_CELL_UID, gid=_SIBLING_UID),
    ):
        with pytest.raises(CodexTrustedIngressError, match="neither expected nor pre-drop"):
            capture_cell_identity(
                _assignment(),
                "cell-foreign",
                _CELL_PID,
                expected_uid=_CELL_UID,
                expected_gid=_CELL_UID,
                reader=reader,
            )


@pytest.mark.unit
def test_a_root_cell_identity_is_refused_before_anything_is_read() -> None:
    """No cell is ever lawfully root, in either posture.

    Live in-process, where the expectation is the API's own ids: an API left running
    as root would otherwise register root as a cell's lawful identity, and
    _path_obeys_cell_policy would then accept an entirely root-owned helper chain.
    """

    for uid, gid in ((_SPAWNER_UID, _CELL_UID), (_CELL_UID, _SPAWNER_UID)):
        with pytest.raises(CodexTrustedIngressError, match="never be registered as root"):
            capture_cell_identity(
                _assignment(),
                "cell-root",
                _CELL_PID,
                expected_uid=uid,
                expected_gid=gid,
                reader=_cell_reader(uid=_CELL_UID),
            )


@pytest.mark.unit
def test_the_expected_credentials_are_required_and_must_be_exact_ints() -> None:
    """No default, because a caller that cannot name the cell's identity cannot
    register it either. A default would silently restore the racy snapshot at the
    first call site that forgot, which is how this defect shipped in the first place.
    """

    with pytest.raises(TypeError):
        capture_cell_identity(  # type: ignore[call-arg]
            _assignment(), "cell-missing", _CELL_PID, reader=_cell_reader(uid=_CELL_UID)
        )
    with pytest.raises(TypeError, match="exact ints"):
        capture_cell_identity(
            _assignment(),
            "cell-bool",
            _CELL_PID,
            expected_uid=True,  # bool is an int subclass; exact types only
            expected_gid=_CELL_UID,
            reader=_cell_reader(uid=_CELL_UID),
        )


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
        expected_cell_uid=None,
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
        expected_cell_uid=None,
    )

    await registry.revoke(scope)

    with pytest.raises(ModelProxyPeerRegistryError):
        await issuer(scope)
    assert broker.generations == []  # nothing was minted


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "linux", reason="build_cell_scope reads this process /proc")
async def test_a_declared_cell_uid_is_confirmed_by_the_kernel_before_any_mint() -> None:
    """FINDING #3's confirming half: a declaration nobody confirms is not a boundary.

    Registration now DECLARES the cell's uid from its slot rather than observing it,
    so the kernel is asked, on the pid and at the instant of trust, whether the cell
    really holds it. This process does not hold _CELL_UID, so issuance must refuse
    and nothing may be minted - the same refusal a cell that dropped to a SIBLING
    slot's uid would get, which "some unprivileged uid" would have waved through.
    """

    broker = _FakeBroker()
    registry = ModelProxyProcessRegistry()
    scope = _cell_scope("cell-declared")
    await registry.register(scope, expected_uid=os.getuid(), expected_gid=os.getgid())
    issuer = build_ingress_bearer_issuer(
        broker=cast(PhaseScopedModelProxyGrantBroker, broker),
        registry=registry,
        model_id="glm-4.6",
        policy_digest="sha256:" + "a" * 64,
        budget=read_only_budget(),
        ttl_seconds=30,
        holder=GenerationHolder(1),
        expected_cell_uid=_CELL_UID,
    )

    with pytest.raises(PrivilegeError):
        await issuer(scope)
    assert broker.generations == []


@pytest.mark.unit
def test_the_issuer_refuses_a_root_or_malformed_expected_cell_uid() -> None:
    """The confirmation target must itself be a lawful cell uid.

    ``expected_cell_uid=0`` would ask the kernel to confirm that the cell IS root,
    inverting the check into a hazard; a bool would silently confirm uid 1. Both are
    refused at construction, before any listener can serve.
    """

    broker = _FakeBroker()
    for bad in (0, True, "20001"):
        with pytest.raises(CodexTrustedIngressError, match="non-root uid"):
            build_ingress_bearer_issuer(
                broker=cast(PhaseScopedModelProxyGrantBroker, broker),
                registry=ModelProxyProcessRegistry(),
                model_id="glm-4.6",
                policy_digest="sha256:" + "a" * 64,
                budget=read_only_budget(),
                ttl_seconds=30,
                holder=GenerationHolder(1),
                expected_cell_uid=cast(int, bad),
            )
