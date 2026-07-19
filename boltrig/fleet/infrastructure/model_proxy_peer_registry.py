"""Atomic supervisor-owned registry for live Codex App Server identities.

Registration is performed inside ``CodexCellSupervisor.start`` against the
just-spawned child pid, before any protocol traffic, so no instant exists in
which a live App Server is unregistered; a cell that fails to register is reaped
and never handed out. Issuance is likewise bound to liveness: ``authorize`` mints
under the same lock ``revoke`` takes.

THE OPEN GAP ([2026] VJS-CC-VJS 5): attestation proves the PROVENANCE of a
connection, not the INTEGRITY of the program that makes it. Under the present
shared uid, a hostile cell can rewrite a sibling's auth helper (0700 inside the
sibling's MUTABLE cell root) or its config.toml ``auth.command``. The sibling's
App Server then executes attacker-supplied code as its own direct child, which
passes ancestry attestation ON THE MERITS - correct ancestor, cgroup, pid
namespace, uid and gid - and receives the sibling's bearer. Because the scope
carries a tenant id, that is a cross-tenant compromise.

An earlier version of this docstring claimed a rewritten helper "cannot defeat"
attestation because it would still have to connect from a descendant of the
registered App Server. That reasoning holds only under a boundary that stops one
cell rewriting another's helper. Under one uid it is circular: the attacker
chooses what the descendant is. Until a kernel-enforced per-cell boundary over
attestation inputs is enacted and asserted at startup, this machinery must not be
read as conferring cross-cell isolation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TypeAlias

from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
)

DEFAULT_MAX_REGISTERED_MODEL_PROXY_CELLS = 4_096
HARD_MAX_REGISTERED_MODEL_PROXY_CELLS = 100_000
MAX_LINUX_ID = 2**32 - 2
MAX_REGISTRY_VERSION = 2**63 - 1

LogicalCellKey: TypeAlias = tuple[ModelProxyAssignmentScope, str]
ExactProcessKey: TypeAlias = tuple[int, int, str, int, str]
LivePidKey: TypeAlias = tuple[str, int]


class ModelProxyPeerRegistryError(RuntimeError):
    """A process registration operation failed closed."""


class ModelProxyPeerRegistryCapacityExceeded(ModelProxyPeerRegistryError):
    """Retained registration and terminal state reached its hard bound."""


class ModelProxyCellAlreadyRegistered(ModelProxyPeerRegistryError):
    """A logical cell identifier is non-reusable."""


class ModelProxyProcessAlreadyRegistered(ModelProxyPeerRegistryError):
    """A live or exact process identity collides with retained state."""


class ModelProxyRegistrationState(str, Enum):
    LIVE = "live"
    TERMINAL = "terminal"


@dataclass(frozen=True, repr=False)
class ModelProxyProcessRegistration:
    """Internal registration receipt; repr never exposes process metadata."""

    scope: ModelProxyCellScope = field(repr=False)
    expected_uid: int = field(repr=False)
    expected_gid: int = field(repr=False)
    sequence: int = field(repr=False)
    state: ModelProxyRegistrationState = field(default=ModelProxyRegistrationState.LIVE, repr=False)

    def __post_init__(self) -> None:
        if type(self.scope) is not ModelProxyCellScope:
            raise TypeError("scope must be an exact ModelProxyCellScope")
        _linux_id("expected uid", self.expected_uid)
        _linux_id("expected gid", self.expected_gid)
        if type(self.sequence) is not int or self.sequence < 1:
            raise TypeError("registration sequence must be a positive integer")
        if type(self.state) is not ModelProxyRegistrationState:
            raise TypeError("registration state must be exact")

    def __repr__(self) -> str:
        return f"ModelProxyProcessRegistration(state={self.state.value!r}, <redacted>)"


@dataclass(frozen=True, repr=False)
class ModelProxyRegistrySnapshot:
    """Immutable live set pinned to one exact registry mutation version."""

    version: int
    registrations: tuple[ModelProxyProcessRegistration, ...]

    def __post_init__(self) -> None:
        if type(self.version) is not int or not 0 <= self.version <= MAX_REGISTRY_VERSION:
            raise TypeError("registry snapshot version must fit a signed BIGINT")
        if type(self.registrations) is not tuple or any(
            type(item) is not ModelProxyProcessRegistration for item in self.registrations
        ):
            raise TypeError("registry snapshot registrations must be exact")

    def __repr__(self) -> str:
        return "ModelProxyRegistrySnapshot(<redacted>)"


class ModelProxyProcessRegistry:
    """Bounded registry with durable logical-cell tombstones.

    The supervisor owns this object.  Registrations cannot be updated or
    reused: a revoked cell remains terminal until the registry is discarded as
    part of an explicit supervisor restart.
    """

    def __init__(self, *, max_cells: int = DEFAULT_MAX_REGISTERED_MODEL_PROXY_CELLS) -> None:
        self._max_cells = _capacity(max_cells)
        self._records: dict[LogicalCellKey, ModelProxyProcessRegistration] = {}
        self._exact_processes: dict[ExactProcessKey, LogicalCellKey] = {}
        self._live_pids: dict[LivePidKey, LogicalCellKey] = {}
        self._next_sequence = 1
        self._version = 0
        self._lock = asyncio.Lock()

    async def register(
        self,
        scope: ModelProxyCellScope,
        *,
        expected_uid: int,
        expected_gid: int,
    ) -> ModelProxyProcessRegistration:
        if type(scope) is not ModelProxyCellScope:
            raise TypeError("scope must be an exact ModelProxyCellScope")
        uid = _linux_id("expected uid", expected_uid)
        gid = _linux_id("expected gid", expected_gid)
        logical = _logical_key(scope)
        exact = _exact_process_key(scope)
        live_pid = (scope.boot_id, scope.pid)
        async with self._lock:
            if logical in self._records:
                raise ModelProxyCellAlreadyRegistered("logical cell is non-reusable")
            if exact in self._exact_processes or live_pid in self._live_pids:
                raise ModelProxyProcessAlreadyRegistered("process identity is already registered")
            if len(self._records) >= self._max_cells:
                raise ModelProxyPeerRegistryCapacityExceeded("process registry capacity exceeded")
            next_version = _next_version(self._version)
            registration = ModelProxyProcessRegistration(
                scope=scope,
                expected_uid=uid,
                expected_gid=gid,
                sequence=self._next_sequence,
            )
            self._records[logical] = registration
            self._exact_processes[exact] = logical
            self._live_pids[live_pid] = logical
            self._next_sequence += 1
            self._version = next_version
            return registration

    async def revoke(self, scope: ModelProxyCellScope) -> bool:
        if type(scope) is not ModelProxyCellScope:
            raise TypeError("scope must be an exact ModelProxyCellScope")
        logical = _logical_key(scope)
        async with self._lock:
            current = self._records.get(logical)
            if current is None or current.scope != scope:
                raise ModelProxyPeerRegistryError("process registration is unavailable")
            next_version = _next_version(self._version)
            if current.state is ModelProxyRegistrationState.TERMINAL:
                self._version = next_version
                return False
            terminal = replace(current, state=ModelProxyRegistrationState.TERMINAL)
            self._records[logical] = terminal
            self._live_pids.pop((scope.boot_id, scope.pid), None)
            self._version = next_version
            return True

    async def authorize[T](
        self, scope: ModelProxyCellScope, issue: Callable[[], Awaitable[T]]
    ) -> T:
        """Run ``issue`` only while ``scope`` is registered LIVE, under the lock.

        Attestation and issuance are otherwise two separate steps, so a cell could
        be revoked (or its ingress closed) in between and a valid bearer would still
        be minted and delivered. ``revoke`` takes the same lock, so running the mint
        inside it makes "attested" and "still live at mint" one indivisible fact.

        ``issue`` must not re-enter this registry: it is called with the lock held.
        """

        if type(scope) is not ModelProxyCellScope:
            raise TypeError("scope must be an exact ModelProxyCellScope")
        if not callable(issue):
            raise TypeError("issue must be an awaitable callable")
        async with self._lock:
            current = self._records.get(_logical_key(scope))
            if (
                current is None
                or current.scope != scope
                or current.state is not ModelProxyRegistrationState.LIVE
            ):
                raise ModelProxyPeerRegistryError(
                    "process registration is not live at issuance"
                )
            return await issue()

    async def snapshot_live(self) -> ModelProxyRegistrySnapshot:
        async with self._lock:
            registrations = tuple(
                sorted(
                    (
                        registration
                        for registration in self._records.values()
                        if registration.state is ModelProxyRegistrationState.LIVE
                    ),
                    key=lambda item: item.sequence,
                )
            )
            return ModelProxyRegistrySnapshot(self._version, registrations)

    async def confirm_snapshot_live(
        self, version: int, registration: ModelProxyProcessRegistration
    ) -> bool:
        if type(version) is not int or not 0 <= version <= MAX_REGISTRY_VERSION:
            return False
        if type(registration) is not ModelProxyProcessRegistration:
            return False
        async with self._lock:
            current = self._records.get(_logical_key(registration.scope))
            return (
                self._version == version
                and current is registration
                and current.state is ModelProxyRegistrationState.LIVE
            )

    async def retained_count(self) -> int:
        async with self._lock:
            return len(self._records)


def _logical_key(scope: ModelProxyCellScope) -> LogicalCellKey:
    return scope.assignment, scope.cell_id


def _exact_process_key(scope: ModelProxyCellScope) -> ExactProcessKey:
    return (
        scope.pid,
        scope.pid_start_ticks,
        scope.boot_id,
        scope.pid_namespace_inode,
        scope.cgroup_identity_digest,
    )


def _linux_id(label: str, value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_LINUX_ID:
        raise ValueError(f"{label} must be a valid Linux identity")
    return value


def _capacity(value: object) -> int:
    if type(value) is not int or not 1 <= value <= HARD_MAX_REGISTERED_MODEL_PROXY_CELLS:
        raise ValueError("max_cells must be within the hard registry bound")
    return value


def _next_version(current: int) -> int:
    if current >= MAX_REGISTRY_VERSION:
        raise ModelProxyPeerRegistryCapacityExceeded("registry mutation version exhausted")
    return current + 1


__all__ = [
    "ModelProxyCellAlreadyRegistered",
    "ModelProxyPeerRegistryCapacityExceeded",
    "ModelProxyPeerRegistryError",
    "ModelProxyProcessAlreadyRegistered",
    "ModelProxyProcessRegistration",
    "ModelProxyProcessRegistry",
    "ModelProxyRegistrySnapshot",
    "ModelProxyRegistrationState",
]
