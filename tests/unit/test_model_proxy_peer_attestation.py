from __future__ import annotations

import asyncio
import inspect
import socket
import threading
from typing import cast

import pytest

from boltrig.fleet.domain.model_proxy_scope import ModelProxyCellScope
from boltrig.fleet.infrastructure.linux_peer_identity import PeerCredentials
from boltrig.fleet.infrastructure.linux_peer_process_handle import AcceptedUnixPeer
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
    ModelProxyPeerAttestationError,
    ModelProxyPeerAttestationSaturated,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import ModelProxyProcessRegistry

from .model_proxy_peer_fakes import (
    BOOT_ID,
    DEFAULT_GID,
    DEFAULT_NAMESPACE,
    DEFAULT_UID,
    FakePeerProcessHandle,
    FakePeerProcessHandleReader,
    ScriptedProcReader,
    cell_scope,
    install_process,
    proc_stat,
)


def _socket_pair() -> tuple[socket.socket, socket.socket]:
    return socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)


def _fake_peer(peer_socket: socket.socket) -> AcceptedUnixPeer:
    """Mark a raw test socket for the injected handle-reader seam only."""

    return cast(AcceptedUnixPeer, peer_socket)


def _handle(
    helper_pid: int = 300, *, fail_on_checks: set[int] | None = None
) -> FakePeerProcessHandle:
    return FakePeerProcessHandle(
        PeerCredentials(helper_pid, DEFAULT_UID, DEFAULT_GID),
        fail_on_checks=fail_on_checks,
    )


def _attestor(
    registry: ModelProxyProcessRegistry,
    reader: ScriptedProcReader,
    *handles: FakePeerProcessHandle,
    max_ancestry: int = 1,
    timeout: float = 1.0,
    capacity: int = 1,
) -> LinuxModelProxyPeerAttestor:
    return LinuxModelProxyPeerAttestor(
        registry,
        proc_reader=reader,
        handle_reader=FakePeerProcessHandleReader(*(handles or (_handle(),))),
        max_ancestry=max_ancestry,
        timeout_seconds=timeout,
        max_concurrent_captures=capacity,
    )


async def _attest_once(
    registry: ModelProxyProcessRegistry,
    reader: ScriptedProcReader,
    peer_socket: socket.socket,
    *,
    handle: FakePeerProcessHandle | None = None,
    max_ancestry: int = 1,
) -> ModelProxyCellScope:
    attestor = _attestor(registry, reader, handle or _handle(), max_ancestry=max_ancestry)
    try:
        return await attestor.attest(_fake_peer(peer_socket))
    finally:
        await attestor.aclose()


async def _register(
    registry: ModelProxyProcessRegistry,
    *,
    pid: int = 200,
    start_ticks: int = 20_000,
    cell_id: str = "cell-1",
    assignment_id: str = "assignment-1",
    boot_id: str = BOOT_ID,
    namespace: int = DEFAULT_NAMESPACE,
) -> ModelProxyCellScope:
    scope = cell_scope(
        pid=pid,
        start_ticks=start_ticks,
        cell_id=cell_id,
        assignment_id=assignment_id,
        boot_id=boot_id,
        namespace=namespace,
    )
    await registry.register(scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)
    return scope


def _direct_reader() -> ScriptedProcReader:
    reader = ScriptedProcReader()
    install_process(reader, pid=300, parent_pid=200, start_ticks=30_000)
    install_process(reader, pid=200, parent_pid=50, start_ticks=20_000)
    return reader


@pytest.mark.unit
async def test_exact_direct_child_returns_scope_and_closes_pidfd_handle() -> None:
    registry = ModelProxyProcessRegistry()
    scope = await _register(registry)
    handle = _handle()
    left, right = _socket_pair()
    try:
        observed = await _attest_once(registry, _direct_reader(), left, handle=handle)
    finally:
        left.close()
        right.close()

    assert observed is scope
    assert handle.closed
    assert handle.close_count == 1
    assert handle.checks == 5


