"""Trusted single-tenant read-only Codex phase-cell provider ([2026] VJS-CC-VJS 2).

This is the trusted-posture ``CodexPhaseCellProvider``: it provisions one
read-only Codex cell, stands up a per-cell loopback model proxy, and mints the
cell's short-TTL scoped bearer from the child's REAL ``/proc`` identity. It is
lawful ONLY off production: ``acquire`` calls ``require_codex_trusted_posture``
before anything, and ``build_runtime`` re-asserts the same wall at the composition
seam (D1). It never flips a production gate - it runs under the existing
``allow_test_only_runtime`` gate with ``production_ready`` left False (D4).

The credential split (D2): the real upstream key is injected server-side by the
proxy and NEVER placed in the cell environment (the supervisor is constructed with
``auth=None``, so ``sanitized_environment`` never sets ``CODEX_ACCESS_TOKEN``); the
cell holds only the short-TTL scoped bearer, delivered to a SINGLE service uid as a
0600 file (D5).

D3 caveat: the cell scope is the child's real ``/proc`` identity, but WITHOUT the
SO_PEERCRED cross-check production issuance performs over the unix socket. It is
observed, not attested, and must never be mistaken for a peer-attested identity.
The only difference from production is that one cross-check, so the trusted path
maps onto the future SO_PEERCRED swap with an identical ``auth.command`` and
bearer-file delivery contract (D5). Read-only reasoning cutover only; write/effects
are separately court-gated (PR8, D6).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from boltrig.config import Settings
from boltrig.fleet.application.model_proxy_grants import (
    DEFAULT_MODEL_PROXY_TTL_SECONDS,
    PhaseScopedModelProxyGrantBroker,
)
from boltrig.fleet.codex_trusted_wall import require_codex_trusted_posture
from boltrig.fleet.domain import PhaseAssignmentRef
from boltrig.fleet.domain.model_proxy_scope import ModelProxyCellScope
from boltrig.fleet.infrastructure.codex_cell_supervisor import (
    CodexCellSupervisor,
    InitializedCodexCell,
)
from boltrig.fleet.infrastructure.codex_model_proxy_server import (
    BearerDigestLookup,
    PerCellModelProxyServer,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_ingress import (
    CodexTrustedIngress,
    build_ingress_bearer_issuer,
    capture_cell_identity,
    select_ingress_socket_path,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    AdmittedCodexCell,
    CodexPhaseAdmission,
    CodexPhaseAdmissionSource,
    CodexPreflightProbe,
    CodexRuntimeAdmissionError,
)
from boltrig.fleet.infrastructure.codex_runtime_config import CodexReasoningEffort
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    GenerationHolder,
    TrustedProxyProvisionError,
    materialize_helper,
    model_policy_digest,
    read_only_budget,
    render_trusted_config,
    tracking_bearer_verifier,
    write_cell_config,
)
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistry,
)

@dataclass(eq=False)
class _TrustedSession:
    """Live per-cell resources the reaper releases when the cell closes."""

    proxy: PerCellModelProxyServer
    scope: ModelProxyCellScope
    ingress: CodexTrustedIngress
    holder: GenerationHolder
    reaper: asyncio.Task[None]


class TrustedProxyCodexPhaseCellProvider:
    """Provision a trusted read-only Codex cell behind a per-cell loopback proxy."""

    def __init__(
        self,
        *,
        source: CodexPhaseAdmissionSource,
        supervisor: CodexCellSupervisor,
        probe: CodexPreflightProbe,
        broker: PhaseScopedModelProxyGrantBroker,
        grant_store: BearerDigestLookup,
        registry: ModelProxyProcessRegistry,
        attestor: LinuxModelProxyPeerAttestor,
        stack_root: Path,
        upstream_base_url: str,
        upstream_key: str,
        http_client: httpx.AsyncClient,
        generation: int = 1,
        reasoning_effort: CodexReasoningEffort = CodexReasoningEffort.HIGH,
        ttl_seconds: int = DEFAULT_MODEL_PROXY_TTL_SECONDS,
        env: Mapping[str, str] | None = None,
        settings: Settings | None = None,
    ) -> None:
        if type(supervisor) is not CodexCellSupervisor:
            raise TypeError("supervisor must be an exact CodexCellSupervisor")
        # D2 guard: the supervisor MUST be constructed with auth=None so the child
        # environment never carries the upstream key (CODEX_ACCESS_TOKEN).
        if supervisor._auth is not None:
            raise TrustedProxyProvisionError(
                "trusted Codex supervisor must be constructed with auth=None (D2)"
            )
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be a positive integer")
        if type(reasoning_effort) is not CodexReasoningEffort:
            raise TypeError("reasoning_effort must be an exact CodexReasoningEffort")
        if type(registry) is not ModelProxyProcessRegistry:
            raise TypeError("registry must be an exact ModelProxyProcessRegistry")
        if type(attestor) is not LinuxModelProxyPeerAttestor:
            raise TypeError("attestor must be an exact LinuxModelProxyPeerAttestor")
        if not isinstance(stack_root, Path) or not stack_root.is_absolute():
            raise TrustedProxyProvisionError("stack_root must be an absolute Path")
        self._source = source
        self._supervisor = supervisor
        self._probe = probe
        self._broker = broker
        self._grant_store = grant_store
        self._registry = registry
        self._attestor = attestor
        self._stack_root = stack_root
        self._upstream_base_url = upstream_base_url
        self._upstream_key = upstream_key
        self._client = http_client
        self._generation = generation
        self._reasoning_effort = reasoning_effort
        self._ttl = ttl_seconds
        self._env = env
        self._settings = settings
        self._sessions: dict[str, _TrustedSession] = {}

    async def acquire(self, assignment: PhaseAssignmentRef) -> AdmittedCodexCell:
        if type(assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        # D1: fail closed BEFORE any provisioning or bearer mint can happen.
        require_codex_trusted_posture(self._env, self._settings)
        admission = await self._source.admit(assignment)
        if type(admission) is not CodexPhaseAdmission or admission.assignment != assignment:
            raise CodexRuntimeAdmissionError("admission source returned another assignment")
        holder = GenerationHolder(self._generation)
        proxy: PerCellModelProxyServer | None = None
        cell: InitializedCodexCell | None = None
        scope: ModelProxyCellScope | None = None
        ingress: CodexTrustedIngress | None = None
        try:
            # The ceiling is the compiled policy's effective tools, which admission
            # requires to be empty on the quarantined read-only lane. Deriving it
            # here (rather than hard-coding empty) means the PR8 write phase widens
            # by policy, never by editing the proxy.
            proxy = await self._start_proxy(
                holder, frozenset(admission.compilation.policy.enabled_tools)
            )
            model_id = admission.compilation.policy.model.model_id
            layout = admission.layout
            # The socket path is derived from the (pre-start) cell id, so the helper
            # the App Server will exec can be materialized before start.
            socket_path = select_ingress_socket_path(self._stack_root, layout.cell_id)
            self._write_cell_config(
                cell_id=layout.cell_id,
                cell_root=layout.cell_root,
                codex_home=layout.codex_home,
                model_id=model_id,
                proxy_port=proxy.port,
                socket_path=socket_path,
            )
            cell = await self._supervisor.start(admission.layout)
            # FINDING #1: build the registered scope from the App Server's real
            # /proc identity via the SAME capture attestation uses (canonical cgroup
            # digest), so the auth-helper child attests against a matching ancestor.
            identity = capture_cell_identity(assignment, cell.metadata.cell_id, cell.metadata.pid)
            scope = identity.scope
            # Register + bind + serve BEFORE the preflight/first turn, so the App
            # Server's first lazy auth.command call always finds a live registration.
            ingress = CodexTrustedIngress(self._registry, self._attestor)
            await ingress.start(
                identity=identity,
                socket_path=socket_path,
                bearer_issuer=build_ingress_bearer_issuer(
                    broker=self._broker,
                    registry=self._registry,
                    model_id=model_id,
                    policy_digest=model_policy_digest(model_id, self._reasoning_effort),
                    budget=read_only_budget(),
                    ttl_seconds=self._ttl,
                    holder=holder,
                ),
            )
            preflight = await self._probe.probe(cell.client, admission.skill_plan)
            admitted = AdmittedCodexCell(admission, cell, preflight)
            self._register_session(cell, proxy, scope, ingress, holder)
            return admitted
        except BaseException:
            await self._teardown(proxy, scope, ingress)
            if cell is not None:
                await _close_ignoring_failure(cell)
            raise

    async def _start_proxy(
        self, holder: GenerationHolder, allowed_tools: frozenset[str]
    ) -> PerCellModelProxyServer:
        proxy = PerCellModelProxyServer(
            verify_bearer=tracking_bearer_verifier(self._grant_store, holder),
            upstream_base_url=self._upstream_base_url,
            upstream_key=self._upstream_key,
            client=self._client,
            allowed_tools=allowed_tools,
        )
        await proxy.start()
        return proxy

    def _write_cell_config(
        self,
        *,
        cell_id: str,
        cell_root: Path,
        codex_home: Path,
        model_id: str,
        proxy_port: int,
        socket_path: Path,
    ) -> None:
        helper_path, helper_sha256 = materialize_helper(cell_root, cell_id, socket_path)
        config_toml = render_trusted_config(
            cell_id=cell_id,
            cell_root=cell_root,
            codex_home=codex_home,
            helper_path=helper_path,
            helper_sha256=helper_sha256,
            model_id=model_id,
            policy_digest=model_policy_digest(model_id, self._reasoning_effort),
            reasoning_effort=self._reasoning_effort,
            proxy_port=proxy_port,
        )
        write_cell_config(codex_home, config_toml)

    def _register_session(
        self,
        cell: InitializedCodexCell,
        proxy: PerCellModelProxyServer,
        scope: ModelProxyCellScope,
        ingress: CodexTrustedIngress,
        holder: GenerationHolder,
    ) -> None:
        reaper = asyncio.create_task(
            self._reap(cell, proxy, scope, ingress),
            name=f"codex-trusted-reap-{cell.metadata.cell_id}",
        )
        self._sessions[cell.metadata.cell_id] = _TrustedSession(
            proxy, scope, ingress, holder, reaper
        )

    async def _reap(
        self,
        cell: InitializedCodexCell,
        proxy: PerCellModelProxyServer,
        scope: ModelProxyCellScope,
        ingress: CodexTrustedIngress,
    ) -> None:
        try:
            await cell.wait_closed()
        finally:
            await self._teardown(proxy, scope, ingress)
            self._sessions.pop(cell.metadata.cell_id, None)

    async def _teardown(
        self,
        proxy: PerCellModelProxyServer | None,
        scope: ModelProxyCellScope | None,
        ingress: CodexTrustedIngress | None,
    ) -> None:
        if ingress is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await ingress.aclose()
        if proxy is not None:
            with contextlib.suppress(Exception):
                await proxy.aclose()
        if scope is not None:
            with contextlib.suppress(Exception):
                await self._broker.cancel_cell(scope)


async def _close_ignoring_failure(cell: InitializedCodexCell) -> None:
    task: asyncio.Task[None] = asyncio.ensure_future(cell.aclose())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
    except BaseException:
        pass


__all__ = [
    "TrustedProxyCodexPhaseCellProvider",
    "TrustedProxyProvisionError",
]
