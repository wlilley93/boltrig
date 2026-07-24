"""Pure bounded ancestry proof run inside the dedicated capture executor."""

from __future__ import annotations

from .linux_peer_identity import (
    CapturedLinuxProcess,
    PeerCredentials,
    ProcReader,
    capture_linux_process,
    read_boot_id,
    read_pid_namespace_inode,
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
    # The helper and its ancestors run at the CELL uid (2000N), whose restricted
    # /proc/<pid>/ns/pid the capless API cannot read. Every one of them shares THIS
    # container's single pid namespace (no CLONE_NEWPID), so the inode is an invariant
    # read from self; supplying it lets the ancestry capture complete without the
    # cross-uid read. The registered cell scope carries the same container inode
    # (capture_cell_identity sources it identically), so the match still holds.
    container_pid_ns = read_pid_namespace_inode(reader)
    first_chain = _capture_chain(
        reader,
        credentials.pid,
        boot_id=boot_id,
        max_ancestry=max_ancestry,
        pid_namespace_inode=container_pid_ns,
    )
    registration, registered_depth = _select_registration(first_chain, registrations, credentials)
    if read_boot_id(reader) != boot_id:
        raise ModelProxyPeerAncestryError("peer ancestry changed")
    second_chain = _capture_chain(
        reader,
        credentials.pid,
        boot_id=boot_id,
        max_ancestry=registered_depth,
        pid_namespace_inode=container_pid_ns,
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
    pid_namespace_inode: int | None = None,
) -> tuple[CapturedLinuxProcess, ...]:
    current_pid = helper_pid
    seen: set[int] = set()
    chain: list[CapturedLinuxProcess] = []
    for _depth in range(max_ancestry + 1):
        if current_pid in seen:
            raise ModelProxyPeerAncestryError("peer ancestry cycle")
        seen.add(current_pid)
        process = capture_linux_process(
            reader, current_pid, expected_boot_id=boot_id, pid_namespace_inode=pid_namespace_inode
        )
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
    if len(matches) > 1:
        # Two registered App Servers in one chain: genuinely ambiguous. Effectively
        # impossible in the single-cell posture, so almost always the >1 case is a
        # test or a registry leak, NOT the cold-cell failure below.
        raise ModelProxyPeerAncestryError("peer ancestry is ambiguous")
    if not matches:
        # The common cold-cell failure is ZERO matches, which the old overloaded
        # "ambiguous" message hid. Name the STRUCTURAL near-miss field (never a
        # value - the reason is content-free and safe to log) so a cold-cell reject
        # is self-diagnosing rather than a mystery.
        raise ModelProxyPeerAncestryError(
            f"peer ancestry has no registered ancestor ({_zero_match_reason(chain, registrations)})"
        )
    registration, depth = matches[0]
    if not _path_obeys_cell_policy(chain[: depth + 1], registration):
        raise ModelProxyPeerAncestryError("peer path policy mismatch")
    return registration, depth


def _zero_match_reason(
    chain: tuple[CapturedLinuxProcess, ...],
    registrations: tuple[ModelProxyProcessRegistration, ...],
) -> str:
    """A content-free descriptor of WHY no ancestor matched, for the server log.

    Reports only the first differing STRUCTURAL field of a strong-identity
    near-miss (an ancestor whose pid + start-ticks + boot equal a registration's,
    so it IS the registered App Server, but a policy field drifted) - never any
    value. When no ancestor even shares the strong identity, the App Server is not
    in the captured ancestry at all (reparent, the depth bound, or a pid-namespace
    boundary). This turns the intermittent cold-cell reject into a named cause.
    """
    for process in chain[1:]:
        for registration in registrations:
            scope = registration.scope
            if not (
                scope.pid == process.pid
                and scope.pid_start_ticks == process.start_ticks
                and scope.boot_id == process.boot_id
            ):
                continue
            if scope.pid_namespace_inode != process.pid_namespace_inode:
                return "registered process present but pid namespace differs"
            if scope.cgroup_identity_digest != process.cgroup_identity_digest:
                return "registered process present but cgroup identity differs (post-registration cgroup move)"
            if (
                registration.expected_uid != process.uid
                or registration.expected_gid != process.gid
            ):
                return "registered process present but uid/gid differs"
            return "registered process present but a strong-identity field differs"
    return "no registered process in the captured ancestry (reparent, depth bound, or pid-namespace boundary)"


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
