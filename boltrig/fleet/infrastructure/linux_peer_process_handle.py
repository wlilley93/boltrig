"""Owned Linux pidfd handle acquired only from an accepted Unix peer."""

from __future__ import annotations

import os
import select
import socket
import struct
from typing import Protocol, cast

from .linux_peer_identity import LinuxPeerIdentityError, PeerCredentials

# Python may not expose this newer Linux socket option even when the running
# kernel supports it.  Linux UAPI assigns SO_PEERPIDFD the stable value 77.
SO_PEERPIDFD_OPTION = getattr(socket, "SO_PEERPIDFD", 77)
ALLOWED_MODEL_PROXY_SOCKET_TYPE = socket.SOCK_STREAM
MAX_UNIX_SOCKET_NAME_BYTES = 108
_ACCEPT_PROVENANCE = object()


class AcceptedUnixPeer:
    """Opaque endpoint minted only by this module's validated ``accept()``."""

    __slots__ = ("_closed", "_listener_name", "_socket")

    def __init__(
        self,
        peer_socket: socket.socket,
        listener_name: str | bytes,
        provenance: object,
    ) -> None:
        if provenance is not _ACCEPT_PROVENANCE:
            raise LinuxPeerIdentityError("accepted peer provenance is unavailable")
        self._socket = peer_socket
        self._listener_name = listener_name
        self._closed = False

    def _borrow(self, provenance: object) -> tuple[socket.socket, str | bytes]:
        if provenance is not _ACCEPT_PROVENANCE or self._closed:
            raise LinuxPeerIdentityError("accepted peer is unavailable")
        return self._socket, self._listener_name

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._socket.close()

    def send_bearer(self, bearer: bytes) -> None:
        """Deliver bytes to exactly this attested peer, then let the caller close.

        Writes to this peer's own connected socket only; unlike ``_borrow`` it never
        surrenders the socket, so the bearer can reach only the one attested
        endpoint ([2026] VJS-CC-VJS 3). Provenance and close semantics are unchanged.
        """
        if type(bearer) is not bytes or not bearer:
            raise LinuxPeerIdentityError("bearer must be non-empty bytes")
        if self._closed:
            raise LinuxPeerIdentityError("accepted peer is unavailable")
        try:
            self._socket.sendall(bearer)
        except OSError as exc:
            raise LinuxPeerIdentityError("accepted peer delivery failed") from exc

    def __repr__(self) -> str:
        state = "closed" if self._closed else "accepted"
        return f"AcceptedUnixPeer({state}, <redacted>)"


class PeerProcessHandle(Protocol):
    """Owned, pollable lifetime proof for the kernel-observed socket peer."""

    @property
    def credentials(self) -> PeerCredentials: ...

    def assert_alive(self) -> None: ...

    def close(self) -> None: ...


class PeerProcessHandleReader(Protocol):
    """Acquire an owned peer process handle from an accepted socket."""

    def acquire(self, peer: AcceptedUnixPeer) -> PeerProcessHandle: ...


class LinuxPeerProcessHandle:
    """Owned ``SO_PEERPIDFD`` result; never opened from a caller PID."""

    __slots__ = ("_closed", "_credentials", "_pidfd")

    def __init__(self, pidfd: int, credentials: PeerCredentials) -> None:
        if type(pidfd) is not int or pidfd < 0:
            raise LinuxPeerIdentityError("invalid peer process handle")
        if type(credentials) is not PeerCredentials:
            raise TypeError("credentials must be exact PeerCredentials")
        self._pidfd = pidfd
        self._credentials = credentials
        self._closed = False

    @property
    def credentials(self) -> PeerCredentials:
        return self._credentials

    def assert_alive(self) -> None:
        if self._closed:
            raise LinuxPeerIdentityError("peer process handle is closed")
        poller = select.poll()
        mask = select.POLLIN | select.POLLERR | select.POLLHUP | select.POLLNVAL
        try:
            poller.register(self._pidfd, mask)
            events = poller.poll(0)
        except (OSError, ValueError) as exc:
            raise LinuxPeerIdentityError("peer process handle unavailable") from exc
        if events:
            raise LinuxPeerIdentityError("peer process is not live")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self._pidfd)
        except OSError:
            pass

    def __repr__(self) -> str:
        state = "closed" if self._closed else "owned"
        return f"LinuxPeerProcessHandle({state}, <redacted>)"


class LinuxSocketPeerProcessHandleReader:
    """Validate an accepted AF_UNIX stream and acquire its kernel pidfd."""

    def acquire(self, peer: AcceptedUnixPeer) -> PeerProcessHandle:
        if type(peer) is not AcceptedUnixPeer:
            raise LinuxPeerIdentityError("peer must have trusted accept provenance")
        peer_socket, listener_name = peer._borrow(_ACCEPT_PROVENANCE)
        _validate_accepted_socket(peer_socket, listener_name)
        pidfd = _acquire_peer_pidfd(peer_socket)
        try:
            credentials = _read_peer_credentials(peer_socket)
            if credentials.pid == os.getpid():
                raise LinuxPeerIdentityError("self peer is not permitted")
            os.set_inheritable(pidfd, False)
            handle = LinuxPeerProcessHandle(pidfd, credentials)
            handle.assert_alive()
            return handle
        except Exception:
            try:
                os.close(pidfd)
            except OSError:
                pass
            raise