@pytest.mark.unit
async def test_bounded_ancestry_succeeds_but_sibling_and_excess_depth_fail() -> None:
    registry = ModelProxyProcessRegistry()
    scope = await _register(registry, pid=100, start_ticks=10_000)
    reader = ScriptedProcReader()
    install_process(reader, pid=300, parent_pid=200, start_ticks=30_000)
    install_process(reader, pid=200, parent_pid=100, start_ticks=20_000)
    install_process(reader, pid=100, parent_pid=50, start_ticks=10_000)
    left, right = _socket_pair()
    try:
        assert await _attest_once(registry, reader, left, max_ancestry=2) is scope
        with pytest.raises(ModelProxyPeerAttestationError):
            await _attest_once(registry, reader, left, max_ancestry=1)
    finally:
        left.close()
        right.close()

    sibling = ScriptedProcReader()
    install_process(sibling, pid=300, parent_pid=101, start_ticks=30_000)
    install_process(sibling, pid=101, parent_pid=50, start_ticks=10_001)
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError):
            await _attest_once(registry, sibling, left)
    finally:
        left.close()
        right.close()


@pytest.mark.unit
async def test_request_has_no_pid_or_scope_claim_surface() -> None:
    assert tuple(inspect.signature(LinuxModelProxyPeerAttestor.attest).parameters) == (
        "self",
        "peer_socket",
    )
    registry = ModelProxyProcessRegistry()
    await _register(registry)
    reader = ScriptedProcReader()
    install_process(reader, pid=999, parent_pid=200, start_ticks=99_900)
    install_process(reader, pid=200, parent_pid=50, start_ticks=20_000)
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError):
            await _attest_once(registry, reader, left, handle=_handle(300))
    finally:
        left.close()
        right.close()


@pytest.mark.unit
@pytest.mark.parametrize("changed_target", ["parent", "helper"])
async def test_pid_start_tick_reuse_and_proc_toctou_are_rejected(
    changed_target: str,
) -> None:
    registry = ModelProxyProcessRegistry()
    await _register(registry)
    reader = ScriptedProcReader()
    helper_stats = [proc_stat(300, parent_pid=200, start_ticks=30_000)] * 4
    parent_stats = [proc_stat(200, parent_pid=50, start_ticks=20_000)] * 4
    if changed_target == "parent":
        parent_stats[2:] = [proc_stat(200, parent_pid=50, start_ticks=20_001)] * 2
    else:
        helper_stats[2:] = [proc_stat(300, parent_pid=200, start_ticks=30_001)] * 2
    install_process(
        reader,
        pid=300,
        parent_pid=200,
        start_ticks=30_000,
        stat_sequence=helper_stats,
    )
    install_process(
        reader,
        pid=200,
        parent_pid=50,
        start_ticks=20_000,
        stat_sequence=parent_stats,
    )
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError):
            await _attest_once(registry, reader, left)
    finally:
        left.close()
        right.close()


@pytest.mark.unit
async def test_cycle_and_two_registered_ancestors_are_rejected() -> None:
    cycle_registry = ModelProxyProcessRegistry()
    await _register(cycle_registry)
    cycle = ScriptedProcReader()
    install_process(cycle, pid=300, parent_pid=200, start_ticks=30_000)
    install_process(cycle, pid=200, parent_pid=300, start_ticks=20_000)
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError):
            await _attest_once(cycle_registry, cycle, left, max_ancestry=2)
    finally:
        left.close()
        right.close()

    registry = ModelProxyProcessRegistry()
    await _register(registry, pid=200, start_ticks=20_000)
    await _register(
        registry,
        pid=100,
        start_ticks=10_000,
        cell_id="cell-2",
        assignment_id="assignment-2",
    )
    reader = ScriptedProcReader()
    install_process(reader, pid=300, parent_pid=200, start_ticks=30_000)
    install_process(reader, pid=200, parent_pid=100, start_ticks=20_000)
    install_process(reader, pid=100, parent_pid=50, start_ticks=10_000)
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError):
            await _attest_once(registry, reader, left, max_ancestry=2)
    finally:
        left.close()
        right.close()


