"""The peer uid is bound to the cell's uid ([2026] VJS-CC-VJS 7 J8).

J8 ordered peer attestation extended to require the connecting peer's uid to equal
the cell's assigned uid, because the ingress socket is ABSTRACT and therefore
carries no filesystem permission bits: distinct uids confer nothing at that surface
on their own.

On reading the code the property is already there. ``_path_obeys_cell_policy``
requires every process in the attested slice to match ``expected_uid``, and the
slice INCLUDES ``chain[0]``, which ``_peer_matches_helper`` has already bound to
the ``SO_PEERCRED`` credentials of the connecting socket. So the peer uid is
compared today.

That reading is not a discharge. VJS-CC-VJS 5 expressly forbids discharging an
acceptance condition "by argument or review or the absence of a known attack
rather than by the adversarial test itself", and no test exercised these
predicates at all. These are that test. If a refactor ever drops ``chain[0]`` from
the policy slice, or compares only the ancestor, this fails.
"""

from __future__ import annotations

import pytest

from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
)
from boltrig.fleet.infrastructure.linux_peer_identity import (
    CapturedLinuxProcess,
    PeerCredentials,
)
from boltrig.fleet.infrastructure.model_proxy_peer_ancestry import (
    _path_obeys_cell_policy,
    _peer_matches_helper,
    _registration_matches_process,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistration,
)

_BOOT = "0123abcd-4567-89ef-0123-456789abcdef"
_CGROUP = "sha256:" + "c" * 64
_CELL_UID = 20001
_SIBLING_UID = 20002


def _process(pid: int, *, uid: int = _CELL_UID, parent: int = 0) -> CapturedLinuxProcess:
    return CapturedLinuxProcess(
        pid=pid,
        parent_pid=parent,
        start_ticks=1000 + pid,
        boot_id=_BOOT,
        pid_namespace_inode=4026531836,
        cgroup_identity_digest=_CGROUP,
        uid=uid,
        gid=uid,
    )


def _registration(process: CapturedLinuxProcess) -> ModelProxyProcessRegistration:
    root = ModelProxyRootScope("tenant-a", "ws-1", "run-1")
    scope = ModelProxyCellScope(
        ModelProxyAssignmentScope(ModelProxyPhaseScope(root, "phase-1"), "assignment-1"),
        "cell-1",
        process.pid,
        process.start_ticks,
        process.boot_id,
        process.pid_namespace_inode,
        process.cgroup_identity_digest,
    )
    return ModelProxyProcessRegistration(
        scope=scope, expected_uid=_CELL_UID, expected_gid=_CELL_UID, sequence=1
    )


@pytest.mark.unit
def test_the_connecting_peer_uid_must_equal_the_cells_uid() -> None:
    """The J8 property: chain[0] is IN the policy slice, so its uid is checked.

    A helper running as a SIBLING cell's uid is refused even though its ancestry,
    cgroup, pid namespace and boot id are all correct. That is the case the
    abstract socket cannot refuse on its own.
    """

    app_server = _process(100)
    registration = _registration(app_server)

    own_helper = _process(101, uid=_CELL_UID, parent=100)
    assert _path_obeys_cell_policy((own_helper, app_server), registration) is True

    sibling_helper = _process(101, uid=_SIBLING_UID, parent=100)
    assert _path_obeys_cell_policy((sibling_helper, app_server), registration) is False


@pytest.mark.unit
def test_the_registered_app_server_uid_must_match_too() -> None:
    """Not only the peer: the attested ancestor is bound to the same uid."""

    foreign = _process(100, uid=_SIBLING_UID)
    assert _registration_matches_process(_registration(_process(100)), foreign) is False
    assert _registration_matches_process(_registration(_process(100)), _process(100)) is True


@pytest.mark.unit
def test_the_socket_credentials_are_bound_to_the_captured_helper() -> None:
    """chain[0] is not taken on trust; it must match SO_PEERCRED exactly.

    This is the join that makes the uid check meaningful: without it the chain
    could describe some other process entirely.
    """

    helper = _process(101, uid=_CELL_UID)
    assert _peer_matches_helper(helper, PeerCredentials(pid=101, uid=_CELL_UID, gid=_CELL_UID))
    for wrong in (
        PeerCredentials(pid=101, uid=_SIBLING_UID, gid=_CELL_UID),
        PeerCredentials(pid=101, uid=_CELL_UID, gid=_SIBLING_UID),
        PeerCredentials(pid=999, uid=_CELL_UID, gid=_CELL_UID),
    ):
        assert _peer_matches_helper(helper, wrong) is False


@pytest.mark.unit
def test_an_intermediate_process_of_a_foreign_uid_breaks_the_path() -> None:
    """Every hop is checked, not just the two ends.

    A cell that could interpose one foreign-uid process between the App Server and
    the helper would otherwise satisfy both endpoint checks.
    """

    app_server = _process(100)
    middle = _process(150, uid=_SIBLING_UID, parent=100)
    helper = _process(101, uid=_CELL_UID, parent=150)
    assert _path_obeys_cell_policy((helper, middle, app_server), _registration(app_server)) is False
