"""Supervisor-ownable AF_UNIX ingress that attests each connecting peer.

Beat 1 of the SO_PEERCRED production-issuance path ([2026] VJS-CC-VJS 1 and 3).
This owns a real ``AF_UNIX`` / ``SOCK_STREAM`` listener bound on a writable cell
path, and for an accepted connection performs end-to-end SO_PEERCRED /
SO_PEERPIDFD attestation through :class:`LinuxModelProxyPeerAttestor`, yielding
an attested :class:`ModelProxyCellScope` bound to exactly one live registered
cell.

Caller-supplied identity is never provenance ([2026] VJS-CC-VJS 1): the only
trusted endpoint is the one minted by ``accept_model_proxy_unix_peer``, so the
blocking accept runs through that seam and never a bypass that fabricates an
``AcceptedUnixPeer``. This module never mints a bearer, grants authority, or
reads request data; ``production_ready`` stays False.

Beat 1 exposes only single-shot ``accept_once`` (attest, then close the peer -
no bearer, nothing at rest). The production accept loop and the Option-B
bearer-over-socket write ([2026] VJS-CC-VJS 3, the raw bearer to the attested
peer, no file) land in the next beat, at the point where ``accept_once`` returns
the attested scope.
"""

from __future__ import annotations

import asyncio
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from boltrig.fleet.domain.model_proxy_scope import ModelProxyCellScope

from .linux_peer_process_handle import (
    ALLOWED_MODEL_PROXY_SOCKET_TYPE,
    AcceptedUnixPeer,
    accept_model_proxy_unix_peer,
)
from .model_proxy_peer_attestation import LinuxModelProxyPeerAttestor

_SOCKET_BACKLOG = 16
# Owner-only: in the single-uid interim the supervisor and the cell share a uid,
# so 0600 lets the helper connect. Distinct-uid cells are served by the socket
# (never by widened file perms) - that widening is exactly what VJS-CC-VJS 2/3
# forbid; the cross-uid socket posture is a later multiplayer beat.
_SOCKET_MODE = 0o600
MAX_UNIX_SOCKET_PATH_BYTES = 108


class PeerAttestationListenerError(RuntimeError):
    """The peer-attestation listener could not be bound, accepted, or served."""


class PeerAttestationUnixListener:
    """Own an AF_UNIX listener and attest an accepted peer.

    The supervisor owns one of these. :meth:`bind` creates the socket on a
    writable path; :meth:`accept_once` attests exactly one connection; :meth:`aclose`
    closes the socket and unlinks its path. The attestor (and its process
    registry) are injected, so the listener grants no authority of its own.
    """

    __slots__ = ("_accepts", "_attestor", "_closed", "_closing", "_listener", "_path")

    def __init__(
        self,
        listener: socket.socket,
        path: Path,
        attestor: LinuxModelProxyPeerAttestor,
    ) -> None:
        self._listener = listener
        self._path = path
        self._attestor = attestor
        self._accepts = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="boltrig-peer-accept"
        )
        self._closing = False
        self._closed = False

    @classmethod
    def bind(
        cls, path: Path, attestor: LinuxModelProxyPeerAttestor
    ) -> PeerAttestationUnixListener:
        if type(attestor) is not LinuxModelProxyPeerAttestor:
            raise TypeError("attestor must be an exact LinuxModelProxyPeerAttestor")
        target = _writable_socket_path(path)
        listener = socket.socket(socket.AF_UNIX, ALLOWED_MODEL_PROXY_SOCKET_TYPE)
        try:
            listener.bind(os.fspath(target))
            os.chmod(target, _SOCKET_MODE)
            listener.listen(_SOCKET_BACKLOG)
            listener.setblocking(True)
        except OSError as exc:
            listener.close()
            _unlink_quietly(target)
            raise PeerAttestationListenerError("unix peer listener bind failed") from exc
        return cls(listener, target, attestor)

    async def accept_once(self) -> ModelProxyCellScope:
        """Accept one connection and return its attested cell scope.

        Beat 1 closes the accepted peer once attested; the next beat keeps it open
        here to write the scoped bearer to the attested peer before closing.
        """

        peer = await self._accept()
        try:
            return await self._attestor.attest(peer)
        finally:
            peer.close()

    async def _accept(self) -> AcceptedUnixPeer:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self._accepts, accept_model_proxy_unix_peer, self._listener
            )
        except OSError as exc:
            raise PeerAttestationListenerError("unix peer accept failed") from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closing = True
        # Unblock any accept thread parked in the kernel accept() so the executor
        # can shut down instead of hanging on a peer that will never arrive.
        self._wake_accept()
        self._listener.close()
        self._accepts.shutdown(wait=True)
        _unlink_quietly(self._path)
        self._closed = True

    def _wake_accept(self) -> None:
        try:
            waker = socket.socket(socket.AF_UNIX, ALLOWED_MODEL_PROXY_SOCKET_TYPE)
            try:
                waker.connect(os.fspath(self._path))
            finally:
                waker.close()
        except OSError:
            pass


def _writable_socket_path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise PeerAttestationListenerError("socket path must be an absolute Path")
    encoded = os.fsencode(os.fspath(path))
    if not encoded or len(encoded) > MAX_UNIX_SOCKET_PATH_BYTES:
        raise PeerAttestationListenerError("socket path exceeds the AF_UNIX name bound")
    if not path.parent.is_dir():
        raise PeerAttestationListenerError("socket parent directory is unavailable")
    return path


def _unlink_quietly(path: Path) -> None:
    try:
        os.unlink(os.fspath(path))
    except OSError:
        pass


__all__ = [
    "MAX_UNIX_SOCKET_PATH_BYTES",
    "PeerAttestationListenerError",
    "PeerAttestationUnixListener",
]