@pytest.mark.unit
@pytest.mark.parametrize("mismatch", ["boot", "namespace", "cgroup", "uid", "gid"])
async def test_boot_namespace_cgroup_uid_and_gid_policy_are_exact(mismatch: str) -> None:
    registry = ModelProxyProcessRegistry()
    await _register(
        registry,
        boot_id=("118f4d4c-1111-7222-8333-123456789abc" if mismatch == "boot" else BOOT_ID),
        namespace=(DEFAULT_NAMESPACE + 1 if mismatch == "namespace" else DEFAULT_NAMESPACE),
    )
    reader = ScriptedProcReader()
    install_process(
        reader,
        pid=300,
        parent_pid=200,
        start_ticks=30_000,
        cgroup=("0::/boltrig/other\n" if mismatch == "cgroup" else "0::/boltrig/cell\n"),
        uid=(DEFAULT_UID + 1 if mismatch == "uid" else DEFAULT_UID),
        gid=(DEFAULT_GID + 1 if mismatch == "gid" else DEFAULT_GID),
    )
    install_process(reader, pid=200, parent_pid=50, start_ticks=20_000)
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError):
            await _attest_once(registry, reader, left)
    finally:
        left.close()
        right.close()


@pytest.mark.unit
@pytest.mark.parametrize("fail_on_check", [1, 2, 3, 4, 5])
async def test_dead_pidfd_fails_before_during_and_after_registry_confirm(
    fail_on_check: int,
) -> None:
    registry = ModelProxyProcessRegistry()
    await _register(registry)
    handle = _handle(fail_on_checks={fail_on_check})
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError):
            await _attest_once(registry, _direct_reader(), left, handle=handle)
    finally:
        left.close()
        right.close()
    assert handle.closed


@pytest.mark.unit
async def test_revoke_and_new_matching_ancestor_snapshot_races_fail_closed() -> None:
    registry = ModelProxyProcessRegistry()
    scope = await _register(registry)
    reader = _direct_reader()
    entered = threading.Event()
    release = threading.Event()

    def block_middle_boot(kind: str, path: str, call: int) -> None:
        if kind == "file" and path == "sys/kernel/random/boot_id" and call == 1:
            entered.set()
            release.wait(timeout=2)

    reader.on_read = block_middle_boot
    handle = _handle()
    attestor = _attestor(registry, reader, handle)
    left, right = _socket_pair()
    try:
        task = asyncio.create_task(attestor.attest(_fake_peer(left)))
        assert await asyncio.to_thread(entered.wait, 2)
        assert await registry.revoke(scope)
        release.set()
        with pytest.raises(ModelProxyPeerAttestationError):
            await task
    finally:
        release.set()
        await attestor.aclose()
        left.close()
        right.close()

    second_registry = ModelProxyProcessRegistry()
    await _register(second_registry)
    second_reader = ScriptedProcReader()
    install_process(second_reader, pid=300, parent_pid=200, start_ticks=30_000)
    install_process(second_reader, pid=200, parent_pid=100, start_ticks=20_000)
    install_process(second_reader, pid=100, parent_pid=50, start_ticks=10_000)
    entered.clear()
    release.clear()
    second_reader.on_read = block_middle_boot
    second_attestor = _attestor(second_registry, second_reader, _handle(), max_ancestry=2)
    left, right = _socket_pair()
    try:
        task = asyncio.create_task(second_attestor.attest(_fake_peer(left)))
        assert await asyncio.to_thread(entered.wait, 2)
        await _register(
            second_registry,
            pid=100,
            start_ticks=10_000,
            cell_id="cell-2",
            assignment_id="assignment-2",
        )
        release.set()
        with pytest.raises(ModelProxyPeerAttestationError):
            await task
    finally:
        release.set()
        await second_attestor.aclose()
        left.close()
        right.close()