def accept_model_proxy_unix_peer(listener: socket.socket) -> AcceptedUnixPeer:
    """Perform the kernel accept that mints trusted endpoint provenance."""

    listener_name = _validate_listener(listener)
    try:
        peer_socket, _address = listener.accept()
    except OSError as exc:
        raise LinuxPeerIdentityError("Unix peer accept failed") from exc
    try:
        _validate_accepted_socket(peer_socket, listener_name)
        return AcceptedUnixPeer(peer_socket, listener_name, _ACCEPT_PROVENANCE)
    except Exception:
        peer_socket.close()
        raise


def _validate_listener(listener: socket.socket) -> str | bytes:
    if type(listener) is not socket.socket or listener.family != socket.AF_UNIX:
        raise LinuxPeerIdentityError("listener must be an exact Unix socket")
    try:
        socket_type = listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        accepting = listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
        local_name = listener.getsockname()
    except OSError as exc:
        raise LinuxPeerIdentityError("Unix listener is unavailable") from exc
    if socket_type != ALLOWED_MODEL_PROXY_SOCKET_TYPE or accepting != 1:
        raise LinuxPeerIdentityError("Unix listener policy mismatch")
    if not _valid_unix_name(local_name, require_nonempty=True):
        raise LinuxPeerIdentityError("Unix listener has no pinned local address")
    return cast(str | bytes, local_name)


def _validate_accepted_socket(
    peer_socket: socket.socket, listener_name: str | bytes
) -> None:
    if type(peer_socket) is not socket.socket:
        raise LinuxPeerIdentityError("peer must be a socket")
    if peer_socket.family != socket.AF_UNIX or peer_socket.fileno() < 0:
        raise LinuxPeerIdentityError("peer must be an accepted Unix socket")
    try:
        socket_type = peer_socket.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        accepting = peer_socket.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
        local_name = peer_socket.getsockname()
        peer_name = peer_socket.getpeername()
    except OSError as exc:
        raise LinuxPeerIdentityError("peer must be a connected Unix socket") from exc
    if socket_type != ALLOWED_MODEL_PROXY_SOCKET_TYPE or accepting != 0:
        raise LinuxPeerIdentityError("peer socket policy mismatch")
    if not _valid_unix_name(local_name, require_nonempty=True):
        raise LinuxPeerIdentityError("accepted socket has no pinned local address")
    if local_name != listener_name:
        raise LinuxPeerIdentityError("accepted socket listener identity changed")
    if not _valid_unix_name(peer_name, require_nonempty=False):
        raise LinuxPeerIdentityError("accepted socket peer address is invalid")
    if peer_name and peer_name == local_name:
        raise LinuxPeerIdentityError("self-connected Unix socket is not permitted")


def _valid_unix_name(value: object, *, require_nonempty: bool) -> bool:
    if type(value) not in {str, bytes}:
        return False
    try:
        encoded = os.fsencode(cast(str | bytes, value))
    except (TypeError, UnicodeError):
        return False
    return (not require_nonempty or bool(encoded)) and len(encoded) <= MAX_UNIX_SOCKET_NAME_BYTES


def _acquire_peer_pidfd(peer_socket: socket.socket) -> int:
    if type(SO_PEERPIDFD_OPTION) is not int:
        raise LinuxPeerIdentityError("SO_PEERPIDFD is unavailable")
    try:
        pidfd = peer_socket.getsockopt(socket.SOL_SOCKET, SO_PEERPIDFD_OPTION)
    except OSError as exc:
        raise LinuxPeerIdentityError("kernel peer process handle unavailable") from exc
    if type(pidfd) is not int or pidfd < 0 or pidfd == peer_socket.fileno():
        if pidfd == peer_socket.fileno():
            raise LinuxPeerIdentityError("invalid kernel peer process handle")
        if type(pidfd) is int and pidfd >= 0:
            try:
                os.close(pidfd)
            except OSError:
                pass
        raise LinuxPeerIdentityError("invalid kernel peer process handle")
    return pidfd


def _read_peer_credentials(peer_socket: socket.socket) -> PeerCredentials:
    option = getattr(socket, "SO_PEERCRED", None)
    if type(option) is not int:
        raise LinuxPeerIdentityError("SO_PEERCRED is unavailable")
    size = struct.calcsize("iII")
    try:
        raw = peer_socket.getsockopt(socket.SOL_SOCKET, option, size)
        pid, uid, gid = struct.unpack("iII", raw)
    except (OSError, struct.error) as exc:
        raise LinuxPeerIdentityError("kernel peer credentials unavailable") from exc
    return PeerCredentials(pid=pid, uid=uid, gid=gid)


__all__ = [
    "AcceptedUnixPeer",
    "ALLOWED_MODEL_PROXY_SOCKET_TYPE",
    "LinuxPeerProcessHandle",
    "LinuxSocketPeerProcessHandleReader",
    "PeerProcessHandle",
    "PeerProcessHandleReader",
    "SO_PEERPIDFD_OPTION",
    "accept_model_proxy_unix_peer",
]
