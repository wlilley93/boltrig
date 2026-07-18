"""Pure bounded ancestry proof run inside the dedicated capture executor."""

from __future__ import annotations

from .linux_peer_identity import (
    CapturedLinuxProcess,
    PeerCredentials,
    ProcReader,
    capture_linux_process,
    read_boot_id,
)
from .linux_peer_process_handle import PeerProcessHandle
from .model_proxy_peer_registry import ModelProxyProcessRegistration


class ModelProxyPeerAncestryError(RuntimeError):
    """The peer ancestry did not match exactly one registered process."""


def attest_peer_ancestry(
    reader: ProcReader,
    handle: PeerProcessHandle,
    registrations: tuple[ModelProxyProcessRegistration, ...],
    max_ancestry: int,
) -> ModelProxyProcessRegistration:
    """Capture and recheck one peer chain while its kernel pidfd is held."""

    handle.assert_alive()
    credentials = handle.credentials
    boot_id = read_boot_id(reader)
    first_chain = _capture_chain(
        reader, credentials.pid, boot_id=boot_id, max_ancestry=max_ancestry
    )
    registration, registered_depth = _select_registration(first_chain, registrations, credentials)
    if read_boot_id(reader) != boot_id:
        raise ModelProxyPeerAncestryError("peer ancestry changed")
    second_chain = _capture_chain(
        reader,
        credentials.pid,
        boot_id=boot_id,
        max_ancestry=registered_depth,
    )
    if first_chain[: registered_depth + 1] != second_chain:
        raise ModelProxyPeerAncestryError("peer ancestry changed")
    if read_boot_id(reader) != boot_id:
        raise ModelProxyPeerAncestryError("peer ancestry changed")
    handle.assert_alive()
    return registration


def _capture_chain(
    reader: ProcReader,
    helper_pid: int,
    *,
    boot_id: str,
    max_ancestry: int,
) -> tuple[CapturedLinuxProcess, ...]:
    current_pid = helper_pid
    seen: set[int] = set()
    chain: list[CapturedLinuxProcess] = []
    for _depth in range(max_ancestry + 1):
        if current_pid in seen:
            raise ModelProxyPeerAncestryError("peer ancestry cycle")
        seen.add(current_pid)
        process = capture_linux_process(reader, current_pid, expected_boot_id=boot_id)
        chain.append(process)
        if process.parent_pid in seen:
            raise ModelProxyPeerAncestryError("peer ancestry cycle")
        if process.pid == 1 or process.parent_pid == 0:
            break
        current_pid = process.parent_pid
    return tuple(chain)


def _select_registration(
    chain: tuple[CapturedLinuxProcess, ...],
    registrations: tuple[ModelProxyProcessRegistration, ...],
    credentials: PeerCredentials,
) -> tuple[ModelProxyProcessRegistration, int]:
    if not chain or not _peer_matches_helper(chain[0], credentials):
        raise ModelProxyPeerAncestryError("peer identity mismatch")
    matches: list[tuple[ModelProxyProcessRegistration, int]] = []
    for depth, process in enumerate(chain[1:], start=1):
        for registration in registrations:
            if _registration_matches_process(registration, process):
                matches.append((registration, depth))
    if len(matches) != 1:
        raise ModelProxyPeerAncestryError("peer ancestry is ambiguous")
    registration, depth = matches[0]
    if not _path_obeys_cell_policy(chain[: depth + 1], registration):
        raise ModelProxyPeerAncestryError("peer path policy mismatch")
    return registration, depth


def _peer_matches_helper(helper: CapturedLinuxProcess, credentials: PeerCredentials) -> bool:
    return (
        helper.pid == credentials.pid
        and helper.uid == credentials.uid
        and helper.gid == credentials.gid
    )


def _registration_matches_process(
    registration: ModelProxyProcessRegistration,
    process: CapturedLinuxProcess,
) -> bool:
    scope = registration.scope
    return (
        scope.pid == process.pid
        and scope.pid_start_ticks == process.start_ticks
        and scope.boot_id == process.boot_id
        and scope.pid_namespace_inode == process.pid_namespace_inode
        and scope.cgroup_identity_digest == process.cgroup_identity_digest
        and registration.expected_uid == process.uid
        and registration.expected_gid == process.gid
    )


def _path_obeys_cell_policy(
    path: tuple[CapturedLinuxProcess, ...],
    registration: ModelProxyProcessRegistration,
) -> bool:
    scope = registration.scope
    return all(
        process.boot_id == scope.boot_id
        and process.pid_namespace_inode == scope.pid_namespace_inode
        and process.cgroup_identity_digest == scope.cgroup_identity_digest
        and process.uid == registration.expected_uid
        and process.gid == registration.expected_gid
        for process in path
    )


__all__ = ["ModelProxyPeerAncestryError", "attest_peer_ancestry"]