@pytest.mark.unit
async def test_timeout_keeps_pidfd_and_admission_until_worker_actually_drains() -> None:
    registry = ModelProxyProcessRegistry()
    await _register(registry)
    reader = _direct_reader()
    entered = threading.Event()
    release = threading.Event()

    def block_first_stat(kind: str, path: str, _call: int) -> None:
        if kind == "file" and path == "300/stat":
            entered.set()
            release.wait(timeout=2)

    reader.on_read = block_first_stat
    first, second = _handle(), _handle()
    handle_reader = FakePeerProcessHandleReader(first, second)
    attestor = LinuxModelProxyPeerAttestor(
        registry,
        proc_reader=reader,
        handle_reader=handle_reader,
        max_ancestry=1,
        # The first attest is blocked up to 2s on release.wait, so any deadline
        # under 2s makes it time out as intended; keep enough headroom that the
        # final unblocked attest (line below) never trips the deadline on a
        # loaded box. A genuine hang would still exceed this and fail.
        timeout_seconds=0.5,
        max_concurrent_captures=1,
    )
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError):
            await attestor.attest(_fake_peer(left))
        assert entered.is_set()
        assert not first.closed
        with pytest.raises(ModelProxyPeerAttestationSaturated):
            await attestor.attest(_fake_peer(left))
        assert handle_reader.acquire_count == 1
        release.set()
        for _ in range(100):
            if first.closed:
                break
            await asyncio.sleep(0.005)
        assert first.closed
        reader.on_read = None
        assert await attestor.attest(_fake_peer(left)) == cell_scope()
        assert second.closed
    finally:
        release.set()
        await attestor.aclose()
        left.close()
        right.close()


@pytest.mark.unit
async def test_cancellation_and_shutdown_drain_before_closing_pidfd_or_executor() -> None:
    registry = ModelProxyProcessRegistry()
    await _register(registry)
    reader = _direct_reader()
    entered = threading.Event()
    release = threading.Event()

    def block_first_stat(kind: str, path: str, _call: int) -> None:
        if kind == "file" and path == "300/stat":
            entered.set()
            release.wait(timeout=2)

    reader.on_read = block_first_stat
    handle = _handle()
    attestor = _attestor(registry, reader, handle, timeout=1.0)
    left, right = _socket_pair()
    try:
        task = asyncio.create_task(attestor.attest(_fake_peer(left)))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not handle.closed
        close_task = asyncio.create_task(attestor.aclose())
        await asyncio.sleep(0)
        assert not close_task.done()
        release.set()
        await close_task
        assert handle.closed
        assert handle.close_count == 1
        with pytest.raises(ModelProxyPeerAttestationError):
            await attestor.attest(_fake_peer(left))
    finally:
        release.set()
        await attestor.aclose()
        left.close()
        right.close()


@pytest.mark.unit
async def test_raw_proc_failures_are_generic_and_redacted() -> None:
    registry = ModelProxyProcessRegistry()
    await _register(registry)
    reader = _direct_reader()
    reader.files["300/cgroup"] = ["0::/secret-BEARER-should-never-leak\x00\n"]
    left, right = _socket_pair()
    try:
        with pytest.raises(ModelProxyPeerAttestationError) as error:
            await _attest_once(registry, reader, left)
    finally:
        left.close()
        right.close()
    assert str(error.value) == "model-proxy peer attestation failed"
    assert "secret-BEARER" not in repr(error.value)
    assert error.value.__context__ is None
    assert error.value.__cause__ is None
    traceback = error.value.__traceback__
    frame_names: list[str] = []
    while traceback is not None:
        frame_names.append(traceback.tb_frame.f_code.co_name)
        traceback = traceback.tb_next
    assert "_attest_reserved" not in frame_names


@pytest.mark.unit
def test_attestation_configuration_has_hard_bounds() -> None:
    registry = ModelProxyProcessRegistry()
    reader = ScriptedProcReader()
    handle_reader = FakePeerProcessHandleReader(_handle())
    for options in (
        {"max_ancestry": 17},
        {"timeout_seconds": 5.01},
        {"max_concurrent_captures": 17},
    ):
        with pytest.raises(ValueError):
            LinuxModelProxyPeerAttestor(
                registry,
                proc_reader=reader,
                handle_reader=handle_reader,
                **options,
            )
