"""Bounded pidfd-backed attestation for an accepted model-auth Unix peer.

PID, cell, assignment, and scope claims are never accepted from request data.
Production remains disabled until the supervisor owns process registration and
enforces the fixed helper executable/capability configuration.  This module
does not create a listener, authenticate a bearer, or grant authority.

Success is one identity observation linearized by an unchanged-version final
registry check.  Future authorization must recheck both cell liveness and the
supervisor-owned App Server pidfd atomically with its own decision.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import math
import threading
from typing import cast

from boltrig.fleet.domain.model_proxy_scope import ModelProxyCellScope

from .linux_peer_identity import LinuxProcReader, ProcReader
from .linux_peer_process_handle import (
    AcceptedUnixPeer,
    LinuxSocketPeerProcessHandleReader,
    PeerProcessHandle,
    PeerProcessHandleReader,
)
from .model_proxy_peer_ancestry import attest_peer_ancestry
from .model_proxy_peer_registry import ModelProxyProcessRegistration, ModelProxyProcessRegistry

DEFAULT_MAX_MODEL_PROXY_ANCESTRY = 4
HARD_MAX_MODEL_PROXY_ANCESTRY = 16
DEFAULT_MODEL_PROXY_ATTESTATION_TIMEOUT_SECONDS = 1.0
HARD_MAX_MODEL_PROXY_ATTESTATION_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_CONCURRENT_PEER_CAPTURES = 4
HARD_MAX_CONCURRENT_PEER_CAPTURES = 16


class ModelProxyPeerAttestationError(RuntimeError):
    """A peer could not be bound to exactly one live registered cell."""


class ModelProxyPeerAttestationSaturated(ModelProxyPeerAttestationError):
    """The bounded capture executor has no immediately available admission."""


class LinuxModelProxyPeerAttestor:
    """Own a bounded executor and attest exact helper ancestry."""

    def __init__(
        self,
        registry: ModelProxyProcessRegistry,
        *,
        proc_reader: ProcReader | None = None,
        handle_reader: PeerProcessHandleReader | None = None,
        max_ancestry: int = DEFAULT_MAX_MODEL_PROXY_ANCESTRY,
        timeout_seconds: float = DEFAULT_MODEL_PROXY_ATTESTATION_TIMEOUT_SECONDS,
        max_concurrent_captures: int = DEFAULT_MAX_CONCURRENT_PEER_CAPTURES,
    ) -> None:
        if type(registry) is not ModelProxyProcessRegistry:
            raise TypeError("registry must be an exact ModelProxyProcessRegistry")
        self._registry = registry
        self._proc = proc_reader if proc_reader is not None else LinuxProcReader()
        self._handles = (
            handle_reader if handle_reader is not None else LinuxSocketPeerProcessHandleReader()
        )
        self._max_ancestry = _ancestry_bound(max_ancestry)
        self._timeout = _timeout_bound(timeout_seconds)
        capacity = _capacity_bound(max_concurrent_captures)
        self._executor = ThreadPoolExecutor(
            max_workers=capacity, thread_name_prefix="boltrig-peer-attest"
        )
        self._admission = threading.BoundedSemaphore(capacity)
        self._inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._drainers: set[asyncio.Task[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    async def attest(self, peer_socket: AcceptedUnixPeer) -> ModelProxyCellScope:
        """Return a scope live at the unchanged-snapshot check."""

        loop = self._reserve()
        failed = False
        try:
            return await self._attest_reserved(loop, peer_socket)
        except asyncio.CancelledError:
            raise
        except Exception:
            failed = True
        # Raise outside the handler so no worker exception, traceback, proc
        # value, or future remains attached as context to the public failure.
        if failed:
            raise _generic_failure()
        raise RuntimeError("unreachable peer attestation state")

    async def _attest_reserved(
        self, loop: asyncio.AbstractEventLoop, peer: AcceptedUnixPeer
    ) -> ModelProxyCellScope:
        handle: PeerProcessHandle | None = None
        delegated = False
        try:
            handle = self._handles.acquire(peer)
            handle.assert_alive()
            snapshot = await self._registry.snapshot_live()
            if not snapshot.registrations:
                raise _generic_failure()
            future = cast(
                asyncio.Future[ModelProxyProcessRegistration],
                loop.run_in_executor(
                    self._executor,
                    attest_peer_ancestry,
                    self._proc,
                    handle,
                    snapshot.registrations,
                    self._max_ancestry,
                ),
            )
            try:
                registration = await asyncio.wait_for(asyncio.shield(future), timeout=self._timeout)
            except asyncio.CancelledError:
                self._delegate_drain(future, handle)
                delegated = True
                raise
            except TimeoutError:
                self._delegate_drain(future, handle)
                delegated = True
                raise
            handle.assert_alive()
            confirmed = await self._registry.confirm_snapshot_live(snapshot.version, registration)
            if not confirmed:
                raise _generic_failure()
            handle.assert_alive()
            return registration.scope
        finally:
            if not delegated:
                if handle is not None:
                    handle.close()
                self._release()

    async def aclose(self) -> None:
        """Stop admission, drain every capture, and close the executor once."""

        self._bind_loop()
        if self._closed:
            return
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(
                self._close_owned(), name="model-proxy-peer-attestor-close"
            )
        task = self._close_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def __aenter__(self) -> LinuxModelProxyPeerAttestor:
        self._bind_loop()
        if self._closing or self._closed:
            raise _generic_failure()
        return self

    async def __aexit__(self, _type: object, _value: object, _traceback: object) -> None:
        await self.aclose()

    def _reserve(self) -> asyncio.AbstractEventLoop:
        loop = self._bind_loop()
        if self._closing or self._closed:
            raise _generic_failure()
        if not self._admission.acquire(blocking=False):
            raise ModelProxyPeerAttestationSaturated("peer attestation capacity unavailable")
        self._inflight += 1
        self._idle.clear()
        return loop

    def _release(self) -> None:
        if self._inflight < 1:
            raise RuntimeError("peer attestation admission underflow")
        self._inflight -= 1
        self._admission.release()
        if self._inflight == 0:
            self._idle.set()

    def _delegate_drain(
        self,
        future: asyncio.Future[ModelProxyProcessRegistration],
        handle: PeerProcessHandle,
    ) -> None:
        task = asyncio.create_task(
            self._drain(future, handle), name="model-proxy-peer-attestor-drain"
        )
        self._drainers.add(task)
        task.add_done_callback(self._drainers.discard)

    async def _drain(
        self,
        future: asyncio.Future[ModelProxyProcessRegistration],
        handle: PeerProcessHandle,
    ) -> None:
        cancelled = False
        try:
            while True:
                try:
                    await asyncio.shield(future)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    if future.done():
                        break
                except Exception:
                    break
        finally:
            handle.close()
            self._release()
        if cancelled:
            raise asyncio.CancelledError

    async def _close_owned(self) -> None:
        await self._idle.wait()
        if self._drainers:
            await asyncio.gather(*tuple(self._drainers), return_exceptions=True)
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._closed = True

    def _bind_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("peer attestor cannot cross event loops")
        return loop


def _ancestry_bound(value: object) -> int:
    if type(value) is not int or not 1 <= value <= HARD_MAX_MODEL_PROXY_ANCESTRY:
        raise ValueError("max_ancestry must be within the hard ancestry bound")
    return value


def _capacity_bound(value: object) -> int:
    if type(value) is not int or not 1 <= value <= HARD_MAX_CONCURRENT_PEER_CAPTURES:
        raise ValueError("max_concurrent_captures must be within its hard bound")
    return value


def _timeout_bound(value: object) -> float:
    if type(value) not in {int, float}:
        raise TypeError("timeout_seconds must be a finite positive number")
    numeric = float(cast(int | float, value))
    if (
        not math.isfinite(numeric)
        or numeric <= 0
        or numeric > HARD_MAX_MODEL_PROXY_ATTESTATION_TIMEOUT_SECONDS
    ):
        raise ValueError("timeout_seconds must be within the hard timeout bound")
    return numeric


def _generic_failure() -> ModelProxyPeerAttestationError:
    return ModelProxyPeerAttestationError("model-proxy peer attestation failed")


__all__ = [
    "LinuxModelProxyPeerAttestor",
    "ModelProxyPeerAttestationError",
    "ModelProxyPeerAttestationSaturated",
]
