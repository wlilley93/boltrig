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

``accept_once`` is the single-shot seam (attest, then close - no bearer). The
production accept loop is ``serve``: after SO_PEERCRED attestation it writes the
raw bearer to the SAME attested peer socket and closes it - Option-B delivery
([2026] VJS-CC-VJS 3), nothing at rest. The bearer is minted by an injected
issuer keyed on the attested scope (never the real broker in tests). Wiring
``serve`` into the live provider, and materializing the socket-client helper, is
the later provider-swap beat.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from boltrig.fleet.domain.model_proxy_scope import ModelProxyCellScope

from .linux_peer_process_handle import (
    ALLOWED_MODEL_PROXY_SOCKET_TYPE,
    AcceptedUnixPeer,
    accept_model_proxy_unix_peer,
)
from .model_proxy_peer_attestation import LinuxModelProxyPeerAttestor

logger = logging.getLogger(__name__)

# Injected by the composition (never the real broker in tests): given the attested
# cell scope, return the raw bearer bytes to deliver to that exact peer.
BearerIssuer = Callable[[ModelProxyCellScope], Awaitable[bytes]]

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

    __slots__ = (
        "_accepts",
        "_attestor",
        "_closed",
        "_closing",
        "_listener",
        "_path",
    )

    def __init__(
        self,
        listener: socket.socket,
        path: Path | str,
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
        cls, path: Path | str, attestor: LinuxModelProxyPeerAttestor
    ) -> PeerAttestationUnixListener:
        """Bind either an abstract ``@name`` or a filesystem path.

        The production form is abstract: it has no filesystem presence, so a cell
        sharing the stack-root tmpfs cannot pre-create or replace it, and a second
        ``bind`` of a name already taken fails ``EADDRINUSE`` rather than silently
        winning a race. The filesystem form is retained for the live listener
        tests, which bind this class directly on a temp path.
        """

        if type(attestor) is not LinuxModelProxyPeerAttestor:
            raise TypeError("attestor must be an exact LinuxModelProxyPeerAttestor")
        if isinstance(path, str):
            return cls._bind_abstract(_abstract_socket_name(path), attestor)
        return cls._bind_path(_writable_socket_path(path), attestor)

    @classmethod
    def _bind_abstract(
        cls, name: str, attestor: LinuxModelProxyPeerAttestor
    ) -> PeerAttestationUnixListener:
        """Bind an abstract name: no inode, so no mode to set and nothing to unlink."""

        listener = socket.socket(socket.AF_UNIX, ALLOWED_MODEL_PROXY_SOCKET_TYPE)
        try:
            listener.bind(name)
            listener.listen(_SOCKET_BACKLOG)
            listener.setblocking(True)
        except OSError as exc:
            listener.close()
            raise PeerAttestationListenerError("unix peer listener bind failed") from exc
        return cls(listener, name, attestor)

    @classmethod
    def _bind_path(
        cls, target: Path, attestor: LinuxModelProxyPeerAttestor
    ) -> PeerAttestationUnixListener:
        """Bind a filesystem path. Retained for the live listener tests only."""

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

    async def serve(self, bearer_issuer: BearerIssuer) -> None:
        """Accept, attest, and deliver a scoped bearer to each peer, forever.

        Option-B delivery ([2026] VJS-CC-VJS 3): after SO_PEERCRED attestation the
        raw bearer is written to the SAME attested socket, then the peer is closed -
        nothing at rest (E1). A peer that fails attestation or delivery is dropped
        without disturbing the loop, and nothing is written on failure (fail-closed).
        Stop it by cancelling the serve task, then calling :meth:`aclose`.
        """

        while not self._closing:
            try:
                peer = await self._accept()
            except PeerAttestationListenerError:
                if self._closing:
                    return
                continue
            await self._attest_and_deliver(peer, bearer_issuer)

    async def _attest_and_deliver(
        self, peer: AcceptedUnixPeer, bearer_issuer: BearerIssuer
    ) -> None:
        try:
            scope = await self._attestor.attest(peer)
            bearer = await bearer_issuer(scope)
            if type(bearer) is not bytes or not bearer:
                raise PeerAttestationListenerError("bearer issuer returned no bearer")
            await self._deliver(peer, bearer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Fail-closed: drop this peer, write nothing, keep serving. Logging the
            # reason is safe: attestation/issuer failures carry static messages, never
            # peer-supplied data, so this cannot leak attacker-controlled content.
            logger.warning("model proxy peer dropped: %s: %s", type(exc).__name__, exc)
        finally:
            peer.close()

    async def _deliver(self, peer: AcceptedUnixPeer, bearer: bytes) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._accepts, peer.send_bearer, bearer)

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
        if isinstance(self._path, Path):
            # An abstract name has no directory entry; it is released with the socket.
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


def _abstract_socket_name(value: str) -> str:
    """Translate the ``@name`` argv convention into a real abstract name.

    A Linux abstract socket name begins with a NUL byte, which can never travel
    through ``execve`` argv, so the name reaches the cell's auth helper as ``@name``
    (the convention ``ss``, ``socat`` and systemd all use) and is translated here
    and in the helper. Length is checked against the same ``sun_path`` bound as a
    filesystem path, since the kernel applies it to both.
    """

    if not value.startswith("@") or len(value) < 2:
        raise PeerAttestationListenerError("abstract socket name must start with @")
    name = "\0" + value[1:]
    if len(os.fsencode(name)) > MAX_UNIX_SOCKET_PATH_BYTES:
        raise PeerAttestationListenerError("socket name exceeds the AF_UNIX name bound")
    return name


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
    "BearerIssuer",
    "PeerAttestationListenerError",
    "PeerAttestationUnixListener",
]
