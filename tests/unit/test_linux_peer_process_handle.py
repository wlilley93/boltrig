from __future__ import annotations

import os
import socket
import sys
import tempfile
import time
from typing import cast

import pytest

from boltrig.fleet.infrastructure.linux_peer_identity import LinuxPeerIdentityError
from boltrig.fleet.infrastructure.linux_peer_process_handle import (

    AcceptedUnixPeer,
    LinuxSocketPeerProcessHandleReader,
    SO_PEERPIDFD_OPTION,
    accept_model_proxy_unix_peer,
)

# Every leg here needs a Linux kernel facility macOS does not have: yama
# ptrace_scope, abstract AF_UNIX names, SO_PEERCRED, or bubblewrap. Marked so a
# non-Linux box reports them as unverified instead of failing; on Linux the
# marker is inert and they always run.
pytestmark = pytest.mark.linux_only


def _filesystem_listener() -> tuple[socket.socket, str, str]:
    directory = tempfile.mkdtemp(prefix="bt-peer-", dir="/tmp")
    path = os.path.join(directory, "socket")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(1)
    return listener, path, directory


def _cleanup_listener(listener: socket.socket, path: str, directory: str) -> None:
    listener.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    os.rmdir(directory)


@pytest.mark.unit
def test_peer_pidfd_option_has_linux_uapi_fallback_without_pidfd_open() -> None:
    assert SO_PEERPIDFD_OPTION == getattr(socket, "SO_PEERPIDFD", 77)


@pytest.mark.unit
def test_raw_listener_unconnected_and_socketpair_endpoints_lack_accept_provenance() -> None:
    reader = LinuxSocketPeerProcessHandleReader()
    listener, path, directory = _filesystem_listener()
    unconnected = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    datagram_left, datagram_right = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        for candidate in (listener, unconnected, left, datagram_left):
            with pytest.raises(LinuxPeerIdentityError):
                reader.acquire(cast(AcceptedUnixPeer, candidate))
        with pytest.raises(LinuxPeerIdentityError):
            AcceptedUnixPeer(listener, path, object())
    finally:
        unconnected.close()
        left.close()
        right.close()
        datagram_left.close()
        datagram_right.close()
        _cleanup_listener(listener, path, directory)


@pytest.mark.unit
def test_accept_boundary_rejects_every_non_listener_unix_endpoint() -> None:
    unconnected = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    datagram_left, datagram_right = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        for candidate in (unconnected, left, datagram_left):
            with pytest.raises(LinuxPeerIdentityError):
                accept_model_proxy_unix_peer(candidate)
    finally:
        unconnected.close()
        left.close()
        right.close()
        datagram_left.close()
        datagram_right.close()


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "linux", reason="Linux SO_PEERPIDFD integration")
def test_same_process_accepted_peer_is_rejected() -> None:
    listener, path, directory = _filesystem_listener()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    accepted: AcceptedUnixPeer | None = None
    try:
        client.connect(path)
        accepted = accept_model_proxy_unix_peer(listener)
        with pytest.raises(LinuxPeerIdentityError):
            LinuxSocketPeerProcessHandleReader().acquire(accepted)
    finally:
        if accepted is not None:
            accepted.close()
        client.close()
        _cleanup_listener(listener, path, directory)


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "linux", reason="Linux SO_PEERPIDFD integration")
def test_accepted_child_peer_pidfd_detects_exit_and_closes_idempotently() -> None:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    name = f"\0boltrig-peer-{os.getpid()}-{id(listener)}"
    listener.bind(name)
    listener.listen(1)
    release_read, release_write = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:  # pragma: no cover - executed in the integration child
        try:
            os.close(release_write)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(name)
            os.read(release_read, 1)
            client.close()
        finally:
            os._exit(0)

    os.close(release_read)
    accepted: AcceptedUnixPeer | None = None
    handle = None
    try:
        listener.settimeout(2)
        accepted = accept_model_proxy_unix_peer(listener)
        handle = LinuxSocketPeerProcessHandleReader().acquire(accepted)
        assert handle.credentials.pid == child_pid
        handle.assert_alive()
        os.write(release_write, b"x")
        os.close(release_write)
        release_write = -1
        waited, _status = os.waitpid(child_pid, 0)
        assert waited == child_pid
        child_pid = -1
        for _ in range(100):
            try:
                handle.assert_alive()
            except LinuxPeerIdentityError:
                break
            time.sleep(0.005)
        else:
            pytest.fail("peer pidfd did not report child exit")
        handle.close()
        handle.close()
        with pytest.raises(LinuxPeerIdentityError):
            handle.assert_alive()
        assert "redacted" in repr(handle)
    finally:
        if handle is not None:
            handle.close()
        if accepted is not None:
            accepted.close()
        listener.close()
        if release_write >= 0:
            os.close(release_write)
        if child_pid > 0:
            try:
                os.kill(child_pid, 9)
            except ProcessLookupError:
                pass
            os.waitpid(child_pid, 0)


@pytest.mark.unit
def test_send_bearer_reaches_the_attested_peer_and_guards_its_inputs() -> None:
    listener, path, directory = _filesystem_listener()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    accepted: AcceptedUnixPeer | None = None
    try:
        client.connect(path)
        accepted = accept_model_proxy_unix_peer(listener)
        # Empty and non-bytes bearers are refused before any write.
        with pytest.raises(LinuxPeerIdentityError):
            accepted.send_bearer(b"")
        with pytest.raises(LinuxPeerIdentityError):
            accepted.send_bearer(cast(bytes, "not-bytes"))
        # A well-formed bearer reaches exactly this peer's connected socket.
        accepted.send_bearer(b"bearer-xyz")
        assert client.recv(64) == b"bearer-xyz"
        # A closed peer refuses delivery.
        accepted.close()
        with pytest.raises(LinuxPeerIdentityError):
            accepted.send_bearer(b"after-close")
    finally:
        if accepted is not None:
            accepted.close()
        client.close()
        _cleanup_listener(listener, path, directory)
